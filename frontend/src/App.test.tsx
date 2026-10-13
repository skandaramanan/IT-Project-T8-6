// Decisions must wait for evidence, preserve exact input, and recover safely.
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import App from './App';
import { dwellingKey, groupDwellings } from './api';
import type { Item, Saved, Sync } from './api';

const shared: Sync = { state: 'uploaded', pending: false };
function field(id = 'rent', overrides: Partial<Item> = {}): Item {
  return {
    id,
    region: '216418',
    batch: 'original.pdf',
    record_id: '03-0005-01',
    field_path: '/dwelling/households/0/coding/weekly_rent',
    label: 'Weekly Rent',
    field: { value: '05', code: null, label: null, status: 'ok', confidence: 0.91 },
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
    if (path.startsWith('/api/queue')) {
      const selected =
        new URLSearchParams(path.split('?')[1]).get('region') === '216418' ? current : [];
      return response({
        items: selected,
        diagnostics: [],
        total: selected.length,
        resolved: selected.filter((i) => i.resolved).length,
        unresolved: selected.filter((i) => !i.resolved).length,
        complete: false,
      });
    }
    if (path === '/api/sync/status' || path === '/api/sync') return response(sharing);
    if (!options?.body) return response(current.find((i) => path.endsWith('/' + i.id)));
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
      field: { ...previous.field, value, status },
      review_state: undo ? 'pending' : body.action === 'accept' ? 'accepted' : 'corrected',
      resolved: !undo,
      undo_decision_id: undo ? null : `decision-${previous.id}`,
    };
    current = current.map((i) =>
      i.id === updated.id ? updated : { ...i, version: updated.version },
    );
    const saved: Saved = {
      saved_locally: true,
      item: updated,
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
    failNext: (code: string) => {
      fail = code;
    },
    sharing: (state: Sync) => {
      sharing = state;
    },
  };
}
async function start() {
  const user = userEvent.setup();
  render(<App />);
  await user.type(await screen.findByLabelText('Your name'), 'Jane Smith');
  await user.click(screen.getByRole('button', { name: 'Start reviewing' }));
  await user.click(await screen.findByRole('button', { name: 'Review' }));
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
    expect(screen.getByText('Medium 0.91')).toBeVisible();
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
    expect(screen.getByRole('button', { name: 'Save (fix the digits first)' })).toBeDisabled();
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
    expect(server.mutations[0].body.request_id).not.toBe(server.mutations[1].body.request_id);
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
    expect(server.fetch.mock.calls.some(([url]) => url === '/api/queue?region=216461')).toBe(true);
    expect(server.fetch.mock.calls.some(([url]) => url === '/api/queue')).toBe(false);
  });
});

it('groups households without re-ranking the supplied queue', () => {
  const a = field('a', { record_id: '03-0010-02' });
  const b = field('b', { record_id: '03-0001-01' });
  const c = field('c', { record_id: '03-0010-01' });
  const other = field('other', { region: '216420', record_id: '03-0010-01' });
  expect(groupDwellings([a, b, c, other])).toEqual([[a, c], [b], [other]]);
  expect(dwellingKey(a)).not.toBe(dwellingKey(other));
});

it('renders a bounded number of dwelling rows, with the rest reachable by paging', async () => {
  backend(
    Array.from({ length: 25 }, (_, n) =>
      field(`id${n}`, { record_id: `03-${String(n).padStart(4, '0')}-01` }),
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
  expect(screen.getByText('03-0024')).toBeVisible();
  expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(2);
});

it('keeps startup loading visible while health is unavailable', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => new Promise(() => {})),
  );
  render(<App />);
  expect(screen.getByRole('heading', { name: 'Loading the review tool…' })).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Start reviewing' })).not.toBeInTheDocument();
});

it('reports startup diagnostics without exposing review actions', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      response({ ready: false, diagnostics: [{ message: 'Configure an existing scan root' }] }),
    ),
  );
  render(<App />);
  await screen.findByRole('heading', { name: 'The review tool could not open' });
  expect(screen.getByText('Configure an existing scan root')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Start reviewing' })).not.toBeInTheDocument();
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
