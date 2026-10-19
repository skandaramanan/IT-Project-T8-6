// Browser journeys against the real backend. Each test gets its own synthetic demo
// and server (see e2e/review.e2e.ts), so no test depends on another's decisions.
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'e2e',
  // .e2e.ts, so Vitest's default *.test/*.spec glob never picks these up.
  testMatch: '*.e2e.ts',
  forbidOnly: !!process.env.CI,
  workers: 1,
  use: { trace: 'retain-on-failure' },
});
