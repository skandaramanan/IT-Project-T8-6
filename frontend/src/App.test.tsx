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
async function start(action = 'Review') {
  const user = userEvent.setup();
  render(<App />);
  await user.type(await screen.findByLabelText('Your name'), 'Jane Smith');
  await user.click(screen.getByRole('button', { name: 'Start reviewing' }));
  await user.click(await screen.findByRole('button', { name: action }));
  await screen.findByRole('heading', { name: 'Weekly Rent' });
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
    expect(screen.getByRole('button', { name: 'Correct' })).toBeDisabled();
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
    await user.click(screen.getByRole('button', { name: 'Correct' }));
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
    await user.click(screen.getByRole('button', { name: 'Correct' }));
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
    await user.click(screen.getByRole('button', { name: 'Correct' }));
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
    expect(screen.getByRole('button', { name: 'Correct' })).toBeDisabled();
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
  await user.click(screen.getByRole('button', { name: 'Correct' }));
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
  await user.click(screen.getByRole('button', { name: 'Correct' }));
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
  await user.click(screen.getByRole('button', { name: /Coding card · household 2/ }));
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
  await user.click(screen.getByRole('button', { name: 'Correct' }));
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
    await user.click(screen.getByRole('button', { name: 'Correct' }));
    const save = screen.getByRole('button', { name: 'Save 05' });
    save.focus();
    fireEvent.keyDown(save, { key: 'Escape' });
    expect(screen.queryByLabelText('Your correction')).not.toBeInTheDocument();
  });
  it('shows exact audited original, reviewer and undo without deleting history', async () => {
    backend();
    const user = await start();
    loaded();
    await user.click(screen.getByRole('button', { name: 'Correct' }));
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
    await user.click(screen.getByRole('button', { name: 'Correct' }));
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

it('keeps decided fields selectable after folding their completed printed column', async () => {
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
  const column = screen.getByRole('button', { name: /Left column.*Show/ });
  expect(column).toHaveAttribute('aria-expanded', 'false');
  expect(
    screen.queryByRole('button', { name: /Municipality.*05/ }),
  ).not.toBeInTheDocument();
  await user.click(column);
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
  await user.click(screen.getByRole('button', { name: /Coding card · household 2/ }));
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
  expect(screen.getByRole('button', { name: 'Correct' })).toBeDisabled();
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

it('keeps unqueued card tabs disabled without changing the current field', async () => {
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
  const user = await start();
  const tab = screen.getByRole('button', { name: /Coding card · household 2/ });
  expect(tab).toBeDisabled();
  expect(tab).toHaveTextContent('Not queued');
  expect(
    screen.getByRole('button', { name: /Coding card · household 3/ }),
  ).toBeDisabled();
  await user.click(tab);
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
  expect(screen.getByRole('button', {name: 'Correct'})).toBeDisabled();
  loaded();
  await user.click(screen.getByRole('button', {name: 'Correct'}));
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
  await user.click(screen.getByRole('button', {name: 'Correct'}));
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
  await user.click(screen.getByRole('button', {name: 'Correct'}));
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
