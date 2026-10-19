import { test, expect } from '@playwright/test';
import { execFileSync, spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import os from 'node:os';
import path from 'node:path';

const repo = path.resolve(import.meta.dirname, '../..');

test('offline import ignores historical size and safely refreshes an existing PDF', async ({ page }) => {
  const root = mkdtempSync(path.join(os.tmpdir(), 'survey-import-e2e-'));
  const demo = path.join(root, 'demo');
  const python = (code: string, ...args: string[]) => execFileSync('uv', ['run', 'python', '-c', code, ...args], { cwd: repo, stdio: 'pipe' });
  let server: ReturnType<typeof spawn> | undefined;
  try {
    execFileSync('uv', ['run', 'python', 'scripts/review_demo.py', demo], { cwd: repo, stdio: 'pipe' });
    const target = path.join(demo, 'scans/demo/synthetic.pdf');
    const original = path.join(root, 'downloaded.pdf');
    renameSync(target, original);
    const replacement = path.join(root, 'replacement.pdf');
    python(`
import sys
from pypdf import PdfReader, PdfWriter
writer = PdfWriter()
for page in PdfReader(sys.argv[1]).pages:
    writer.add_page(page)
writer.add_metadata({"/Title": "New downloaded version"})
writer.write(sys.argv[2])
`, original, replacement);
    writeFileSync(path.join(demo, 'catalogue.json'), JSON.stringify({ version: 1, batches: [{ region: 'demo', pdf: 'synthetic.pdf', file_id: 'synthetic', size: 1, md5: '0'.repeat(32) }] }));
    const port = await new Promise<number>((resolve, reject) => {
      const listener = createServer().listen(0, '127.0.0.1', () => {
        const address = listener.address() as { port: number };
        listener.close(() => resolve(address.port));
      });
      listener.on('error', reject);
    });
    const url = `http://127.0.0.1:${port}`;
    const log: string[] = [];
    server = spawn('uv', ['run', 'python', '-c', `
import sys
from pathlib import Path
import uvicorn
from survey.review.api import Settings, create_app
root, port = Path(sys.argv[1]), int(sys.argv[2])
settings = Settings(root / "scans", root / "data checkout", root / "flags.jsonl", root / "cache", port=port, sync_interval=3600, scan_catalogue=root / "catalogue.json")
uvicorn.run(create_app(settings), host="127.0.0.1", port=port)
`, demo, String(port)], { cwd: repo, detached: true, stdio: ['ignore', 'pipe', 'pipe'] });
    server.stdout?.on('data', data => log.push(String(data)));
    server.stderr?.on('data', data => log.push(String(data)));
    await expect.poll(async () => {
      if (server?.exitCode !== null) throw new Error(log.join(''));
      try { return (await (await fetch(`${url}/api/health`)).json()).ready; }
      catch { return false; }
    }, { timeout: 30_000 }).toBe(true);
    await page.addInitScript(() => localStorage.setItem('review-help-seen', 'true'));
    await page.goto(url);
    await page.getByLabel('Your name').fill('Import reviewer');
    await page.getByRole('button', { name: 'Start reviewing', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Download scans', exact: true })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Import downloaded PDF', exact: true })).toBeEnabled();
    for (const file of [original, replacement]) {
      const saved = page.waitForResponse(response => response.url().endsWith('/api/scan-batches/demo/import') && response.request().method() === 'POST');
      await page.getByLabel('Choose downloaded PDF').setInputFiles(file);
      expect((await saved).status()).toBe(200);
      await expect(page.getByText('Scans ready', { exact: true })).toBeVisible();
      expect(readFileSync(target)).toEqual(readFileSync(file));
    }
    const backups = path.join(demo, 'scans/demo/.scan-backups');
    expect(readdirSync(backups)).toHaveLength(1);
    expect(readFileSync(path.join(backups, readdirSync(backups)[0]))).toEqual(readFileSync(original));
    await page.getByRole('button', { name: 'Review', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Accept 04', exact: true })).toBeEnabled();
  } finally {
    if (server?.pid && server.exitCode === null) {
      const exited = new Promise<void>(resolve => server!.once('exit', () => resolve()));
      process.kill(-server.pid, 'SIGTERM');
      await exited;
    }
    rmSync(root, { recursive: true, force: true });
  }
});
