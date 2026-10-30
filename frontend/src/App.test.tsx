// Decisions must wait for evidence, preserve exact input, and recover safely.
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { dwellingKey, reviewSummaryCsv } from './api';
import type { DwellingQueue, Item, Saved, Sync } from './api';

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('review-help-seen', 'true');
});

const shared: Sync = { state: 'uploaded', pending: false };
function field(id = 'rent', overrides: Partial<Item> = {}): Item {
  return {
    id,
    region: '216418',
    batch: 'original.pdf',
    record_id: '03-0005-01',
    dwelling_id: 'dwelling1',
    address: '194-6 Belmore Rd.',
    region_title: 'Camberwell 03 - Part 1',
    card_score: 0.91,
    field_kind: 'numeric_sentinel',
    code_list: [
      { value: '00', label: 'Free' },
      { value: '01', label: 'Rates unknown (owner)' },
    ],
    field_path: '/dwelling/households/0/coding/weekly_rent',
    label: 'Weekly Rent',
    field: {
      value: '05',
      code: null,
      label: null,
      status: 'ok',
      confidence: 0.91,
    },
    review_state: 'pending',
    version: 'v1',
    source: { pdf: 'original.pdf', page: 21, card_id: 'card1' },
    scan_url: '/api/scans/card1',
    reason: 'score 0.91',
    allowed_actions: ['accept', 'correct', 'no_data', 'illegible'],
    warnings: [],
    diagnostics: [],
    resolved: false,
    undo_decision_id: null,
    ...overrides,
  };
}
function response(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
function backend(items = [field()]) {
  let current = items;
  let version = 1;
  const mutations: { path: string; body: Record<string, string> }[] = [];
  let fail = '';
  let sharing = shared;
  function enrich(item: Item): Item {
    return {
      ...item,
      card_fields: item.card_fields ?? [
        ...current
          .filter(
            (i) =>
              i.dwelling_id === item.dwelling_id && i.source.card_id === item.source.card_id,
          )
          .map((i) => ({
            id: i.id,
            field_path: i.field_path + '/' + i.id,
            label: i.label,
            column: i.column,
            field: i.field,
            review_state: i.review_state,
          })),
        {
          id: null,
          field_path: '/context-only',
          label: 'Type of Family',
          field: { value: '1', status: 'ok' as const, confidence: 0.97 },
          review_state: 'pending' as const,
        },
      ],
      cards:
        item.cards ??
        [
          ...new Map(
            current
              .filter((i) => i.dwelling_id === item.dwelling_id)
              .map((i) => [i.source.card_id, i]),
          ).values(),
        ].map((i, n) => ({
          card_id: i.source.card_id,
          score: i.card_score,
          page: i.source.page,
          household_index: n,
          household_no: String(n + 1),
          record_id: i.record_id,
          first_item_id: i.id,
          next_item_id: i.id,
        })),
    };
  }
  const fetch = vi.fn(async (input: string, options?: RequestInit) => {
    const path = String(input);
    if (path.startsWith('/api/scan-batches')) return response({ error: { message: 'No Drive batch', code: 'batch_not_available' } }, 404);
    if (path === '/api/health') return response({ ready: true, diagnostics: [] });
    if (path === '/api/regions')
      return response({
        regions: [
          { region: '216418', has_records: true, has_scan_folder: true },
          { region: '216461', has_records: false, has_scan_folder: true },
        ],
      });
    if (path === '/api/session')
      return response({ reviewer: JSON.parse(String(options?.body)).name });
    if (path.startsWith('/api/dwellings')) {
      const selected =
        new URLSearchParams(path.split('?')[1]).get('region') === '216418' ? current : [];
      if (path.includes('/items?')) {
        const id = path.split('/')[3];
        const items = selected.filter((i) => i.dwelling_id === id);
        return response({
          items,
          diagnostics: [],
          total: items.length,
          resolved: items.filter((i) => i.resolved).length,
        });
      }
      const grouped = new Map<string, Item[]>();
      for (const item of selected)
        grouped.set(item.dwelling_id, [...(grouped.get(item.dwelling_id) ?? []), item]);
      const dwellings = [...grouped.entries()].map(([id, items]) => {
        const resolved = items.filter((i) => i.resolved).length;
        return {
          id,
          region: items[0].region,
          record_id: items[0].record_id,
          address: items[0].address,
          score: items[0].card_score,
          card_count: new Set(items.map((i) => i.source.card_id)).size,
          total: items.length,
          resolved,
          unresolved: items.length - resolved,
          status: items.some((item) => item.diagnostics.length)
            ? 'blocked'
            : resolved === items.length
              ? 'complete'
              : resolved
                ? 'in_progress'
                : 'pending',
          first_item_id: items[0].id,
          next_item_id: items.find((i) => !i.resolved)?.id ?? null,
          last_reviewer: resolved ? 'Jane Smith' : null,
          last_reviewed_at: null,
        };
      });
      dwellings.sort((a, b) => Number(a.status === 'complete') - Number(b.status === 'complete'));
      const summary = {
        dwellings: dwellings.length,
        queued_dwellings: dwellings.length,
        completed_dwellings: dwellings.filter((d) => d.status === 'complete').length,
        average_card_score: dwellings.length ? 0.91 : null,
        scored_cards: dwellings.length,
        unscored_cards: 0,
      };
      return response({
        dwellings,
        summary,
        all_regions: summary,
        diagnostics: [],
        total: selected.length,
        unresolved: selected.filter((i) => !i.resolved).length,
        region_title: selected[0]?.region_title ?? null,
      });
    }
    if (path === '/api/sync/status' || path === '/api/sync') return response(sharing);
    if (!options?.body)
      return response(enrich(current.find((i) => path.endsWith('/' + i.id))!));
    const body = JSON.parse(String(options.body));
    mutations.push({ path, body });
    if (fail) {
      const code = fail;
      fail = '';
      if (code === 'network') throw new TypeError('Lost connection');
      return response(
        {
          error: {
            code,
            message:
              code === 'stale_version'
                ? 'Region changed; reload before saving'
                : 'Could not save; previous local data retained',
          },
        },
        code === 'stale_version' ? 409 : 500,
      );
    }
    const undo = path.startsWith('/api/decisions/');
    const previous = undo
      ? current.find((i) => i.undo_decision_id === path.split('/')[3])!
      : current.find((i) => path.includes('/' + i.id + '/'))!;
    if (!undo && body.action === 'accept' && previous.review_state === 'accepted')
      return response({ error: { code: 'no_op', message: 'Already accepted' } }, 422);
    const value = undo
      ? '05'
      : body.action === 'correct'
        ? body.value
        : body.action === 'accept'
          ? previous.field.value
          : null;
    const status =
      undo || body.action === 'correct'
        ? 'ok'
        : body.action === 'accept'
          ? previous.field.status
          : body.action;
    const updated: Item = {
      ...previous,
      version: `v${++version}`,
      field: {
        ...previous.field,
        value,
        status,
        review: {
          state: undo ? 'pending' : body.action === 'accept' ? 'accepted' : 'corrected',
          history: [
            ...(previous.field.review?.history ?? []),
            {
              id: `audit-${version}`,
              action: undo ? 'undo' : body.action,
              reviewer: 'Jane Smith',
              timestamp: '2026-10-14T07:00:00Z',
              before: { ...previous.field, review: undefined },
              after: { ...previous.field, value, status, review: undefined },
            },
          ],
        },
      },
      review_state: undo
        ? 'pending'
        : body.action === 'accept'
          ? 'accepted'
          : 'corrected',
      resolved: !undo,
      undo_decision_id: undo ? null : `decision-${previous.id}`,
    };
    current = current.map((i) =>
      i.id === updated.id ? updated : { ...i, version: updated.version },
    );
    const saved: Saved = {
      saved_locally: true,
      item: enrich(updated),
      decision: {
        id: `decision-${previous.id}`,
        action: undo ? 'undo' : body.action,
        reviewer: 'Jane Smith',
        timestamp: '2026-10-13T07:00:00Z',
        before: previous.field,
        after: updated.field,
      },
      sync: sharing,
    };
    return response(saved);
  });
  vi.stubGlobal('fetch', fetch);
  return {
    fetch,
    mutations,
    items: () => current,
    resolveField: (id: string) => {
      current = current.map((i) =>
        i.id === id
          ? {
              ...i,
              resolved: true,
              review_state: 'accepted',
              version: 'external',
            }
          : { ...i, version: 'external' },
      );
    },
    failNext: (code: string) => {
      fail = code;
    },
    sharing: (state: Sync) => {
      sharing = state;
    },
  };
}
async function start(action = 'Review', label = 'Weekly Rent') {
  const user = userEvent.setup();
  render(<App />);
  await user.type(await screen.findByLabelText('Your name'), 'Jane Smith');
  await user.click(screen.getByRole('button', { name: 'Start reviewing' }));
  await user.click(await screen.findByRole('button', { name: action }));
  await screen.findByRole('heading', { name: label });
  return user;
}
function loaded() {
  fireEvent.load(screen.getByRole('img'));
}

describe('review flow', () => {
  it('shows answer, status and score but disables actions until the actual scan loads', async () => {
    const server = backend();
    await start();
    expect(screen.getByText('Readable')).toBeVisible();
    expect(screen.getAllByText('Medium 0.91').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Accept 05' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Fix' })).toBeDisabled();
    fireEvent.error(screen.getByRole('img'));
    expect(screen.getByText("Image couldn't load")).toBeVisible();
    expect(server.mutations).toEqual([]);
    loaded();
    expect(screen.getByRole('button', { name: 'Accept 05' })).toBeEnabled();
  });

  it('preserves leading zeros, retains a failed correction, and retries the same complete request', async () => {
    const server = backend();
    const user = await start();
    loaded();
    await user.click(screen.getByRole('button', { name: 'Fix' }));
    const input = screen.getByLabelText('Your correction');
    await user.clear(input);
    await user.type(input, '009');
    server.failNext('save_failed');
    await user.click(screen.getByRole('button', { name: 'Save 009' }));
    expect(input).toHaveValue('009');
    expect(screen.getByRole('button', { name: '← Queue' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    await screen.findByText(/Saved: Weekly Rent 009/);
    expect(server.mutations[0].body).toEqual(server.mutations[1].body);
    expect(server.mutations[0].body).toMatchObject({
      value: '009',
      expected_version: 'v1',
      action: 'correct',
    });
    expect(server.mutations[0].body).not.toHaveProperty('reviewer');
    expect(screen.getByRole('banner')).toHaveTextContent('Jane Smith');
  });

  it('rejects letters instead of normalizing them into digits', async () => {
    const server = backend();
    const user = await start();
    loaded();
    await user.click(screen.getByRole('button', { name: 'Fix' }));
    await user.clear(screen.getByLabelText('Your correction'));
    await user.type(screen.getByLabelText('Your correction'), 'O4');
    expect(
      screen.getByRole('button', { name: 'Save (fix the digits first)' }),
    ).toBeDisabled();
    expect(server.mutations).toEqual([]);
  });

  it('keeps a stale correction until explicit reload and creates a fresh request', async () => {
    const server = backend();
    const user = await start();
    loaded();
    await user.click(screen.getByRole('button', { name: 'Fix' }));
    await user.clear(screen.getByLabelText('Your correction'));
    await user.type(screen.getByLabelText('Your correction'), '009');
    server.failNext('stale_version');
    await user.click(screen.getByRole('button', { name: 'Save 009' }));
    expect(screen.getByLabelText('Your correction')).toHaveValue('009');
    await user.click(screen.getByRole('button', { name: 'Reload current field' }));
    await screen.findByLabelText('Your correction');
    loaded();
    expect(screen.getByLabelText('Your correction')).toHaveValue('009');
    await user.click(screen.getByRole('button', { name: 'Save 009' }));
    expect(server.mutations[0].body.request_id).not.toBe(
      server.mutations[1].body.request_id,
    );
  });

  it('respects backend accept-only restrictions', async () => {
    backend([
      field('rent', {
        allowed_actions: ['accept'],
        warnings: ['Accept-only field: if wrong, leave unresolved; editing is deferred'],
      }),
    ]);
    await start();
    loaded();
    expect(screen.getByRole('button', { name: 'Fix' })).toBeDisabled();
    expect(
      screen.queryByRole('button', { name: "Can't read it or blank?" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Accept 05' })).toBeEnabled();
  });

  it.each([
    ["Nothing written: it's blank", 'no_data'],
    ["Something's there but I can't read it", 'illegible'],
  ])('saves the status choice %s through the API', async (label, action) => {
    const server = backend();
    const user = await start();
    loaded();
    await user.click(screen.getByRole('button', { name: "Can't read it or blank?" }));
    await user.click(screen.getByRole('button', { name: label }));
    expect(server.mutations[0].body.action).toBe(action);
    expect(server.mutations[0].body).not.toHaveProperty('value');
  });

  it('keeps the original undo body after a lost response', async () => {
    const server = backend();
    const user = await start();
    loaded();
    await user.click(screen.getByRole('button', { name: 'Accept 05' }));
    server.failNext('network');
    await user.click(await screen.findByRole('button', { name: 'Undo' }));
    await user.click(await screen.findByRole('button', { name: 'Try again' }));
    await screen.findByText(/Undo saved on this computer/);
    expect(server.mutations[1]).toEqual(server.mutations[2]);
    expect(server.mutations[1].body.expected_version).toBe('v2');
  });

  it('advances only after save and resets scan readiness for the next field', async () => {
    const server = backend([field(), field('garden', { label: 'Garden' })]);
    const user = await start();
    loaded();
    await user.click(screen.getByRole('button', { name: 'Accept 05' }));
    await screen.findByRole('heading', { name: 'Garden' });
    expect(server.mutations).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Accept 05' })).toBeDisabled();
    loaded();
    expect(screen.getByRole('button', { name: 'Accept 05' })).toBeEnabled();
  });

  it('shows a sharing failure separately from the saved decision and stops on same-region conflicts', async () => {
    const server = backend();
    const user = await start();
    loaded();
    server.sharing({
      state: 'upload_failed',
      pending: true,
      error: { code: 'remote_ahead', message: 'Same region changed' },
    });
    await user.click(screen.getByRole('button', { name: 'Accept 05' }));
    await screen.findByText(/Accepted: Weekly Rent/);
    expect(screen.getByRole('banner')).toHaveTextContent("couldn't share yet");
    expect(screen.getByText(/Stop reviewing/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Accept 05' })).toBeDisabled();
  });

  it('filters requests to one region and displays an empty region honestly', async () => {
    const server = backend();
    const user = await start();
    await user.click(screen.getByRole('button', { name: '← Queue' }));
    await user.selectOptions(screen.getByLabelText('Region'), '216461');
    await screen.findByText('No flagged coding fields in this region.');
    expect(
      server.fetch.mock.calls.some(([url]) => url === '/api/dwellings?region=216461'),
    ).toBe(true);
    expect(server.fetch.mock.calls.some(([url]) => url === '/api/queue')).toBe(false);
  });
});

it('uses backend physical identity even when read numbers are duplicated or missing', () => {
  const a = field('a', { record_id: null, dwelling_id: 'physical-a' });
  const b = field('b', { record_id: null, dwelling_id: 'physical-b' });
  expect(dwellingKey(a)).not.toBe(dwellingKey(b));
});

it('renders a bounded number of dwelling rows, with the rest reachable by paging', async () => {
  backend(
    Array.from({ length: 25 }, (_, n) =>
      field(`id${n}`, {
        record_id: `03-${String(n).padStart(4, '0')}-01`,
        dwelling_id: `dwelling${n}`,
      }),
    ),
  );
  const user = userEvent.setup();
  render(<App />);
  await user.type(await screen.findByLabelText('Your name'), 'Jane Smith');
  await user.click(screen.getByRole('button', { name: 'Start reviewing' }));
  await screen.findByRole('table');
  expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(13);
  await user.click(screen.getByRole('button', { name: 'Next ›' }));
  await user.click(screen.getByRole('button', { name: 'Next ›' }));
  expect(screen.getByText('03-0024-01')).toBeVisible();
  expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(2);
});

it('keeps startup loading visible while health is unavailable', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => new Promise(() => {})),
  );
  render(<App />);
  expect(screen.getByRole('heading', { name: 'Loading the review tool…' })).toBeVisible();
  expect(
    screen.queryByRole('button', { name: 'Start reviewing' }),
  ).not.toBeInTheDocument();
});

it('reports startup diagnostics without exposing review actions', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      response({
        ready: false,
        diagnostics: [{ message: 'Configure an existing scan root' }],
      }),
    ),
  );
  render(<App />);
  await screen.findByRole('heading', {
    name: 'The review tool could not open',
  });
  expect(screen.getByText('Configure an existing scan root')).toBeVisible();
  expect(
    screen.queryByRole('button', { name: 'Start reviewing' }),
  ).not.toBeInTheDocument();
});

it('does not let an older sharing poll overwrite the status returned by a save', async () => {
  const server = backend();
  const original = server.fetch.getMockImplementation()!;
  let resolveStatus: (value: Response) => void = () => {};
  server.fetch.mockImplementation((path, options) =>
    path === '/api/sync/status'
      ? new Promise<Response>((resolve) => {
          resolveStatus = resolve;
        })
      : original(path, options),
  );
  const user = await start();
  loaded();
  server.sharing({ state: 'waiting_to_upload', pending: true });
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await screen.findByText(/Accepted: Weekly Rent/);
  const { act } = await import('@testing-library/react');
  await act(async () => {
    resolveStatus(response(shared));
  });
  expect(screen.getByRole('banner')).toHaveTextContent('Saved here · not shared yet');
});

it('retains the editor when an explicit reload cannot reach the backend', async () => {
  const server = backend();
  const user = await start();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Fix' }));
  await user.clear(screen.getByLabelText('Your correction'));
  await user.type(screen.getByLabelText('Your correction'), '009');
  server.failNext('stale_version');
  await user.click(screen.getByRole('button', { name: 'Save 009' }));
  server.fetch.mockImplementationOnce(async () => {
    throw new TypeError('offline');
  });
  await user.click(screen.getByRole('button', { name: 'Reload current field' }));
  expect(screen.getByLabelText('Your correction')).toHaveValue('009');
  expect(screen.getByRole('button', { name: 'Reload current field' })).toBeEnabled();
});

it('allows further review after undo on the same field once its scan has loaded', async () => {
  backend();
  const user = await start();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await user.click(await screen.findByRole('button', { name: 'Undo' }));
  await screen.findByText(/Undo saved on this computer/);
  expect(screen.getByRole('button', { name: 'Accept 05' })).toBeDisabled();
  loaded();
  expect(screen.getByRole('button', { name: 'Accept 05' })).toBeEnabled();
});

it('loads only summaries before opening one dwelling and keeps clear fields read-only', async () => {
  const server = backend();
  const user = await start();
  expect(
    server.fetch.mock.calls.some(([path]) => String(path).startsWith('/api/queue')),
  ).toBe(false);
  expect(
    server.fetch.mock.calls.some(
      ([path]) => path === '/api/dwellings/dwelling1/items?region=216418',
    ),
  ).toBe(true);
  expect(screen.getByRole('button', { name: /Type of Family/ })).toBeDisabled();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  expect(server.mutations).toHaveLength(1);
  expect(screen.getByRole('button', { name: /Type of Family/ })).toBeDisabled();
});

it('shows special-code meanings while allowing an ordinary amount with exact zeros', async () => {
  backend();
  const user = await start();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Fix' }));
  await user.clear(screen.getByLabelText('Your correction'));
  await user.type(screen.getByLabelText('Your correction'), '00');
  expect(screen.getByText('Special codes for this field')).toBeVisible();
  expect(screen.getByText('Free', { selector: '.mean-live' })).toBeVisible();
  await user.clear(screen.getByLabelText('Your correction'));
  await user.type(screen.getByLabelText('Your correction'), '009');
  expect(screen.getByRole('button', { name: 'Save 009' })).toBeEnabled();
});

it('refreshes progress and reviewer attribution on return, and isolates Undo to its dwelling', async () => {
  backend([field(), field('other', { dwelling_id: 'dwelling2', record_id: null })]);
  const user = await startFirst();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await screen.findByRole('button', { name: 'Undo' });
  await user.click(screen.getByRole('button', { name: '← Queue' }));
  await screen.findByText('● Done');
  expect(within(screen.getByRole('table')).getByText('Jane Smith')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Review' }));
  await screen.findByRole('heading', { name: 'Weekly Rent' });
  expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
  expect(screen.getByRole('banner')).toHaveTextContent('Number not identified');
});
async function startFirst() {
  const user = userEvent.setup();
  render(<App />);
  await user.type(await screen.findByLabelText('Your name'), 'Jane Smith');
  await user.click(screen.getByRole('button', { name: 'Start reviewing' }));
  await screen.findByRole('table');
  await user.click(screen.getAllByRole('button', { name: 'Review' })[0]);
  await screen.findByRole('heading', { name: 'Weekly Rent' });
  return user;
}

it('shows each coding card and requires its loaded scan after switching households', async () => {
  backend([
    field(),
    field('rent2', {
      record_id: '03-0005-02',
      source: { pdf: 'original.pdf', page: 22, card_id: 'card2' },
      scan_url: '/api/scans/card2',
    }),
  ]);
  const user = await start();
  loaded();
  await user.selectOptions(screen.getByLabelText('Card to review'), 'card2');
  expect(screen.getByRole('img')).toHaveAttribute('src', '/api/scans/card2');
  expect(screen.getByRole('button', { name: 'Accept 05' })).toBeDisabled();
  loaded();
  expect(screen.getByRole('button', { name: 'Accept 05' })).toBeEnabled();
});

it('brings the selected field into view', async () => {
  const scroll = vi.fn();
  const previous = HTMLElement.prototype.scrollIntoView;
  HTMLElement.prototype.scrollIntoView = scroll;
  try {
    backend();
    await start();
    expect(scroll).toHaveBeenCalledWith({ block: 'nearest' });
  } finally {
    HTMLElement.prototype.scrollIntoView = previous;
  }
});

it('exports all summary rows with literal, escaped values and unknown scores left blank', () => {
  const row = {
    id: 'physical-a',
    region: '216418',
    record_id: null,
    address: '=1+2,"quoted"',
    card_count: 1,
    score: null,
    total: 2,
    resolved: 1,
    unresolved: 1,
    status: 'in_progress',
    first_item_id: 'rent',
    next_item_id: 'rent',
    last_reviewer: 'Jane Smith',
    last_reviewed_at: null,
    diagnostics: [],
  } as const;
  const csv = reviewSummaryCsv({
    dwellings: [row],
  } as unknown as DwellingQueue);
  expect(csv).toContain('"\'=1+2,""quoted"""');
  expect(csv).toContain('"216418","","\'=1+2,""quoted""","1","","2","1","1"');
  expect(csv).toContain('"Jane Smith"');
});

it('refreshes other decisions after a stale editor reload without losing the draft or reopening decided fields', async () => {
  const server = backend([field(), field('garden', { label: 'Garden' })]);
  const user = await start();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Fix' }));
  await user.clear(screen.getByLabelText('Your correction'));
  await user.type(screen.getByLabelText('Your correction'), '009');
  server.resolveField('garden');
  server.failNext('stale_version');
  await user.click(screen.getByRole('button', { name: 'Save 009' }));
  await user.click(screen.getByRole('button', { name: 'Reload current field' }));
  expect(screen.getByLabelText('Your correction')).toHaveValue('009');
  expect(screen.getByText('1 of 2 decided · in card order')).toBeVisible();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Save 009' }));
  await screen.findByText(/Saved: Weekly Rent 009/);
  expect(screen.getByRole('heading', { name: 'Weekly Rent' })).toBeVisible();
  expect(screen.queryByRole('heading', { name: 'Garden' })).not.toBeInTheDocument();
});

describe('PR 3 help, history and finish', () => {
  it('opens first-time help and keeps decisions disabled behind the dialog', async () => {
    backend();
    localStorage.removeItem('review-help-seen');
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByLabelText('Your name'), 'Jane Smith');
    await user.click(screen.getByRole('button', { name: 'Start reviewing' }));
    expect(await screen.findByRole('dialog')).toHaveAccessibleName(
      'Welcome, Jane Smith. Six things to know.',
    );
    expect(screen.getByRole('button', { name: 'Review' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Got it' }));
    expect(localStorage.getItem('review-help-seen')).toBe('true');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it('persists shortcut off and leaves both keyboard and mouse alternatives honest', async () => {
    const server = backend();
    const user = await start();
    loaded();
    await user.click(screen.getByRole('button', { name: 'Help' }));
    await user.click(screen.getByRole('button', { name: 'More help' }));
    await user.click(screen.getByRole('switch', { name: 'Single-letter shortcuts' }));
    await user.click(screen.getByRole('button', { name: 'Got it' }));
    fireEvent.keyDown(
      screen.getByRole('region', { name: 'Fields to review on this card' }),
      { key: 'a' },
    );
    expect(server.mutations).toHaveLength(0);
    fireEvent.keyDown(
      screen.getByRole('region', { name: 'Scan image, scroll to inspect' }),
      { key: 'm' },
    );
    expect(screen.getByRole('button', { name: 'Magnifier (M)' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    expect(localStorage.getItem('review-single-letter-shortcuts')).toBe('false');
    await user.click(screen.getByRole('button', { name: 'Fix' }));
    const save = screen.getByRole('button', { name: 'Save 05' });
    save.focus();
    fireEvent.keyDown(save, { key: 'Escape' });
    expect(screen.queryByLabelText('Your correction')).not.toBeInTheDocument();
  });
  it('shows exact audited original, reviewer and undo without deleting history', async () => {
    backend();
    const user = await start();
    loaded();
    await user.click(screen.getByRole('button', { name: 'Fix' }));
    await user.clear(screen.getByLabelText('Your correction'));
    await user.type(screen.getByLabelText('Your correction'), '009');
    await user.click(screen.getByRole('button', { name: 'Save 009' }));
    await user.click(screen.getByRole('button', { name: 'Show history' }));
    const history = screen.getByRole('region', {
      name: 'History of Weekly Rent',
    });
    expect(history).toHaveTextContent('Machine read: 05');
    expect(history).toHaveTextContent('Corrected: 05 → 009');
    expect(history).toHaveTextContent('by Jane Smith');
    expect(history.querySelector('time')).toHaveAttribute(
      'dateTime',
      '2026-10-14T07:00:00Z',
    );
    loaded();
    await user.click(
      screen.getByRole('button', {
        name: 'Undo latest decision on this field',
      }),
    );
    expect(
      await screen.findByRole('region', { name: 'History of Weekly Rent' }),
    ).toHaveTextContent('Undone: 009 → 05');
  });
  it('undo shortcut targets the saved field after advancing to a different field', async () => {
    const server = backend([field(), field('garden', { label: 'Garden' })]);
    const user = await start();
    loaded();
    await user.click(screen.getByRole('button', { name: 'Accept 05' }));
    await screen.findByRole('heading', { name: 'Garden' });
    expect(screen.getByRole('heading', { name: 'Garden' }).closest('article')).toHaveFocus();
    loaded();
    fireEvent.keyDown(
      screen.getByRole('region', { name: 'Fields to review on this card' }),
      { key: 'u' },
    );
    await screen.findByText(
      'Undo saved on this computer. The original decision stays in the history.',
    );
    expect(server.mutations.at(-1)?.path).toBe('/api/decisions/decision-rent/undo');
  });
  it('finish keeps local saves distinct from failed sharing and preserves working context', async () => {
    const server = backend();
    const user = await start();
    loaded();
    server.sharing({
      state: 'upload_failed',
      pending: true,
      error: { code: 'git_auth', message: 'Sign in to Git' },
    });
    await user.click(screen.getByRole('button', { name: 'Save and Exit' }));
    const dialog = await screen.findByRole('dialog', {
      name: "You're all saved",
    });
    expect(dialog).toHaveTextContent('Sharing has not been confirmed');
    expect(dialog).toHaveTextContent('page 21, Weekly Rent');
    expect(within(dialog).queryByText('Shared with the team.')).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Keep reviewing' }));
    expect(screen.getByRole('heading', { name: 'Weekly Rent' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Accept 05' })).toBeEnabled();
  });
  it('does not allow finish to discard an unsaved correction or uncertain request', async () => {
    const server = backend();
    const user = await start();
    loaded();
    await user.click(screen.getByRole('button', { name: 'Fix' }));
    await user.clear(screen.getByLabelText('Your correction'));
    await user.type(screen.getByLabelText('Your correction'), '009');
    expect(screen.getByRole('button', { name: 'Save and Exit' })).toBeDisabled();
    server.failNext('network');
    await user.click(screen.getByRole('button', { name: 'Save 009' }));
    expect(screen.getByRole('button', { name: 'Save and Exit' })).toBeDisabled();
    expect(screen.getByLabelText('Your correction')).toHaveValue('009');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

it('keeps decided fields visible and selectable in their completed printed column', async () => {
  backend([
    field('municipality', {
      label: 'Municipality',
      column: 'Left column',
      review_state: 'accepted',
      resolved: true,
    }),
    field('rent', { column: 'Middle column' }),
  ]);
  const user = await start('Continue');
  loaded();
  expect(screen.getByRole('heading', { name: 'Left column' })).toBeVisible();
  expect(screen.queryByRole('button', { name: /Left column.*Show/ })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Municipality.*05/ })).toBeVisible();
  await user.click(screen.getByRole('button', { name: /Municipality.*05/ }));
  expect(
    await screen.findByRole('region', { name: 'History of Municipality' }),
  ).toHaveTextContent('No review decisions recorded');
  expect(screen.getByRole('button', { name: 'Accept 05' })).toBeDisabled();
});
it('switches household scan and card score and waits for the new image', async () => {
  backend([
    field(),
    field('second', {
      label: 'Garden',
      card_score: 0.75,
      record_id: '03-0005-02',
      source: { pdf: 'original.pdf', page: 33, card_id: 'card2' },
      scan_url: '/api/scans/card2',
    }),
  ]);
  const user = await start();
  loaded();
  await user.selectOptions(screen.getByLabelText('Card to review'), 'card2');
  await screen.findByRole('heading', { name: 'Garden' });
  expect(screen.getByRole('img')).toHaveAttribute('src', '/api/scans/card2');
  expect(screen.getByRole('img')).toHaveAccessibleName(/page 33/);
  expect(screen.getByRole('banner')).toHaveTextContent('Medium 0.75');
  expect(screen.getByRole('button', { name: 'Accept 05' })).toBeDisabled();
  loaded();
  expect(screen.getByRole('button', { name: 'Accept 05' })).toBeEnabled();
});

it('requires fresh scan evidence when another reviewer signs in on the open field', async () => {
  backend();
  const user = await start();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Change' }));
  await user.clear(screen.getByLabelText('Your name'));
  await user.type(screen.getByLabelText('Your name'), 'Second Reviewer');
  await user.click(screen.getByRole('button', { name: 'Start reviewing' }));
  await screen.findByRole('heading', { name: 'Weekly Rent' });
  expect(screen.getByRole('heading', { name: 'Weekly Rent' }).closest('article')).toHaveFocus();
  expect(screen.getByRole('button', { name: 'Accept 05' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Fix' })).toBeDisabled();
  loaded();
  expect(screen.getByRole('button', { name: 'Accept 05' })).toBeEnabled();
});

it('clears a previous reviewer’s saved Undo button and shortcut on sign-in', async () => {
  const server = backend([field(), field('garden', { label: 'Garden' })]);
  const user = await start();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await screen.findByRole('heading', { name: 'Garden' });
  await user.click(screen.getByRole('button', { name: 'Change' }));
  await user.clear(screen.getByLabelText('Your name'));
  await user.type(screen.getByLabelText('Your name'), 'Second Reviewer');
  await user.click(screen.getByRole('button', { name: 'Start reviewing' }));
  await screen.findByRole('heading', { name: 'Garden' });
  expect(
    screen.queryByRole('button', { name: /^Undo$/ }),
  ).not.toBeInTheDocument();
  const panel = screen.getByRole('region', { name: 'Fields to review on this card' });
  fireEvent.keyDown(panel, { key: 'u' });
  loaded();
  fireEvent.keyDown(panel, { key: 'u' });
  expect(server.mutations).toHaveLength(1);
});

it.each([
  [401, 'session_required', 'Session expired'],
  [409, 'remote_ahead', 'Same region changed'],
])('handles a %s error during Save and Exit', async (status, code, message) => {
  const server = backend();
  const user = await start();
  loaded();
  vi.stubGlobal('fetch', async (input: string, options?: RequestInit) =>
    input === '/api/sync' && options?.method === 'POST'
      ? response({ error: { code, message } }, status)
      : server.fetch(input, options),
  );
  await user.click(screen.getByRole('button', { name: 'Save and Exit' }));
  if (status === 401) {
    expect(await screen.findByLabelText('Your name')).toBeVisible();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Accept 05' })).not.toBeInTheDocument();
  } else {
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('Ask the team to reconcile this region');
    await user.click(within(dialog).getByRole('button', { name: 'Keep reviewing' }));
    expect(screen.getByRole('button', { name: 'Accept 05' })).toBeDisabled();
  }
  expect(screen.getAllByText(message).length).toBeGreaterThan(0);
});

it('does not label a context-only printed column as decided or fold it', async () => {
  const rent = field();
  backend([
    field('rent', {
      column: 'Middle column',
      card_fields: [
        {
          id: rent.id,
          field_path: rent.field_path,
          label: rent.label,
          column: 'Middle column',
          field: rent.field,
          review_state: 'pending',
        },
        {
          id: null,
          field_path: '/context',
          label: 'Length of Residence',
          column: 'Right column',
          field: rent.field,
          review_state: 'pending',
        },
      ],
    }),
  ]);
  await start();
  expect(screen.getByRole('heading', { name: 'Right column' })).toBeVisible();
  expect(screen.getByRole('button', { name: /Length of Residence/ })).toBeDisabled();
  expect(
    screen.queryByRole('button', { name: /Right column.*decided/ }),
  ).not.toBeInTheDocument();
});

it('omits unqueued cards from the card selector while preserving the current field', async () => {
  const rent = field();
  backend([
    field('rent', {
      cards: [
        {
          card_id: rent.source.card_id,
          household_index: 0,
          household_no: '1',
          record_id: rent.record_id,
          first_item_id: rent.id,
          next_item_id: rent.id,
        },
        {
          card_id: 'optional-card',
          household_index: 1,
          household_no: '2',
          record_id: null,
          first_item_id: null,
          next_item_id: null,
        },
        {
          card_id: 'optional-card',
          household_index: 2,
          household_no: '3',
          record_id: null,
          first_item_id: null,
          next_item_id: null,
        },
      ],
    }),
  ]);
  await start();
  expect(screen.queryByRole('option', { name: /household 2/ })).not.toBeInTheDocument();
  expect(screen.queryByRole('option', { name: /household 3/ })).not.toBeInTheDocument();
  expect(screen.queryByText('Not queued')).not.toBeInTheDocument();
  expect(screen.getByRole('img')).toHaveAttribute('src', rent.scan_url);
});

it('Continue skips blocked dwellings but leaves their rows visible', async () => {
  backend([
    field('blocked', {
      label: 'Garden',
      dwelling_id: 'blocked',
      record_id: '03-0001-01',
      diagnostics: [{ code: 'missing_scan', message: 'Scan missing' }],
    }),
    field(),
  ]);
  const user = userEvent.setup();
  render(<App />);
  await user.type(await screen.findByLabelText('Your name'), 'Jane Smith');
  await user.click(screen.getByRole('button', { name: 'Start reviewing' }));
  const next = await screen.findByRole('button', { name: 'Continue 03-0005-01 →' });
  expect(screen.getByText('03-0001-01')).toBeVisible();
  await user.click(next);
  expect(await screen.findByRole('heading', { name: 'Weekly Rent' })).toBeVisible();
});

it('marks a newly discovered missing scan blocked so Continue can move on', async () => {
  const server = backend([
    field(),
    field('other', { label: 'Garden', dwelling_id: 'other', record_id: '03-0006-01' }),
  ]);
  vi.stubGlobal('fetch', async (input: string, options?: RequestInit) => {
    const result = await server.fetch(input, options);
    if (String(input).includes('/api/dwellings/dwelling1/items?')) {
      const data = await result.json();
      data.items = data.items.map((item: Item) => ({
        ...item,
        allowed_actions: [],
        diagnostics: [{ code: 'missing_scan', message: 'Scan missing' }],
      }));
      return response(data);
    }
    return result;
  });
  // Two Review row buttons: choose this dwelling through the Continue shortcut.
  const user = await start('Continue 03-0005-01 →');
  await user.click(screen.getByRole('button', { name: '← Queue' }));
  expect(
    await screen.findByRole('button', { name: 'Continue 03-0006-01 →' }),
  ).toBeVisible();
});


it('preserves multiline Unicode text through scan gating, uncertain retry and stale recovery', async () => {
  const text = field('note', {field_kind: 'text', label: 'Weekly Rent', code_list: [], field_path: '/dwelling/notes/0/text', field: {value: 'Machine note', status: 'ok', confidence: null}});
  const server = backend([text]);
  const user = await start();
  expect(screen.getByRole('button', {name: 'Fix'})).toBeDisabled();
  loaded();
  await user.click(screen.getByRole('button', {name: 'Fix'}));
  const input = screen.getByLabelText('Your correction');
  expect(input.tagName).toBe('TEXTAREA');
  fireEvent.change(input, {target: {value: '  Café — 王\nSecond line: 009\n'}});
  server.failNext('network');
  await user.click(screen.getByRole('button', {name: 'Save correction'}));
  expect(input).toHaveValue('  Café — 王\nSecond line: 009\n');
  await user.click(screen.getByRole('button', {name: 'Try again'}));
  expect(server.mutations).toHaveLength(2);
  expect(server.mutations[1].body).toEqual(server.mutations[0].body);
  expect(server.mutations[1].body.value).toBe('  Café — 王\nSecond line: 009\n');
});

it('retains text drafts after a confirmed stale version and disables decisions until the reloaded scan loads', async () => {
  const server = backend([field('note', {field_kind: 'text', code_list: [], field: {value: 'Machine note', status: 'ok', confidence: null}})]);
  const user = await start();
  loaded();
  await user.click(screen.getByRole('button', {name: 'Fix'}));
  fireEvent.change(screen.getByLabelText('Your correction'), {target: {value: 'Unicode 王\nNext line'}});
  server.failNext('stale_version');
  await user.click(screen.getByRole('button', {name: 'Save correction'}));
  expect(screen.getByLabelText('Your correction')).toHaveValue('Unicode 王\nNext line');
  await user.click(screen.getByRole('button', {name: 'Reload current field'}));
  expect(screen.getByLabelText('Your correction')).toHaveValue('Unicode 王\nNext line');
  expect(screen.getByRole('button', {name: 'Save correction'})).toBeDisabled();
  loaded();
  expect(screen.getByRole('button', {name: 'Save correction'})).toBeEnabled();
});

it('bounds text corrections and rejects NUL before sending a decision', async () => {
  const server = backend([field('note', {field_kind: 'text', code_list: [], field: {value: 'Machine note', status: 'ok', confidence: null}})]);
  const user = await start();
  loaded();
  await user.click(screen.getByRole('button', {name: 'Fix'}));
  const input = screen.getByLabelText('Your correction');
  expect(input).toHaveAttribute('maxlength', '10000');
  for (const value of ['x'.repeat(10001), 'text\0text']) {
    fireEvent.change(input, {target: {value}});
    expect(screen.getByRole('button', {name: 'Save correction'})).toBeDisabled();
  }
  fireEvent.change(input, {target: {value: '王'.repeat(10000)}});
  expect(screen.getByRole('button', {name: 'Save correction'})).toBeEnabled();
  expect(server.mutations).toHaveLength(0);
});

it('moves between fields without saving and waits for fresh scan evidence', async () => {
  const server = backend([field(), field('garden', { label: 'Garden' })]);
  const user = await start();
  expect(screen.getByRole('button', { name: 'Previous field' })).toBeDisabled();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Next field' }));
  await screen.findByRole('heading', { name: 'Garden' });
  expect(screen.getByRole('button', { name: 'Next field' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Accept 05' })).toBeDisabled();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Previous field' }));
  await screen.findByRole('heading', { name: 'Weekly Rent' });
  expect(server.mutations).toHaveLength(0);
});

it('reaccepts a reviewed field by refreshing and advancing without another decision', async () => {
  const server = backend([field(), field('garden', { label: 'Garden' })]);
  const user = await start();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await screen.findByRole('heading', { name: 'Garden' });
  await user.click(screen.getByRole('button', { name: 'Previous field' }));
  await screen.findByRole('heading', { name: 'Weekly Rent' });
  loaded();
  server.fetch.mockClear();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await screen.findByRole('heading', { name: 'Garden' });
  expect(server.fetch.mock.calls.map(([path]) => path)).toEqual([
    '/api/review-items/rent/decisions',
    '/api/review-items/rent',
    '/api/dwellings/dwelling1/items?region=216418',
    '/api/review-items/garden',
  ]);
  expect(server.items()[0].field.review?.history).toHaveLength(1);
  expect(server.mutations).toHaveLength(2);
  expect(screen.queryByRole('heading', { name: 'Card reviewed' })).not.toBeInTheDocument();
});

it('stays on a field changed between the reaccept item and queue refreshes and reloads its scan and draft', async () => {
  const server = backend([field(), field('garden', { label: 'Garden' })]);
  const user = await start();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await screen.findByRole('heading', { name: 'Garden' });
  await user.click(screen.getByRole('button', { name: 'Previous field' }));
  await screen.findByRole('heading', { name: 'Weekly Rent' });
  loaded();
  const accepted = server.items()[0];
  const latest: Item = {
    ...accepted,
    version: 'external-change',
    review_state: 'pending',
    resolved: false,
    field: { ...accepted.field, value: '009', review: { ...accepted.field.review!, state: 'pending' } },
  };
  let changed = false;
  const originalFetch = server.fetch.getMockImplementation()!;
  server.fetch.mockImplementation(async (input, options) => {
    const result = await originalFetch(input, options);
    if (!options?.body && input === '/api/dwellings/dwelling1/items?region=216418') {
      changed = true;
      const queue = await result.json();
      return response({ ...queue, items: [latest, queue.items[1]], resolved: 0 });
    }
    if (changed && !options?.body && input === '/api/review-items/rent')
      return response({ ...await result.json(), ...latest });
    return result;
  });
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await screen.findByText('This field changed. Check it against the scan before deciding.');
  expect(screen.getByRole('heading', { name: 'Weekly Rent' })).toBeVisible();
  expect(screen.queryByRole('heading', { name: 'Garden' })).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Card reviewed' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Accept 009' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Fix' })).toBeDisabled();
  loaded();
  expect(screen.getByRole('button', { name: 'Accept 009' })).toBeEnabled();
  await user.click(screen.getByRole('button', { name: 'Fix' }));
  expect(screen.getByLabelText('Your correction')).toHaveValue('009');
  expect(server.items()[0].field.review?.history).toHaveLength(1);
  expect(server.mutations).toHaveLength(2);
});

it('offers completion choices when the final accepted field is accepted again', async () => {
  const server = backend([field(), field('garden', { label: 'Garden' })]);
  const user = await start();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await screen.findByRole('heading', { name: 'Garden' });
  loaded();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await screen.findByRole('heading', { name: 'Card reviewed' });
  await user.click(screen.getByRole('button', { name: 'Stay here' }));
  await user.click(screen.getByRole('button', { name: 'Previous field' }));
  await screen.findByRole('heading', { name: 'Weekly Rent' });
  await user.click(screen.getByRole('button', { name: 'Next field' }));
  await screen.findByRole('heading', { name: 'Garden' });
  loaded();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await screen.findByRole('heading', { name: 'Card reviewed' });
  expect(screen.getByRole('button', { name: 'Stay here' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Back to queue' })).toBeEnabled();
  expect(server.items().map((item) => item.field.review?.history.length)).toEqual([1, 1]);
  expect(server.mutations).toHaveLength(3);
});

it.each([
  ['item', 'network'], ['item', 'stale'],
  ['queue', 'network'], ['queue', 'stale'],
])('keeps the reviewed field open if the %s refresh fails with %s after reaccepting', async (target, failure) => {
  const server = backend([field(), field('garden', { label: 'Garden' })]);
  const user = await start();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await screen.findByRole('heading', { name: 'Garden' });
  await user.click(screen.getByRole('button', { name: 'Previous field' }));
  await screen.findByRole('heading', { name: 'Weekly Rent' });
  loaded();
  const originalFetch = server.fetch.getMockImplementation()!;
  server.fetch.mockImplementation(async (input, options) => {
    if (!options?.body && input === (target === 'item'
      ? '/api/review-items/rent' : '/api/dwellings/dwelling1/items?region=216418')) {
      if (failure === 'network') throw new TypeError('Lost connection');
      return response({ error: { code: 'stale_version', message: 'Region changed; reload before saving' } }, 409);
    }
    return originalFetch(input, options);
  });
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await screen.findByRole('alert');
  expect(screen.getByRole('heading', { name: 'Weekly Rent' })).toBeVisible();
  expect(screen.queryByRole('heading', { name: 'Garden' })).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Card reviewed' })).not.toBeInTheDocument();
  expect(server.items()[0].field.review?.history).toHaveLength(1);
  expect(server.items()[1].resolved).toBe(false);
});

it('finishes a card explicitly, keeps completion after staying, and reopens it on undo', async () => {
  const server = backend([
    field(), field('garden', { label: 'Garden' }),
    field('second', { label: 'Other card', source: { pdf: 'original.pdf', page: 22, card_id: 'card2' }, scan_url: '/api/scans/card2' }),
  ]);
  const user = await start();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await screen.findByRole('heading', { name: 'Garden' });
  expect(screen.queryByRole('heading', { name: 'Card reviewed' })).not.toBeInTheDocument();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await screen.findByRole('heading', { name: 'Card reviewed' });
  expect(screen.getByRole('heading', { name: 'Garden' })).toBeVisible();
  expect(screen.getByRole('banner')).toHaveTextContent('High · reviewed');
  expect(screen.getByRole('button', { name: /Weekly Rent.*ACCEPTED/ })).toBeVisible();
  expect(screen.queryByRole('heading', { name: 'Other card' })).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Stay here' }));
  expect(screen.getByRole('heading', { name: 'Card reviewed' })).toBeVisible();
  await user.click(screen.getByRole('button', { name: /^Undo$/ }));
  await screen.findByText(/Undo saved on this computer/);
  expect(screen.getByRole('banner')).toHaveTextContent('Medium 0.91');
  expect(screen.queryByRole('heading', { name: 'Card reviewed' })).not.toBeInTheDocument();
  loaded();
  expect(screen.getByRole('button', { name: 'Accept 05' })).toBeEnabled();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await user.click(await screen.findByRole('button', { name: 'Next card' }));
  await screen.findByRole('heading', { name: 'Other card' });
  expect(server.mutations).toHaveLength(4);
});

it('offers the next dwelling after finishing its last card without navigating automatically', async () => {
  backend([field(), field('other', { dwelling_id: 'dwelling2', label: 'Other dwelling', record_id: '03-0006-01', source: { pdf: 'original.pdf', page: 22, card_id: 'card2' }, scan_url: '/api/scans/card2' })]);
  const user = await startFirst();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await screen.findByRole('heading', { name: 'Card reviewed' });
  expect(screen.getByRole('heading', { name: 'Weekly Rent' })).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Next card' }));
  expect(await screen.findByRole('heading', { name: 'Other dwelling' })).toBeVisible();
  expect(screen.getByRole('button', { name: 'Accept 05' })).toBeDisabled();
});

it('offers return to queue after the final card and preserves completion after staying', async () => {
  backend();
  const user = await start();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await screen.findByRole('heading', { name: 'Card reviewed' });
  expect(screen.queryByRole('button', { name: 'Next card' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Back to queue' })).toBeEnabled();
  await user.click(screen.getByRole('button', { name: 'Stay here' }));
  expect(screen.getByRole('heading', { name: 'Card reviewed' })).toBeVisible();
  await user.click(screen.getByRole('button', { name: '← Queue' }));
  expect(await screen.findByRole('table')).toBeVisible();
});

it('makes survey fronts directly discoverable and preserves multiline Unicode fixes', async () => {
  const cards: NonNullable<Item['cards']> = [
    { card_id: 'card1', household_index: 0, household_no: '1', record_id: '03-0005-01', first_item_id: 'rent', next_item_id: 'rent', role: 'coding-front' },
    { card_id: 'survey1', household_index: null, household_no: null, record_id: '03-0005-01', first_item_id: 'survey', next_item_id: 'survey', role: 'survey-front' },
  ];
  const server = backend([
    field('rent', { cards }),
    field('survey', { cards, label: 'Survey address', field_kind: 'text', code_list: [], field: { value: 'Machine address', status: 'ok', confidence: null }, source: { pdf: 'original.pdf', page: 20, card_id: 'survey1', role: 'survey-front' }, scan_url: '/api/scans/survey1' }),
  ]);
  const user = await start();
  const selector = screen.getByLabelText('Card to review');
  expect(within(selector).getByRole('group', { name: 'Survey and notes' })).toBeInTheDocument();
  expect(within(selector).getByRole('group', { name: 'Coding cards' })).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Open survey front' }));
  await screen.findByRole('heading', { name: 'Survey address' });
  expect(selector).toHaveValue('survey1');
  expect(screen.getByRole('img')).toHaveAttribute('src', '/api/scans/survey1');
  expect(screen.getByRole('button', { name: 'Fix' })).toBeDisabled();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Fix' }));
  fireEvent.change(screen.getByLabelText('Your correction'), { target: { value: 'Café 王\nSecond line' } });
  await user.click(screen.getByRole('button', { name: 'Save correction' }));
  expect(server.mutations[0].body.value).toBe('Café 王\nSecond line');
});

it('moves completed dwellings below pending work in the queue', async () => {
  backend([field(), field('other', { dwelling_id: 'dwelling2', record_id: '03-0006-01', label: 'Other dwelling' })]);
  const user = await startFirst();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  await screen.findByRole('heading', { name: 'Card reviewed' });
  await user.click(screen.getByRole('button', { name: '← Queue' }));
  const table = await screen.findByRole('table');
  const rows = within(table).getAllByRole('row');
  expect(rows[1]).toHaveTextContent('03-0006-01');
  expect(rows[2]).toHaveTextContent('03-0005-01');
  expect(rows[2]).toHaveTextContent('High · reviewed');
});

it('does not announce region completion while unsupported queue diagnostics remain', async () => {
  const server = backend();
  const originalFetch = server.fetch.getMockImplementation()!;
  server.fetch.mockImplementation(async (input, options) => {
    const result = await originalFetch(input, options);
    if (!String(input).startsWith('/api/dwellings?')) return result;
    const queue = await result.json();
    return response({ ...queue, total: queue.total + 1, unresolved: queue.unresolved + 1,
      diagnostics: [{ code: 'invalid_reference', message: 'Unsupported field on another scan', region: '216418', batch: 'missing.pdf', page: 99 }] });
  });
  const user = await start();
  loaded();
  await user.click(screen.getByRole('button', { name: 'Accept 05' }));
  expect(await screen.findByRole('heading', { name: 'Card reviewed' })).toBeVisible();
  expect(screen.queryByText('All queued cards in this region are reviewed.')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Back to queue' }));
  expect(await screen.findByText('Remaining fields need the team’s attention.')).toBeVisible();
  expect(screen.getByText('Unsupported field on another scan')).toBeVisible();
});

it('places reviewed survey fronts below pending coding cards and keeps direct access', async () => {
  const cards: NonNullable<Item['cards']> = [
    { card_id: 'survey1', household_index: null, household_no: null, record_id: null, first_item_id: 'survey', next_item_id: null, role: 'survey-front', reviewed: true },
    { card_id: 'card1', household_index: 0, household_no: '1', record_id: '03-0005-01', first_item_id: 'rent', next_item_id: 'rent', role: 'coding-front', reviewed: false },
  ];
  backend([
    field('rent', { cards }),
    field('survey', { cards, label: 'Survey address', resolved: true, review_state: 'accepted', source: { pdf: 'original.pdf', page: 20, card_id: 'survey1', role: 'survey-front' }, scan_url: '/api/scans/survey1' }),
  ]);
  const user = await start('Continue');
  const selector = screen.getByLabelText('Card to review');
  expect(within(selector).getAllByRole('option').map((option) => (option as HTMLOptionElement).value)).toEqual(['card1', 'survey1']);
  expect(within(within(selector).getByRole('group', { name: 'Reviewed cards' })).getByRole('option', { name: /Survey front.*Reviewed/ })).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Open survey front' }));
  expect(await screen.findByRole('heading', { name: 'Survey address' })).toBeVisible();
  expect(screen.getByRole('heading', { name: 'Card reviewed' })).toBeVisible();
});

it('keeps queue details collapsed while region and review remain easy to reach', async () => {
  const server = backend();
  const originalFetch = server.fetch.getMockImplementation()!;
  server.fetch.mockImplementation(async (input, options) => {
    if (String(input).startsWith('/api/scan-batches?')) return response({
      region: '216418', pdf: 'original.pdf', size: 4, downloaded: 4,
      state: 'ready', local_ready: true, local_file_exists: true,
      automatic_download: true, active_region: null, drive_url: '', error: null,
    });
    return originalFetch(input, options);
  });
  const user = await start();
  await user.click(screen.getByRole('button', { name: '← Queue' }));
  const summary = screen.getByText('Review details and scans');
  const details = summary.closest('details')!;
  expect(details).not.toHaveAttribute('open');
  expect(screen.getByLabelText('Region')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Review' })).toBeVisible();
  expect(screen.getByRole('button', { name: 'Save and Exit' })).toBeVisible();
  expect(within(details).getByText(/All regions/)).not.toBeVisible();
  expect(within(details).getByText(/Machine average/)).not.toBeVisible();
  expect(screen.getByRole('button', { name: 'Review summary (.csv)' })).toBeVisible();
  expect(screen.getByRole('button', { name: 'Refresh queue' })).toBeVisible();
  await user.click(summary);
  expect(details).toHaveAttribute('open');
  expect(within(details).getByText(/All regions/)).toBeVisible();
  expect(within(details).getByText(/Machine average/)).toBeVisible();
  expect(within(details).getByRole('progressbar', { name: 'Region progress' })).toBeVisible();
  expect(screen.getByRole('button', { name: 'Review summary (.csv)' })).toBeVisible();
  expect(within(details).getByRole('region', { name: 'Scans for this region' })).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Refresh queue' }));
  expect(details).toHaveAttribute('open');
  await user.click(summary);
  expect(details).not.toHaveAttribute('open');
});

it.each(['accept', 'correct'] as const)('keeps %s saving feedback in the action area and prevents duplicate decisions', async (action) => {
  const server = backend([field(), field('garden', { label: 'Garden' })]);
  const originalFetch = server.fetch.getMockImplementation()!;
  let release!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  server.fetch.mockImplementation(async (input, options) => {
    if (String(input).endsWith('/decisions')) await held;
    return originalFetch(input, options);
  });
  const user = await start();
  loaded();
  if (action === 'correct') {
    await user.click(screen.getByRole('button', { name: 'Fix' }));
    await user.clear(screen.getByLabelText('Your correction'));
    await user.type(screen.getByLabelText('Your correction'), '009');
  }
  const actionButton = screen.getByRole('button', { name: action === 'accept' ? 'Accept 05' : 'Save 009' });
  const actions = actionButton.closest<HTMLElement>('.acts')!;
  await user.click(actionButton);
  const saving = await screen.findByText('Saving…');
  expect(saving).toHaveAttribute('role', 'status');
  expect(actions).toContainElement(saving);
  expect(actionButton).toBeDisabled();
  expect(within(actions).getByRole('button', { name: action === 'accept' ? 'Fix' : 'Cancel' })).toBeDisabled();
  expect(screen.queryByText('Saving on this computer…')).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Weekly Rent' })).toBeVisible();
  release();
  await screen.findByRole('heading', { name: 'Garden' });
  expect(screen.queryByText('Saving…')).not.toBeInTheDocument();
  expect(server.mutations).toHaveLength(1);
  expect(screen.getByRole('button', { name: 'Undo' }).closest('.review-feedback')).not.toBeNull();
  await user.click(screen.getByRole('button', { name: 'Dismiss saved confirmation' }));
  expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
  loaded();
  fireEvent.keyDown(screen.getByRole('region', { name: 'Fields to review on this card' }), { key: 'u' });
  await screen.findByText(/Undo saved on this computer/);
  expect(server.mutations).toHaveLength(2);
  expect(server.mutations[1].path).toContain('/undo');
});

describe('identity corrections', () => {
  it('preserves leading zeros and a lettered coding dwelling number', async () => {
    const server = backend([field('number', {
      label: 'Dwelling number', field_kind: 'numeric', identity_kind: 'dwelling',
      field_path: '/dwelling/number', code_list: [], allowed_actions: ['accept', 'correct'],
    })]);
    const user = await start('Review', 'Dwelling number');
    loaded();
    await user.click(screen.getByRole('button', { name: 'Fix' }));
    const input = screen.getByLabelText('Your correction');
    await user.clear(input);
    await user.type(input, '0006b');
    expect(input).toHaveValue('0006b');
    await user.click(screen.getByRole('button', { name: 'Save 0006b' }));
    await screen.findByText(/Saved: Dwelling number 0006b/);
    expect(server.mutations[0].body).toMatchObject({ action: 'correct', value: '0006b' });
    expect(screen.queryByRole('button', { name: "Can't read it or blank?" })).not.toBeInTheDocument();
  });

  it.each([
    ['municipality', 'Municipality', '00', ['001', ' 1', '1 ', '1a', '１']],
    ['household', 'Household number', '01', ['001', ' 1', '1 ', '1b', '١']],
    ['dwelling', 'Dwelling number', '0001A', ['00001', '00001A', '1AB', ' 1', '1 ', '1é']],
  ] as const)('validates %s identity without trimming or silently normalizing it', async (kind, label, valid, invalid) => {
    const server = backend([field('identity', {
      label, identity_kind: kind, field_kind: 'numeric', field_path: '/dwelling/number',
      code_list: [], allowed_actions: ['accept', 'correct'],
    })]);
    const user = await start('Review', label);
    loaded();
    expect(screen.getByRole('button', { name: 'Fix' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: 'Fix' }));
    const input = screen.getByLabelText('Your correction');
    for (const value of invalid) {
      fireEvent.change(input, { target: { value } });
      expect(input).toHaveValue(value);
      expect(within(input.closest('form')!).getByRole('button', { name: /^Save / })).toBeDisabled();
    }
    expect(server.mutations).toEqual([]);
    fireEvent.change(input, { target: { value: valid } });
    expect(screen.getByRole('button', { name: `Save ${valid}` })).toBeEnabled();
  });

  it('keeps historical extraction flags in collapsed source notes without an active warning', async () => {
    backend([field('rent', { dwelling_flags: ['identity_reread'], review_issues: [] })]);
    const user = await start();
    loaded();
    const summary = screen.getByText(/^Source notes/);
    const details = summary.closest('details')!;
    expect(details).not.toHaveAttribute('open');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    await user.click(summary);
    expect(details).toHaveAttribute('open');
    expect(details).toHaveTextContent('The identity block was read a second time.');
    expect(screen.queryByText(/needs team attention/i)).not.toBeInTheDocument();
  });

  it('refreshes active identity issues from the saved response while retaining source notes', async () => {
    const server = backend([field('rent', {
      identity_kind: 'dwelling', field_kind: 'numeric', dwelling_flags: ['identity_reread'],
      review_issues: [{ code: 'identity_conflict', message: 'Check the dwelling number against the scan.' }],
    })]);
    const realFetch = server.fetch.getMockImplementation()!;
    server.fetch.mockImplementation(async (input, options) => {
      const result = await realFetch(input, options);
      if (!String(input).endsWith('/decisions')) return result;
      const saved = await result.json() as Saved;
      return response({ ...saved, item: { ...saved.item, review_issues: [] } });
    });
    const user = await start();
    loaded();
    expect(screen.getByText('Check the dwelling number against the scan.')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Fix' }));
    await user.clear(screen.getByLabelText('Your correction'));
    await user.type(screen.getByLabelText('Your correction'), '0006A');
    await user.click(screen.getByRole('button', { name: 'Save 0006A' }));
    await screen.findByText(/Saved: Weekly Rent 0006A/);
    expect(screen.queryByText('Check the dwelling number against the scan.')).not.toBeInTheDocument();
    expect(screen.getByText(/^Source notes/)).toBeVisible();
  });
});

it('keeps a negated identity accept-only when the backend restricts its actions', async () => {
  backend([field('identity', {
    label: 'Municipality', identity_kind: 'municipality', field_kind: 'numeric',
    allowed_actions: ['accept'], code_list: [],
    field: { value: '27', status: 'ok', confidence: null, negated: true },
    warnings: ['A crossed-out identity requires a separate resolution.'],
  })]);
  await start('Review', 'Municipality');
  loaded();
  expect(screen.getByRole('button', { name: 'Fix' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Accept 27' })).toBeEnabled();
  expect(screen.queryByRole('button', { name: "Can't read it or blank?" })).not.toBeInTheDocument();
});

it('validates the survey front dwelling number like the coding card', async () => {
  const server = backend([field('handwritten', {
    label: 'Number of Dwelling', field_kind: 'text', identity_kind: null,
    field_path: '/dwelling/handwritten/dwelling_no', code_list: [],
    source: { pdf: 'original.pdf', page: 21, card_id: 'survey1', role: 'survey-front' },
  })]);
  const user = await start('Review', 'Number of Dwelling');
  loaded();
  await user.click(screen.getByRole('button', { name: 'Fix' }));
  expect(screen.getByText(/Enter 1–4 digits, optionally followed by a letter/)).toBeVisible();
  await user.clear(screen.getByLabelText('Your correction'));
  await user.type(screen.getByLabelText('Your correction'), '12 see back');
  expect(screen.getByRole('button', { name: /^Save correction$/ })).toBeDisabled();
  await user.clear(screen.getByLabelText('Your correction'));
  await user.type(screen.getByLabelText('Your correction'), '0006b');
  await user.click(screen.getByRole('button', { name: /^Save correction$/ }));
  await screen.findByText(/Saved: Number of Dwelling 0006b/);
  expect(server.mutations[0].body).toMatchObject({ action: 'correct', value: '0006b' });
});

describe('prepared per-card review', () => {
  function prepared(overrides: Partial<Item> = {}) {
    return field('identity', {
      label: 'Dwelling number', identity_kind: 'dwelling', prepared_review: true, assigned: true,
      field_path: '/dwelling/households/0/dwelling_no', allowed_actions: ['accept', 'correct'],
      source: { pdf: 'original.pdf', page: 21, card_id: 'card1', role: 'coding-front' },
      duplicate_peers: [], ...overrides,
    });
  }

  it('confirms duplicates before committing and retains Compare after advancing', async () => {
    const server = backend([prepared(), field('rent', { prepared_review: true,
      source: { pdf: 'original.pdf', page: 21, card_id: 'card1', role: 'coding-front' } })]);
    const real = server.fetch.getMockImplementation()!;
    server.fetch.mockImplementation(async (input, options) => {
      if (String(input).endsWith('/preview')) return response({ version: 'v1', duplicate_confirmation: 'c'.repeat(64),
        duplicate: { identity: '03-0007-01', card_ids: ['card1', 'peer'] }, membership: { outcome: 'ambiguous' } });
      const result = await real(input, options);
      if (!String(input).endsWith('/decisions')) return result;
      const saved = await result.json() as Saved;
      return response({ ...saved, item: { ...saved.item, duplicate_peers: [{ card_id: 'peer', page: 54, pdf: 'original.pdf',
        identity: '03-0007-01', address: 'Other address', scan_url: '/api/scans/peer' }] } });
    });
    const user = await start('Review', 'Dwelling number');
    loaded();
    await user.click(screen.getByRole('button', { name: 'Fix' }));
    await user.clear(screen.getByLabelText('Your correction'));
    await user.type(screen.getByLabelText('Your correction'), '7');
    await user.click(screen.getByRole('button', { name: 'Save 7' }));
    const dialog = await screen.findByRole('dialog', { name: 'Confirm duplicate identity' });
    expect(server.mutations).toHaveLength(0);
    await user.click(within(dialog).getByRole('button', { name: 'Go back' }));
    expect(screen.getByLabelText('Your correction')).toHaveValue('7');
    await user.click(screen.getByRole('button', { name: 'Save 7' }));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Save anyway' }));
    await screen.findByRole('heading', { name: 'Weekly Rent' });
    expect(screen.getByText(/Duplicate identity on coding page 21/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Compare' })).toBeVisible();
    expect(server.mutations).toHaveLength(1);
    expect(server.mutations[0].body.duplicate_confirmation).toBe('c'.repeat(64));
  });

  it('requires explicit retention before saving a last-card link', async () => {
    const server = backend([prepared()]);
    const real = server.fetch.getMockImplementation()!;
    server.fetch.mockImplementation(async (input, options) => {
      if (String(input).endsWith('/link-candidates')) return response({ version: 'v1', outcome: 'supplementary_pending', requires_retention: true,
        candidates: [{ card_id: 'target', current: false, clear: true, coding_pages: [334], front_pages: [332], address: 'Destination address', reason: 'Compatible readings' }] });
      if (String(input).endsWith('/link')) {
        const body = JSON.parse(String(options?.body));
        server.mutations.push({ path: String(input), body });
        return response({ saved_locally: true, item: prepared({ retained_bundle_count: 1 }),
          decision: { id: 'link-operation', action: 'link', reviewer: 'Jane Smith', timestamp: '2026-10-29T00:00:00Z' }, sync: shared, structural_change: true });
      }
      return real(input, options);
    });
    const user = await start('Review', 'Dwelling number');
    await user.click(screen.getByRole('button', { name: 'Link to dwelling' }));
    const dialog = await screen.findByRole('dialog', { name: 'Link coding card to dwelling' });
    await user.click(within(dialog).getByLabelText(/Destination address/));
    expect(within(dialog).getByRole('button', { name: 'Save link' })).toBeDisabled();
    await user.click(within(dialog).getByRole('checkbox'));
    await user.click(within(dialog).getByRole('button', { name: 'Save link' }));
    await screen.findByRole('button', { name: 'Retained evidence (1)' });
    expect(server.mutations[0].body).toMatchObject({ target_card_id: 'target', retain_supplements: true });
  });

  it('keeps the link form open with its choice when the server refuses it', async () => {
    const server = backend([prepared()]);
    const real = server.fetch.getMockImplementation()!;
    server.fetch.mockImplementation(async (input, options) => {
      if (String(input).endsWith('/link-candidates')) return response({ version: 'v1', outcome: 'manual', requires_retention: false,
        candidates: [{ card_id: 'target', current: false, clear: true, coding_pages: [334], front_pages: [332], address: 'Destination address', reason: 'Compatible readings' }] });
      if (String(input).endsWith('/link')) {
        server.mutations.push({ path: String(input), body: JSON.parse(String(options?.body)) });
        return response({ error: { code: 'invalid_destination', message: 'Choose a current compatible destination in this region and PDF' } }, 422);
      }
      return real(input, options);
    });
    const user = await start('Review', 'Dwelling number');
    await user.click(screen.getByRole('button', { name: 'Link to dwelling' }));
    const dialog = await screen.findByRole('dialog', { name: 'Link coding card to dwelling' });
    await user.click(within(dialog).getByLabelText(/Destination address/));
    await user.click(within(dialog).getByRole('button', { name: 'Save link' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Choose a current compatible destination');
    expect(screen.getAllByText(/Choose a current compatible destination/)).toHaveLength(1);
    expect(within(dialog).getByLabelText(/Destination address/)).toBeChecked();
    expect(within(dialog).getByRole('button', { name: 'Save link' })).toBeEnabled();
    expect(server.mutations).toHaveLength(1);
  });

  it('shows why the server refused an Undo of the last link', async () => {
    const server = backend([prepared({ undo_link_id: 'link-operation' })]);
    const real = server.fetch.getMockImplementation()!;
    server.fetch.mockImplementation(async (input, options) => {
      if (String(input).endsWith('/api/cards/card1')) return response({ version: 'v2' });
      if (String(input).endsWith('/undo')) {
        server.mutations.push({ path: String(input), body: JSON.parse(String(options?.body)) });
        return response({ error: { code: 'missing_remote', message: 'The data checkout has no remote' } }, 422);
      }
      return real(input, options);
    });
    const user = await start('Review', 'Dwelling number');
    await user.click(screen.getByRole('button', { name: 'Undo last link' }));
    expect(await screen.findByText('The data checkout has no remote')).toBeVisible();
    expect(server.mutations).toHaveLength(1);
  });
});

describe('high-confidence context disclosure', () => {
  const title = 'High-confidence fields not queued for review';
  type Row = NonNullable<Item['card_fields']>[number];
  const context = (label: string, confidence: number | null, overrides: Partial<Row> = {}): Row => ({
    id: null, field_path: '/context/' + label, label, column: 'Right column',
    field: { value: '00', status: 'ok', confidence }, review_state: 'pending', ...overrides,
  });
  const queued = (item: Item): Row => ({
    id: item.id, field_path: item.field_path, label: item.label, column: 'Middle column',
    field: item.field, review_state: item.review_state,
  });

  it('collapses only unqueued, readable, pending context at the 0.98 threshold', async () => {
    const rent = field();
    backend([field('rent', { card_fields: [
      queued(rent), context('Below threshold', 0.979), context('Threshold context', 0.98),
      context('Certain context', 1), context('Unscored context', null),
      context('Unreadable context', 0.99, { field: { value: null, status: 'illegible', confidence: 0.99 } }),
      context('Blank context', 0.99, { field: { value: null, status: 'no_data', confidence: 0.99 } }),
      context('Accepted context', 0.99, { review_state: 'accepted' }),
      context('Corrected context', 0.99, { review_state: 'corrected' }),
    ] })]);
    const user = await start();
    const summary = screen.getByText(`${title} (2)`);
    const details = summary.closest('details')!;
    expect(details).not.toHaveAttribute('open');
    for (const label of ['Below threshold', 'Unscored context', 'Unreadable context', 'Blank context', 'Accepted context', 'Corrected context']) {
      expect(screen.getByRole('button', { name: new RegExp(label) })).toBeVisible();
    }
    await user.click(summary);
    expect(details).toHaveAttribute('open');
    expect(within(details).getByRole('heading', { name: 'Right column' })).toBeVisible();
    for (const label of ['Threshold context', 'Certain context']) {
      const row = within(details).getByText(label).closest('.r')!;
      expect(row).toBeVisible();
      expect(row).toHaveTextContent('00');
      expect(row).toHaveTextContent('NOT QUEUED');
      expect(row.tagName).toBe('DIV');
      expect(within(row as HTMLElement).queryByRole('button')).not.toBeInTheDocument();
    }
    await user.click(summary);
    expect(details).not.toHaveAttribute('open');
  });

  it('keeps queued 0.98 fields in navigation and completion while context remains unqueued', async () => {
    const rent = field('rent', { field: { value: '05', status: 'ok', confidence: 0.98 } });
    const garden = field('garden', { label: 'Garden', field: { value: '00', status: 'ok', confidence: 1 } });
    const card_fields = [queued(rent), queued(garden), context('Certain context', 0.99)];
    const server = backend([{ ...rent, card_fields }, { ...garden, card_fields }]);
    const user = await start();
    expect(screen.getByRole('heading', { name: 'Weekly Rent' })).toBeVisible();
    expect(screen.getByRole('button', { name: /Garden/ })).toBeVisible();
    expect(screen.getByText(`${title} (1)`).closest('details')).not.toHaveAttribute('open');
    loaded();
    await user.click(screen.getByRole('button', { name: 'Accept 05' }));
    await screen.findByRole('heading', { name: 'Garden' });
    expect(screen.queryByRole('heading', { name: 'Card reviewed' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next field' })).toBeDisabled();
    loaded();
    await user.click(screen.getByRole('button', { name: 'Accept 00' }));
    expect(await screen.findByRole('heading', { name: 'Card reviewed' })).toBeVisible();
    expect(server.mutations).toHaveLength(2);
    expect(server.mutations[0].path).toContain('/rent/');
    expect(server.mutations[1].path).toContain('/garden/');
  });

  it('omits an empty disclosure when context is low confidence or every high-confidence row is queued', async () => {
    const rent = field('rent', { field: { value: '05', status: 'ok', confidence: 0.99 } });
    backend([{ ...rent, card_fields: [queued(rent), context('Visible context', 0.97)] }]);
    await start();
    expect(screen.queryByText(new RegExp(title))).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Visible context/ })).toBeVisible();
  });

  it('keeps expansion on same-card navigation and closes it when switching physical cards', async () => {
    const rent = field();
    const garden = field('garden', { label: 'Garden' });
    const other = field('other', {
      label: 'Other card', source: { pdf: 'original.pdf', page: 22, card_id: 'card2' }, scan_url: '/api/scans/card2',
    });
    const card_fields = [queued(rent), queued(garden), context('First card context', 0.98)];
    const server = backend([
      { ...rent, card_fields }, { ...garden, card_fields },
      { ...other, card_fields: [queued(other), context('Second card context', 0.99)] },
    ]);
    const user = await start();
    await user.click(screen.getByText(`${title} (1)`));
    expect(screen.getByText(`${title} (1)`).closest('details')).toHaveAttribute('open');
    await user.click(screen.getByRole('button', { name: 'Next field' }));
    await screen.findByRole('heading', { name: 'Garden' });
    expect(screen.getByText(`${title} (1)`).closest('details')).toHaveAttribute('open');
    await user.selectOptions(screen.getByLabelText('Card to review'), 'card2');
    await screen.findByRole('heading', { name: 'Other card' });
    expect(screen.getByText(`${title} (1)`).closest('details')).not.toHaveAttribute('open');
    await user.selectOptions(screen.getByLabelText('Card to review'), 'card1');
    await screen.findByRole('heading', { name: 'Garden' });
    expect(screen.getByText(`${title} (1)`).closest('details')).not.toHaveAttribute('open');
    expect(server.mutations).toHaveLength(0);
  });
});
