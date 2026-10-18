import { test as base, expect, type Page } from '@playwright/test';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createInterface } from 'node:readline';
import { once } from 'node:events';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../..', import.meta.url));

type Item = {
  id: string; region: string; label: string; field_path: string;
  source: { pdf: string; page: number };
  field: { value: string | null };
  undo_decision_id: string | null;
};
type Control = {
  urls: Record<string, string>;
  call: (action: string, extra?: object) => Promise<any>;
};

// Private stdin/stdout control for process restarts and transport failure injection.
// The production application exposes no test endpoints.
const test = base.extend<{ control: Control }>({
  control: async ({}, use, info) => {
    const workspace = process.env.REVIEW_TEST_WORKSPACE;
    if (!workspace) throw new Error('Set REVIEW_TEST_WORKSPACE; see docs/review-github-acceptance.md');
    const child: ChildProcessWithoutNullStreams = spawn(
      process.env.REVIEW_TEST_PYTHON ?? path.join(root, '.venv/bin/python'),
      [path.join(root, 'scripts/review_github_test.py'), 'browser-session', workspace],
      { stdio: ['pipe', 'pipe', 'pipe'] },
    );
    let errors = '';
    child.stderr.on('data', (data) => { errors += data.toString(); });
    const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
    async function receive() {
      const line = await lines.next();
      if (line.done) throw new Error(`Browser backend controller exited: ${errors}`);
      return JSON.parse(line.value);
    }
    try {
      const ready = await receive();
      await use({ urls: ready.urls, call: async (action, extra = {}) => {
        child.stdin.write(JSON.stringify({ action, ...extra }) + '\n');
        const response = await receive();
        if (!response.ok) throw new Error(response.error);
        return response.result;
      } });
    } finally {
      // EOF lets Python restore temporary Git settings and stop both backends.
      child.stdin.end();
      if (child.exitCode === null) {
        await Promise.race([once(child, 'exit'), new Promise<void>((resolve) => {
          const timer = setTimeout(() => { child.kill('SIGTERM'); resolve(); }, 25_000);
          timer.unref();
        })]);
      }
      await info.attach('controller-log', { body: errors, contentType: 'text/plain' });
    }
  },
});

async function signIn(page: Page, url: string, reviewer: string, region = 'demo-a') {
  await page.goto(url);
  const seenHelp = await page.evaluate(() => localStorage.getItem('review-help-seen') === 'true');
  await page.getByLabel('Your name', { exact: true }).fill(reviewer);
  await page.getByRole('button', { name: 'Start reviewing', exact: true }).click();
  // First-use help is deliberately exercised, then dismissed.
  const help = page.getByRole('dialog');
  if (!seenHelp) {
    await expect(help).toBeVisible();
    await help.getByRole('button', { name: 'Close dialog', exact: true }).click();
  }
  await page.getByLabel('Region', { exact: true }).selectOption(region);
  await expect(page.getByRole('heading', { name: 'Review queue', exact: true })).toBeVisible();
}

async function openRent(page: Page) {
  await page.getByRole('button', { name: /^(Review|Continue|Reopen)$/ }).first().click();
  await expect(page.getByRole('region', { name: 'Fields to review on this card', exact: true })).toBeVisible();
  // Select the queued Weekly Rent row even if a previous scenario resolved it.
  if (!await page.getByRole('heading', { name: 'Weekly Rent', exact: true }).isVisible()) {
    await page.getByRole('button', { name: /^Weekly Rent / }).first().click();
  }
  await expect(page.getByRole('heading', { name: 'Weekly Rent', exact: true })).toBeVisible();
}

async function correct(page: Page, value: string): Promise<Item> {
  await openRent(page);
  await expect(page.getByRole('button', { name: 'Correct', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Correct', exact: true }).click();
  await page.getByLabel('Your correction', { exact: true }).fill(value);
  const saved = page.waitForResponse(r => r.url().includes('/decisions') && r.request().method() === 'POST');
  await page.getByRole('button', { name: `Save ${value}`, exact: true }).click();
  const response = await saved;
  expect(response.ok()).toBeTruthy();
  const result = await response.json();
  expect(result.saved_locally).toBe(true);
  expect(result.item.field.value).toBe(value);
  return result.item;
}

async function share(page: Page) {
  const sent = page.waitForResponse(r => r.url().endsWith('/api/sync') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Share now', exact: true }).click();
  const result = await (await sent).json();
  expect(result.state).toBe('uploaded');
  await expect(page.getByRole('banner').getByRole('status')).toContainText('Shared');
}

function expectation(item: Item, value: string | null, reviewer: string) {
  return { item, value, reviewer };
}

test('correction and GitHub upload', async ({ page, control }) => {
  await signIn(page, control.urls.A, 'Browser correction');
  const item = await correct(page, '009');
  await share(page);
  await control.call('verify', { expectations: [expectation(item, '009', 'Browser correction')] });
});

test('backend restart retains correction and permits durable undo', async ({ page, control }) => {
  await signIn(page, control.urls.A, 'Browser restart');
  const before = await (await page.request.get(control.urls.A + '/api/queue?region=demo-a')).json();
  const item = await correct(page, '017');
  const original = before.items.find((i: Item) => i.id === item.id).field.value;
  await control.call('restart');
  await signIn(page, control.urls.A, 'Browser restart');
  const stored = await (await page.request.get(`${control.urls.A}/api/review-items/${item.id}`)).json();
  expect(stored.field.value).toBe('017');
  await openRent(page);
  await page.getByRole('button', { name: 'Undo latest decision on this field', exact: true }).click();
  await share(page);
  await control.call('verify', { expectations: [expectation(item, original, 'Browser restart')] });
});

test('Save and Exit retains failed upload and recovery shares it', async ({ page, control }) => {
  await signIn(page, control.urls.A, 'Browser recovery');
  const item = await correct(page, '023');
  await control.call('fail-push');
  await page.getByRole('button', { name: 'Save and Exit', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Sharing has not been confirmed');
  await expect(page.getByRole('dialog')).toContainText('Your decisions remain on this computer');
  await control.call('restart');
  await control.call('restore-push');
  await signIn(page, control.urls.A, 'Browser recovery');
  await share(page);
  await control.call('verify', { expectations: [expectation(item, '023', 'Browser recovery')] });
  await page.getByRole('button', { name: 'Save and Exit', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Shared with the team');
});

test('simultaneous reviewers preserve different regions and converge', async ({ browser, control }) => {
  const ca = await browser.newContext();
  const cb = await browser.newContext();
  try {
    const a = await ca.newPage(), b = await cb.newPage();
    await Promise.all([signIn(a, control.urls.A, 'Browser A', 'demo-a'), signIn(b, control.urls.B, 'Browser B', 'demo-b')]);
    const [ia, ib] = await Promise.all([correct(a, '031'), correct(b, '042')]);
    await Promise.all([share(a), share(b)]);
    const proof = await control.call('verify', { expectations: [expectation(ia, '031', 'Browser A'), expectation(ib, '042', 'Browser B')] });
    await Promise.all([share(a), share(b)]);
    for (const page of [a, b]) {
      const status = await (await page.request.get(new URL('/api/sync/status', page.url()).href)).json();
      expect(status.head).toBe(proof.sha);
      for (const item of [ia, ib]) {
        const incoming = await (await page.request.get(new URL(`/api/review-items/${item.id}`, page.url()).href)).json();
        expect(incoming.field.value).toBe(item.field.value);
      }
    }
  } finally {
    await ca.close();
    await cb.close();
  }
});
