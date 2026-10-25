// Independent edge probes: real typing/pasting must reach validation unchanged.
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import App from './App';
import type { Item } from './api';

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('review-help-seen', 'true');
});

async function openIdentity(kind: NonNullable<Item['identity_kind']>) {
  const item: Item = {
    id: 'identity', region: '216418', batch: 'scan.pdf', record_id: '03-0005-01',
    dwelling_id: 'dwelling', address: null, region_title: null, card_score: 0.91,
    field_kind: 'numeric', identity_kind: kind, field_path: '/dwelling/dwelling_no',
    label: 'Identity', field: { value: '1', status: 'ok', confidence: 0.91 },
    review_state: 'pending', version: 'v1', source: { pdf: 'scan.pdf', page: 1, card_id: 'card' },
    scan_url: '/scan.png', reason: '', allowed_actions: ['accept', 'correct'],
    warnings: [], diagnostics: [], resolved: false, undo_decision_id: null, code_list: [],
  };
  const summary = { dwellings: 1, queued_dwellings: 1, completed_dwellings: 0,
    average_card_score: 0.91, scored_cards: 1, unscored_cards: 0 };
  const fetch = vi.fn(async (input: string) => {
    const path = String(input);
    const data = path === '/api/health' ? { ready: true, diagnostics: [] }
      : path === '/api/regions' ? { regions: [{ region: '216418', has_records: true }] }
      : path === '/api/session' ? { reviewer: 'Edge reviewer' }
      : path === '/api/sync/status' ? { state: 'uploaded', pending: false }
      : path.includes('/items?') ? { items: [item], total: 1, resolved: 0, unresolved: 1, diagnostics: [] }
      : path.startsWith('/api/dwellings?') ? {
        dwellings: [{ id: 'dwelling', region: item.region, total: 1, resolved: 0, unresolved: 1,
          status: 'pending', score: 0.91, diagnostics: [], card_count: 1, first_item_id: item.id, next_item_id: item.id }],
        summary, all_regions: summary, diagnostics: [], total: 1, unresolved: 1,
      } : item;
    return new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fetch);
  const user = userEvent.setup();
  render(<App />);
  await user.type(await screen.findByLabelText('Your name'), 'Edge reviewer');
  await user.click(screen.getByRole('button', { name: 'Start reviewing' }));
  await user.click(await screen.findByRole('button', { name: 'Review' }));
  await screen.findByRole('heading', { name: 'Identity' });
  fireEvent.load(screen.getByRole('img'));
  await user.click(screen.getByRole('button', { name: 'Fix' }));
  const input = screen.getByLabelText('Your correction');
  await user.clear(input);
  return { user, input, fetch };
}

it.each([
  ['municipality', '003', 'typing'],
  ['household', '123', 'typing'],
  ['dwelling', '1234AB', 'typing'],
  ['municipality', '003', 'pasting'],
  ['household', '123', 'pasting'],
  ['dwelling', '1234AB', 'pasting'],
] as const)('shows the full overlength %s reading %s via %s and blocks Enter instead of truncating it', async (kind, reading, method) => {
  const { user, input, fetch } = await openIdentity(kind);
  if (method === 'typing') await user.type(input, reading);
  else await user.paste(reading);
  expect(input).toHaveValue(reading);
  expect(screen.getByRole('button', { name: 'Save (check the identity)' })).toBeDisabled();
  await user.keyboard('{Enter}');
  expect(fetch.mock.calls.some(([path]) => path.endsWith('/decisions'))).toBe(false);
});
