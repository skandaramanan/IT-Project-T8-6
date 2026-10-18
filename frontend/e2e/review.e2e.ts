// The real reviewer, in a real browser, against the real backend (synthetic demo data).
// Vitest covers input rules with a fake API; these cover what only the whole stack can:
// cookies, idempotent retries, two reviewers, missing scans and Git sharing.
import { type ChildProcess, execFileSync, spawn } from 'node:child_process';
import { mkdtempSync, rmSync, renameSync, writeFileSync, readFileSync, realpathSync } from 'node:fs';
import os from 'node:os';
import { createServer } from 'node:net';
import path from 'node:path';
import { test as base, expect, type Page } from '@playwright/test';

const repo = path.resolve(import.meta.dirname, '../..');

function disposableSample(directory: string): string {
  const sample = realpathSync(directory);
  const manifest = JSON.parse(readFileSync(path.join(sample, 'manifest.json'), 'utf8'));
  const remote = path.join(sample, 'remote.git');
  expect(manifest.remote).toBe(remote);
  expect(realpathSync(remote)).toBe(remote);
  const gitUrls = (...args: string[]) => execFileSync('git', [
    '-C', path.join(sample, 'data checkout'), 'remote', 'get-url', ...args, 'origin',
  ], { encoding: 'utf8' }).trim().split(/\r?\n/);
  expect(gitUrls('--all')).toEqual([remote]);
  expect(gitUrls('--push', '--all')).toEqual([remote]);
  return sample;
}

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
const test = base.extend<{ demo: string; app: string; generatedQueue: boolean; productionRecords: boolean }>({
  generatedQueue: [false, { option: true }],
  productionRecords: [false, { option: true }],
  demo: async ({ generatedQueue, productionRecords }, use) => {
    if (productionRecords) {
      const sample = disposableSample(process.env.SURVEY_ACCEPTANCE_SAMPLE!);
      await use(sample);
      return;
    }
    // Outside the repo: the backend refuses a data checkout inside the code checkout.
    const root = mkdtempSync(path.join(os.tmpdir(), 'survey-e2e-'));
    const demo = path.join(root, 'demo');
    execFileSync('uv', ['run', 'python', 'scripts/review_demo.py', demo], {
      cwd: repo,
      stdio: 'pipe',
    });
    if (generatedQueue) {
      writeFileSync(path.join(demo, 'flags.jsonl'), execFileSync(
        'uv', ['run', 'survey', 'flags', path.join(demo, 'data checkout', 'results')],
        { cwd: repo },
      ));
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

test.describe('matching production records and scans', () => {
  test.use({ productionRecords: true });
  test.setTimeout(120_000);
  const productionExpect = expect.configure({ timeout: 30_000 });
  test.skip(!process.env.SURVEY_ACCEPTANCE_SAMPLE, 'Prepare a fresh disposable sample with scripts/review_acceptance.py');

  test('the real produced queue saves exact digits through the built browser and local sharing', async ({ page }) => {
    await signIn(page, 'Production Browser Verification');
    const queue = await (await page.request.get('/api/queue')).json();
    expect(queue.diagnostics).toEqual([]);
    await page.getByRole('button', { name: 'Review', exact: true }).first().click();
    // Follow the actual printed field label; no invented IDs, values or scores.
    await page.getByRole('button', { name: /^Weekly Rent / }).first().click();
    await productionExpect(page.getByRole('heading', { name: 'Weekly Rent', exact: true })).toBeVisible();
    await productionExpect(page.getByRole('button', { name: 'Correct', exact: true })).toBeEnabled();
    await expect(page.getByRole('img')).toHaveJSProperty('complete', true);
    await correct(page, '009');
    await productionExpect(page.getByText('Saved: Weekly Rent 009')).toBeVisible();
    await page.getByRole('button', { name: 'Share now' }).click();
    await productionExpect(sharing(page)).toHaveText(/Shared/);
    await page.reload();
    await page.getByLabel('Your name').fill('Production Browser Verification');
    await page.getByRole('button', { name: 'Start reviewing' }).click();
    await page.getByRole('button', { name: 'Continue', exact: true }).first().click();
    await productionExpect(corrected(page)).toBeVisible();
  });
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
  await page.getByRole('button', { name: 'Correct', exact: true }).click();
  await page.getByLabel('Your correction').fill(value);
  await page.getByRole('button', { name: `Save ${value}` }).click();
}

const corrected = (page: Page) =>
  page.getByRole('button', { name: /^Weekly Rent 009 .*CORRECTED$/ });
const sharing = (page: Page) => page.getByRole('banner').getByRole('status');

test('production sample preflight rejects an alternate push destination', async ({ demo }) => {
  const sample = realpathSync(demo);
  writeFileSync(path.join(sample, 'manifest.json'), JSON.stringify({ remote: path.join(sample, 'remote.git') }));
  expect(disposableSample(demo)).toBe(sample);
  execFileSync('git', ['-C', path.join(sample, 'data checkout'), 'config', 'remote.origin.pushurl', path.join(sample, 'different-local-remote.git')]);
  expect(() => disposableSample(demo)).toThrow();
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
  await expect(page.getByRole('button', { name: 'Correct', exact: true })).toBeDisabled();
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

test.describe('production queue producer', () => {
  test.use({ generatedQueue: true });

  test('generated identity and numeric flags open controls and retain exact corrections', async ({ page }) => {
    await signIn(page);
    const queue = await (await page.request.get('/api/queue')).json();
    expect(queue.diagnostics).toEqual([]);
    expect(queue.items.length).toBeGreaterThan(3);
    await page.getByRole('button', { name: 'Review', exact: true }).click();
    // Printed order starts with identity. It is deliberately accept-only.
    await expect(page.getByRole('heading', { name: 'Municipality', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Accept 27' })).toBeEnabled();
    await page.getByRole('button', { name: /^Weekly Rent 04 / }).click();
    await expect(page.getByRole('button', { name: 'Accept 04' })).toBeEnabled();
    await expect(page.getByRole('img')).toHaveJSProperty('complete', true);
    await correct(page, '009');
    await expect(page.getByText('Saved: Weekly Rent 009')).toBeVisible();
    const after = await (await page.request.get('/api/queue')).json();
    const saved = after.items.find((item: { label: string; review_state: string }) =>
      item.label === 'Weekly Rent' && item.review_state === 'corrected');
    expect(saved.field.value).toBe('009');
    expect(saved.field.review.history[0].before.value).toBe('04');
    await page.reload();
    await page.getByLabel('Your name').fill('Playwright Reviewer');
    await page.getByRole('button', { name: 'Start reviewing' }).click();
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
    await expect(corrected(page)).toBeVisible();
  });
});
