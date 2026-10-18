import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';

const output = fileURLToPath(new URL('./test-results', import.meta.url));

export default defineConfig({
  testDir: './e2e',
  outputDir: output,
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 15_000 },
  reporter: [['list'], ['json', { outputFile: `${output}/results.json` }]],
  use: {
    actionTimeout: 20_000,
    browserName: 'chromium',
    headless: true,
    viewport: { width: 1440, height: 1000 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
});
