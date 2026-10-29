// The real reviewer, in a real browser, against the real backend (synthetic demo data).
// Vitest covers input rules with a fake API; these cover what only the whole stack can:
// cookies, idempotent retries, two reviewers, missing scans and Git sharing.
import { type ChildProcess, execFileSync, spawn } from 'node:child_process';
import { appendFileSync, mkdtempSync, readFileSync, rmSync, renameSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import { createServer } from 'node:net';
import path from 'node:path';
import { test as base, expect, type Page } from '@playwright/test';

const repo = path.resolve(import.meta.dirname, '../..');

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer().listen(0, '127.0.0.1', () => {
      const { port } = server.address() as { port: number };
      server.close(() => resolve(port));
    });
    server.on('error', reject);
  });
}

async function waitForHealth(url: string, server: ChildProcess, log: string[]) {
  for (let i = 0; i < 120; i++) {
    if (server.exitCode !== null) throw new Error(`Review server exited:\n${log.join('')}`);
    try {
      if ((await fetch(`${url}/api/health`)).ok) return;
    } catch {
      // not listening yet
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`Review server never became healthy:\n${log.join('')}`);
}

// A fresh demo and backend per test: one writer per data checkout (D029).
const test = base.extend<{ demo: string; app: string; identityFields: boolean; highConfidenceContext: boolean; retainedCase: boolean }>({
  identityFields: [false, { option: true }],
  highConfidenceContext: [false, { option: true }],
  retainedCase: [false, { option: true }],
  demo: async ({ identityFields, highConfidenceContext, retainedCase }, use) => {
    // Outside the repo: the backend refuses a data checkout inside the code checkout.
    const root = mkdtempSync(path.join(os.tmpdir(), 'survey-e2e-'));
    const demo = path.join(root, 'demo');
    execFileSync('uv', ['run', 'python', 'scripts/review_demo.py', demo], {
      cwd: repo,
      stdio: 'pipe',
    });
    if (identityFields) {
      appendFileSync(path.join(demo, 'flags.jsonl'), [
        '/dwelling/households/0/municipality',
        '/dwelling/households/0/dwelling_no',
        '/dwelling/households/0/household_no',
      ].map((field_path) => JSON.stringify({
        region: 'demo', pdf: 'synthetic.pdf', page: 1, field_path, reason: 'Synthetic identity review',
      })).join('\n') + '\n');
    }
    if (highConfidenceContext) {
      const file = path.join(demo, 'data checkout/results/demo.jsonl');
      const record = JSON.parse(readFileSync(file, 'utf8'));
      record.dwelling.households[0].house.age_of_house = { value: '007', status: 'ok', confidence: 0.98 };
      record.dwelling.households[0].coding.weekly_rent.confidence = 0.98;
      writeFileSync(file, JSON.stringify(record) + '\n');
    }
    if (retainedCase) {
      const file = path.join(demo, 'data checkout/results/demo.jsonl');
      const record = JSON.parse(readFileSync(file, 'utf8'));
      const second = record.dwelling.households.pop();
      second.dwelling_no.value = '7';
      second.record_id = '27-0007-02';
      second.relink = { state: 'provisional', reason: 'No associated survey front' };
      record.dwelling.handwritten = { dwelling_no: { value: '6', status: 'ok', confidence: null, source: 'survey-front' } };
      writeFileSync(file, JSON.stringify(record) + '\n' + JSON.stringify({ schema_version: '0.7.0', region: 'demo', batch: 'synthetic.pdf', dwelling: { households: [second] } }) + '\n');
    }
    try {
      await use(demo);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  },
  app: async ({ demo }, use) => {
    const port = await freePort();
    const log: string[] = [];
    // ponytail: process-group kill is POSIX only; Windows needs taskkill /T if e2e runs there.
    const server = spawn(
      'uv',
      [
        'run', 'survey', 'review',
        '--scan-root', path.join(demo, 'scans'),
        '--data-checkout', path.join(demo, 'data checkout'),
        '--flags', path.join(demo, 'flags.jsonl'),
        '--cache', path.join(demo, 'cache'),
        '--port', String(port),
      ],
      { cwd: repo, detached: true, stdio: ['ignore', 'pipe', 'pipe'] },
    );
    server.stdout?.on('data', (d) => log.push(String(d)));
    server.stderr?.on('data', (d) => log.push(String(d)));
    const url = `http://127.0.0.1:${port}`;
    try {
      await waitForHealth(url, server, log);
      await use(url);
    } finally {
      if (server.exitCode === null) process.kill(-server.pid!, 'SIGTERM');
    }
  },
  baseURL: async ({ app }, use) => use(app),
});

async function signIn(page: Page, name = 'Playwright Reviewer') {
  // The first-use welcome dialog (#59) blocks Review; Vitest covers the dialog itself.
  await page.addInitScript(() => localStorage.setItem('review-help-seen', 'true'));
  await page.goto('/');
  await page.getByLabel('Your name').fill(name);
  await page.getByRole('button', { name: 'Start reviewing' }).click();
}

async function openFirstField(page: Page) {
  await page.getByRole('button', { name: 'Review', exact: true }).click();
  // Accept switches on only once the real scan has loaded.
  await expect(page.getByRole('button', { name: 'Accept 04' })).toBeEnabled();
}

async function correct(page: Page, value: string) {
  await page.getByRole('button', { name: 'Fix', exact: true }).click();
  await page.getByLabel('Your correction').fill(value);
  await page.getByRole('button', { name: `Save ${value}` }).click();
}

const corrected = (page: Page) =>
  page.getByRole('button', { name: /^Weekly Rent 009 .*CORRECTED$/ });
const sharing = (page: Page) => page.getByRole('banner').getByRole('status');

test.describe('optional high-confidence context', () => {
  test.use({ highConfidenceContext: true });
  test('keeps queued high-confidence fields visible and expands read-only context without changing progress', async ({ page }) => {
    await signIn(page);
    await openFirstField(page);
    const optional = page.locator('details.optional-fields');
    const summary = optional.locator('summary');
    await expect(summary).toHaveText('High-confidence fields not queued for review (1)');
    await expect(optional).not.toHaveAttribute('open');
    await expect(page.getByText('Age of House', { exact: true })).toBeHidden();
    await expect(page.getByRole('heading', { name: 'Weekly Rent', exact: true })).toBeVisible();
    await summary.press('Enter');
    await expect(optional).toHaveAttribute('open');
    await expect(optional.getByText('Age of House', { exact: true })).toBeVisible();
    await expect(optional.getByText('007', { exact: true })).toBeVisible();
    await expect(optional.getByRole('button')).toHaveCount(0);
    await page.getByRole('button', { name: 'Accept 04' }).click();
    await expect(page.getByRole('heading', { name: 'Garden', exact: true })).toBeVisible();
    await expect(optional).toHaveAttribute('open');
    await page.getByRole('button', { name: 'Accept 1', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Card reviewed', exact: true })).toBeVisible();
    await expect(page.getByText('All 2 queued fields on this card are reviewed.')).toBeVisible();
    await page.getByRole('button', { name: 'Next card', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Accept 12', exact: true })).toBeEnabled();
    const firstCard = await page.getByRole('option', { name: /Coding card.*household 1/ }).getAttribute('value');
    await page.getByLabel('Card to review').selectOption(firstCard!);
    await expect(optional).not.toHaveAttribute('open');
  });
});

test('a correction is saved, shared and still marked after a reload (NFR-05)', async ({ page }) => {
  await signIn(page);
  await openFirstField(page);
  await expect(page.getByRole('img')).toHaveJSProperty('complete', true);

  await correct(page, '009');
  await expect(page.getByText('Saved: Weekly Rent 009')).toBeVisible();
  await expect(corrected(page)).toBeVisible();

  await expect(page.getByRole('heading', { name: 'Garden' })).toBeVisible();
  await page.getByRole('button', { name: 'Accept 1' }).click();
  await page.getByRole('button', { name: 'Undo' }).click();
  await expect(page.getByText(/Undo saved on this computer/)).toBeVisible();

  await expect(sharing(page)).toHaveText(/not shared yet/);
  await page.getByRole('button', { name: 'Share now' }).click();
  await expect(sharing(page)).toHaveText(/Shared/);

  await page.reload();
  await page.getByLabel('Your name').fill('Playwright Reviewer');
  await page.getByRole('button', { name: 'Start reviewing' }).click();
  // The undone accept doesn't count: only the correction is decided.
  const row = page.getByRole('row', { name: /27-0006-01/ });
  await expect(row).toContainText('1 decided');
  await row.getByRole('button', { name: 'Continue' }).click();
  await expect(corrected(page)).toBeVisible();
});

test('a save whose response is lost is retried once, not recorded twice', async ({ page }) => {
  await signIn(page);
  await openFirstField(page);
  let itemId = '';
  // The backend saves, then the browser loses the response: the uncertain case.
  await page.route('**/api/review-items/*/decisions', async (route) => {
    itemId = new URL(route.request().url()).pathname.split('/')[3];
    await route.fetch();
    await route.abort('failed');
  }, { times: 1 });

  await correct(page, '009');
  await expect(page.getByText(/Saving has not been confirmed/)).toBeVisible();
  await expect(page.getByLabel('Your correction')).toHaveValue('009');
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByText('Saved: Weekly Rent 009')).toBeVisible();

  const { history } = await (await page.request.get(`/api/review-items/${itemId}/history`)).json();
  expect(history).toHaveLength(1);
});

test('two reviewers on one field: the second is stopped, not silently overwriting', async ({
  page,
  browser,
  baseURL,
}) => {
  const other = await (await browser.newContext({ baseURL })).newPage();
  await signIn(page, 'Reviewer A');
  await signIn(other, 'Reviewer B');
  await openFirstField(page);
  await openFirstField(other);

  const saved = page.waitForResponse('**/api/review-items/*/decisions');
  await correct(page, '009');
  const itemId = new URL((await saved).url()).pathname.split('/')[3];
  await expect(page.getByText('Saved: Weekly Rent 009')).toBeVisible();

  // B still sees the old 04 and tries to accept it.
  await other.getByRole('button', { name: 'Accept 04' }).click();
  await expect(other.getByRole('alert')).toBeVisible();
  await other.getByRole('button', { name: 'Reload current field' }).click();
  await expect(other.getByRole('button', { name: 'Accept 009' })).toBeVisible();
  await expect(other.getByText('Machine read: 04. The original is kept.')).toBeVisible();

  const { history } = await (await page.request.get(`/api/review-items/${itemId}/history`)).json();
  expect(history).toHaveLength(1);
  expect(history[0]).toMatchObject({ action: 'correct', reviewer: 'Reviewer A' });
  await other.context().close();
});

test('a missing scan keeps every decision switched off', async ({ page, demo }) => {
  rmSync(path.join(demo, 'scans', 'demo', 'synthetic.pdf'));
  await signIn(page);
  await page.getByRole('button', { name: 'Review', exact: true }).click();
  await expect(page.getByText("Image couldn't load")).toBeVisible();
  await expect(page.getByRole('button', { name: 'Accept 04' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Fix', exact: true })).toBeDisabled();
});

test('when sharing fails the decision stays saved, and shares once the remote is back', async ({
  page,
  demo,
}) => {
  const remote = path.join(demo, 'remote.git');
  await signIn(page);
  await openFirstField(page);
  renameSync(remote, `${remote}.away`);

  await correct(page, '009');
  await expect(page.getByText('Saved: Weekly Rent 009')).toBeVisible();
  await page.getByRole('button', { name: 'Share now' }).click();
  await expect(sharing(page)).toHaveText(/couldn't share yet/);
  await expect(page.getByText(/saved on this computer but not shared/)).toBeVisible();

  renameSync(`${remote}.away`, remote);
  await page.getByRole('button', { name: 'Share now' }).click();
  await expect(sharing(page)).toHaveText(/Shared/);
  expect(
    execFileSync('git', ['-C', remote, 'log', '--oneline', 'review-data'], { encoding: 'utf8' }),
  ).toMatch(/save reviewed region records/);
});

test('a lost session asks for the name again and the typed correction survives', async ({ page }) => {
  await signIn(page);
  await openFirstField(page);
  // As after a backend restart: the session cookie no longer counts.
  await page.context().clearCookies();

  await correct(page, '009');
  await expect(page.getByText(/Enter your reviewer name/)).toBeVisible();
  await page.getByRole('button', { name: 'Start reviewing' }).click();
  await expect(page.getByLabel('Your correction')).toHaveValue('009');
  await page.getByRole('button', { name: 'Save 009' }).click();
  await expect(page.getByText('Saved: Weekly Rent 009')).toBeVisible();
});

test('reaccepting an accepted field advances and completing it again preserves original history', async ({ page }) => {
  await signIn(page);
  await openFirstField(page);
  const firstSave = page.waitForResponse('**/api/review-items/*/decisions');
  await page.getByRole('button', { name: 'Accept 04', exact: true }).click();
  const firstId = new URL((await firstSave).url()).pathname.split('/')[3];
  await expect(page.getByRole('heading', { name: 'Garden', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Previous field', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Weekly Rent', exact: true })).toBeVisible();
  const repeatedSave = page.waitForResponse('**/api/review-items/*/decisions');
  await page.getByRole('button', { name: 'Accept 04', exact: true }).click();
  const repeatedResponse = await repeatedSave;
  expect(repeatedResponse.status()).toBe(422);
  expect((await repeatedResponse.json()).error.code).toBe('no_op');
  await expect(page.getByRole('heading', { name: 'Garden', exact: true })).toBeVisible();
  const finalSave = page.waitForResponse('**/api/review-items/*/decisions');
  await page.getByRole('button', { name: 'Accept 1', exact: true }).click();
  const finalId = new URL((await finalSave).url()).pathname.split('/')[3];
  await expect(page.getByRole('heading', { name: 'Card reviewed', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Stay here', exact: true }).click();
  await page.getByRole('button', { name: 'Previous field', exact: true }).click();
  await page.getByRole('button', { name: 'Next field', exact: true }).click();
  await page.getByRole('button', { name: 'Accept 1', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Card reviewed', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Stay here', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Next card', exact: true })).toBeEnabled();
  for (const itemId of [firstId, finalId]) {
    const { history } = await (await page.request.get(`/api/review-items/${itemId}/history`)).json();
    expect(history).toHaveLength(1);
    expect(history[0]).toMatchObject({ action: 'accept', reviewer: 'Playwright Reviewer' });
  }
});

test('card completion stays explicit, reviewed fields remain visible, and survey text is easy to open', async ({ page }) => {
  await signIn(page);
  await openFirstField(page);
  await expect(page.getByRole('button', { name: 'Previous field', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Next field', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Garden', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Previous field', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Weekly Rent', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Accept 04', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Garden', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Accept 1', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Card reviewed', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Garden', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /^Weekly Rent 04 .*ACCEPTED$/ })).toBeVisible();
  await expect(page.getByRole('banner')).toContainText('High · reviewed');
  await page.getByRole('button', { name: 'Stay here', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Card reviewed', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Card reviewed', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Accept 1', exact: true }).click();
  await page.getByRole('button', { name: 'Next card', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Garden', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Open survey front', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Address', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Fix', exact: true }).click();
  await page.getByLabel('Your correction', { exact: true }).fill('Café 王\nSecond line');
  await page.getByRole('button', { name: 'Save correction', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Card reviewed', exact: true })).toBeVisible();
  await page.reload();
  await page.getByLabel('Your name').fill('Playwright Reviewer');
  await page.getByRole('button', { name: 'Start reviewing', exact: true }).click();
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page.getByRole('button', { name: 'Open survey front', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Address', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Fix', exact: true }).click();
  await expect(page.getByLabel('Your correction', { exact: true })).toHaveValue('Café 王\nSecond line');
});

for (const action of ['accept', 'correct'] as const) {
  test(`${action} shows saving over the decision buttons without moving the scan`, async ({ page }) => {
    await signIn(page);
    await openFirstField(page);
    if (action === 'correct') {
      await page.getByRole('button', { name: 'Fix', exact: true }).click();
      await page.getByLabel('Your correction').fill('009');
    }
    const button = page.getByRole('button', { name: action === 'accept' ? 'Accept 04' : 'Save 009', exact: true });
    await button.scrollIntoViewIfNeeded();
    const actions = page.locator('.acts');
    const scan = page.getByRole('region', { name: 'Scanned card', exact: true });
    const before = { scan: await scan.boundingBox(), actions: await actions.boundingBox() };
    expect(before.scan).not.toBeNull();
    expect(before.actions).not.toBeNull();
    let release!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    await page.route('**/api/review-items/*/decisions', async (route) => {
      await held;
      await route.continue();
    }, { times: 1 });
    await button.click();
    const saving = actions.getByRole('status');
    await expect(saving).toHaveText('Saving…');
    await expect(button).toBeDisabled();
    const during = { scan: await scan.boundingBox(), actions: await actions.boundingBox() };
    expect(during.scan).toEqual(before.scan);
    expect(during.actions).toEqual(before.actions);
    const overlay = await saving.boundingBox();
    expect(overlay).not.toBeNull();
    expect(Math.abs(overlay!.y - before.actions!.y)).toBeLessThanOrEqual(1);
    expect(overlay!.width).toBeGreaterThanOrEqual(before.actions!.width - 2);
    expect(await saving.evaluate((element) => getComputedStyle(element).position)).toBe('absolute');
    if (action === 'accept') await page.screenshot({ path: test.info().outputPath('saving-overlay.png'), fullPage: true });
    release();
    await expect(page.getByRole('heading', { name: 'Garden', exact: true })).toBeVisible();
    await expect(page.getByText(action === 'accept' ? 'Accepted: Weekly Rent 04' : 'Saved: Weekly Rent 009')).toBeVisible();
    const feedback = page.locator('.review-feedback');
    await expect(feedback.getByRole('button', { name: 'Undo', exact: true })).toBeVisible();
    expect(await feedback.evaluate((element) => getComputedStyle(element).position)).toBe('fixed');
    expect(await scan.boundingBox()).toEqual(before.scan);
    await feedback.getByRole('button', { name: 'Dismiss saved confirmation' }).click();
    await expect(feedback).toBeEmpty();
    expect(await scan.boundingBox()).toEqual(before.scan);
  });
}

test('the compact queue keeps a long region title within a narrow viewport and reveals its tools', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.route('**/api/regions', async (route) => {
    const result = await (await route.fetch()).json();
    result.regions = result.regions.map((region: { title?: string }) => ({
      ...region, title: 'A very long descriptive region title with many streets and survey districts '.repeat(5),
    }));
    await route.fulfill({ json: result });
  });
  await page.route('**/api/scan-batches?*', async (route) => route.fulfill({ json: {
    region: 'demo', pdf: 'synthetic.pdf', size: 4, downloaded: 0,
    state: 'missing', automatic_download: false, active_region: null,
    local_file_exists: false, drive_url: 'https://drive.google.com/file/d/demo/view', error: null,
  } }));
  await signIn(page);
  const region = page.getByLabel('Region', { exact: true });
  await expect(region).toBeVisible();
  const bounds = (await region.boundingBox())!;
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(375);
  const overflowing = await page.evaluate(() => [...document.querySelectorAll('body *')]
    .filter((element) => element.getBoundingClientRect().right > innerWidth && getComputedStyle(element).display !== 'none')
    .map((element) => ({ tag: element.tagName, class: element.className, right: element.getBoundingClientRect().right })).slice(0, 15));
  expect(await page.evaluate(() => document.documentElement.scrollWidth), JSON.stringify(overflowing)).toBeLessThanOrEqual(375);
  await expect(page.getByText(/Machine average/)).toBeHidden();
  await expect(page.getByText(/All regions:/)).toBeHidden();
  await expect(page.getByRole('button', { name: 'Review summary (.csv)' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Refresh queue' })).toBeVisible();
  await page.getByText('Review details and scans', { exact: true }).click();
  await expect(page.getByText(/Machine average/)).toBeVisible();
  await expect(page.getByRole('progressbar', { name: 'Region progress' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Review summary (.csv)' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Refresh queue' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Download scans', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Import downloaded PDF', exact: true })).toBeEnabled();
});


test.describe('identity review', () => {
  test.use({ identityFields: true });
  test('identity corrections update displayed record IDs and Undo restores them', async ({ page }) => {
    await signIn(page);
    await page.getByRole('button', { name: 'Review', exact: true }).click();
    const fields = page.getByRole('region', { name: 'Fields to review on this card' });
    await expect(page.getByRole('button', { name: 'Fix', exact: true })).toBeEnabled();
    const cases = [
      { label: 'Municipality', value: '03', recordId: '03-0006-01', invalid: '003' },
      { label: 'Number of Dwelling', value: '0006b', recordId: '27-0006B-01', invalid: '1234AB' },
      { label: 'Number of Household', value: '03', recordId: '27-0006-03', invalid: '123' },
    ];
    let decisionRequests = 0;
    page.on('request', (request) => {
      if (request.url().endsWith('/decisions')) decisionRequests += 1;
    });
    for (const { label, value, recordId, invalid } of cases) {
      if (!(await page.getByRole('heading', { name: label, exact: true }).isVisible())) {
        await fields.getByRole('button', { name: new RegExp(`^${label} `) }).click();
      }
      await expect(page.getByRole('button', { name: 'Fix', exact: true })).toBeEnabled();
      // Use browser typing: fill() bypasses maxLength and hid truncation defects.
      await page.getByRole('button', { name: 'Fix', exact: true }).click();
      const correction = page.getByLabel('Your correction');
      await correction.fill('');
      await correction.pressSequentially(invalid);
      await expect(correction).toHaveValue(invalid);
      await expect(page.getByRole('button', { name: 'Save (check the identity)' })).toBeDisabled();
      const beforeInvalidEnter = decisionRequests;
      await correction.press('Enter');
      await expect(correction).toHaveValue(invalid);
      expect(decisionRequests).toBe(beforeInvalidEnter);
      await page.getByRole('button', { name: 'Cancel', exact: true }).click();
      const saved = page.waitForResponse('**/api/review-items/*/decisions');
      await correct(page, value);
      const result = await (await saved).json();
      expect(result.item.record_id).toBe(recordId);
      expect(result.item.field.value).toBe(value);
      await expect(page.getByRole('banner')).toContainText(recordId);
      await page.getByRole('button', { name: 'Undo', exact: true }).click();
      await expect(page.getByText(/Undo saved on this computer/)).toBeVisible();
      await expect(page.getByRole('banner')).toContainText('27-0006-01');
    }
  });

  test('duplicate confirmation precedes saving and an unqueued peer identity can be repaired', async ({ page, demo }) => {
    await signIn(page);
    await page.getByRole('button', { name: 'Review', exact: true }).click();
    const fields = page.getByRole('region', { name: 'Fields to review on this card' });
    await fields.getByRole('button', { name: /^Number of Household / }).click();
    await expect(page.getByRole('button', { name: 'Fix', exact: true })).toBeEnabled();
    await correct(page, '2');
    const dialog = page.getByRole('dialog', { name: 'Confirm duplicate identity' });
    await expect(dialog).toBeVisible();
    const file = path.join(demo, 'data checkout/results/demo.jsonl');
    expect(JSON.parse(readFileSync(file, 'utf8')).dwelling.households[0].household_no.value).toBe('1');
    await dialog.getByRole('button', { name: 'Compare', exact: true }).click();
    await expect(dialog.getByRole('heading', { name: /Coding page 2/ })).toBeVisible();
    await dialog.getByRole('button', { name: 'Save anyway' }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByText('Duplicate identity on coding page 1.')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Municipality', exact: true })).toBeVisible();
    const before = await (await page.request.get('/api/queue')).json();
    await page.getByRole('button', { name: 'Compare', exact: true }).click();
    const compare = page.getByRole('dialog', { name: 'Compare coding cards' });
    await compare.getByRole('button', { name: 'Fix Number of Household on page 2' }).click();
    await expect(page.getByLabel('Your correction')).toHaveValue('2');
    await expect(page.getByText(/Identity correction outside your assigned queue/)).toBeVisible();
    await page.getByLabel('Your correction').fill('3');
    await expect(page.getByRole('button', { name: 'Save 3', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: 'Save 3', exact: true }).click();
    await expect(page.getByText(/Saved: Number of Household 3/)).toBeVisible();
    const after = await (await page.request.get('/api/queue')).json();
    expect(after.total).toBe(before.total);
    const saved = JSON.parse(readFileSync(file, 'utf8'));
    expect(saved.dwelling.households.every((h: { flags: string[] }) => !h.flags.includes('duplicate_record_id'))).toBe(true);
  });
});

test.describe('retained evidence', () => {
  test.use({ identityFields: true, retainedCase: true });
  test('retains former scans and notes, then undoes the link while keeping a later building correction', async ({ page, demo }) => {
    await signIn(page);
    await page.getByRole('button', { name: 'Review', exact: true }).first().click();
    const fields = page.getByRole('region', { name: 'Fields to review on this card' });
    await fields.getByRole('button', { name: /^Number of Dwelling / }).click();
    await expect(page.getByRole('button', { name: 'Fix', exact: true })).toBeEnabled();
    await correct(page, '7');
    await expect(page.getByText(/Saved: Number of Dwelling 7/)).toBeVisible();
    await page.getByRole('button', { name: 'Link to dwelling' }).click();
    const dialog = page.getByRole('dialog', { name: 'Link coding card to dwelling' });
    await dialog.getByRole('radio', { name: /coding pages 2/ }).check();
    await expect(dialog.getByRole('button', { name: 'Save link' })).toBeDisabled();
    await dialog.getByRole('checkbox').check();
    await dialog.getByRole('button', { name: 'Save link' }).click();
    await page.getByRole('button', { name: 'Retained evidence (1)' }).click();
    const retained = page.getByRole('dialog', { name: 'Retained supplementary evidence' });
    await expect(retained.getByText('Synthetic interview notes\nSecond line', { exact: true })).toBeVisible();
    await expect(retained.getByRole('img', { name: 'Original scan, page 3' })).toBeVisible();
    await retained.getByRole('button', { name: 'Close dialog' }).click();
    await fields.getByRole('button', { name: /^Garden / }).click();
    await expect(page.getByRole('button', { name: 'Fix', exact: true })).toBeEnabled();
    await correct(page, '3');
    await expect(page.getByText(/Saved: Garden 3/)).toBeVisible();
    await page.getByRole('button', { name: 'Undo last link' }).click();
    await expect(page.getByText(/Undo saved on this computer/)).toBeVisible();
    const rows = readFileSync(path.join(demo, 'data checkout/results/demo.jsonl'), 'utf8').trim().split('\n').map((s) => JSON.parse(s));
    const restored = rows.find((r) => r.dwelling.households.some((h: { cards: { page: number }[] }) => h.cards[0].page === 1));
    const card = restored.dwelling.households.find((h: { cards: { page: number }[] }) => h.cards[0].page === 1);
    expect(card.dwelling_no.value).toBe('7');
    expect(card.house.garden.value).toBe('3');
    expect(card.retained_supplements).toBeUndefined();
    expect(restored.dwelling.cards.map((c: { page: number }) => c.page)).toEqual([3, 4]);
  });
});
