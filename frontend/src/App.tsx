// A bounded review slice over IT-113: saves are confirmed before advancing.
import { useEffect, useRef, useState } from 'react';
import ScanViewer from './ScanViewer';
import Dialog from './Dialog';
import Help, { readPreference, savePreference, SHORTCUTS_KEY, HELP_KEY } from './Help';
import History from './History';
import { api, ApiError, dwellingKey, reviewSummaryCsv } from './api';
import type {
  Action,
  Dwelling,
  DwellingQueue,
  Item,
  Queue,
  Region,
  Saved,
  Sync,
} from './api';

const statuses = {
  ok: 'Readable',
  no_data: 'Blank',
  illegible: "Can't read it",
  damaged: 'Damaged or covered',
  omitted: 'Not read',
};
const stopCodes = new Set([
  'remote_ahead',
  'diverged',
  'external_change',
  'git_conflict',
  'wrong_branch',
  'unexpected_changes',
  'unexpected_commit',
  'invalid_history',
]);
const PAGE_SIZE = 12;

function Confidence({ score }: { score: number | null }) {
  const band = score === null ? 'none' : score >= 0.97 ? 'high' : score < 0.6 ? 'low' : 'med';
  const label = { none: 'Not scored', high: 'High', low: 'Low', med: 'Medium' }[band];
  return (
    <span className={`badge ${band}`}>
      <span aria-hidden="true">
        {band === 'none' ? '◌' : band === 'high' ? '✓' : band === 'low' ? '△' : '◐'}
      </span>
      {label}
      {score === null ? '' : ` ${score.toFixed(2)}`}
    </span>
  );
}
function Value({ item }: { item: Item }) {
  return <>{item.field.value ?? statuses[item.field.status]}</>;
}
interface Pending {
  path: string;
  body: object;
}

export default function App() {
  const [ready, setReady] = useState(false);
  const [startupError, setStartupError] = useState('');
  const [regions, setRegions] = useState<Region[]>([]);
  const [name, setName] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [region, setRegion] = useState('');
  const [queue, setQueue] = useState<DwellingQueue | null>(null);
  const [dwellingItems, setDwellingItems] = useState<Queue | null>(null);
  const [item, setItem] = useState<Item | null>(null);
  const [page, setPage] = useState(0);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [sync, setSync] = useState<Sync | null>(null);
  const syncRevision = useRef(0);
  const [syncUnknown, setSyncUnknown] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [needsReload, setNeedsReload] = useState(false);
  const [scanLoaded, setScanLoaded] = useState('');
  const [scanAttempt, setScanAttempt] = useState(0);
  const [scanFailed, setScanFailed] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  const [draft, setDraft] = useState('');
  const [alternatives, setAlternatives] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [lastSaved, setLastSaved] = useState<{
    item: Item;
    decisionId: string;
    text: string;
  } | null>(null);
  const activeFieldRef = useRef<HTMLElement>(null);
  const [showHelp, setShowHelp] = useState(false);
  const [moreHelp, setMoreHelp] = useState(false);
  const [shortcuts, setShortcuts] = useState(() => readPreference(SHORTCUTS_KEY, true));
  const [showHistory, setShowHistory] = useState(false);
  const [expandedColumns, setExpandedColumns] = useState<string[]>([]);
  const [finishError, setFinishError] = useState('');
  const [exited, setExited] = useState(false);

  useEffect(() => {
    activeFieldRef.current?.scrollIntoView?.({ block: 'nearest' });
    if (!correcting) activeFieldRef.current?.focus({ preventScroll: true });
  }, [item?.id, reviewer]);

  useEffect(() => {
    function warnBeforeClose(event: BeforeUnloadEvent) {
      if (pending || (correcting && draft !== (item?.field.value ?? ''))) {
        event.preventDefault();
        event.returnValue = '';
      }
    }
    window.addEventListener('beforeunload', warnBeforeClose);
    return () => window.removeEventListener('beforeunload', warnBeforeClose);
  }, [pending, correcting, draft, item]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function initialize() {
      try {
        const health = await api<{
          ready: boolean;
          diagnostics: { message: string }[];
        }>('/api/health');
        if (!health.ready) {
          if (health.diagnostics.length)
            throw new ApiError(health.diagnostics.map((d) => d.message).join(' '), 503);
          timer = setTimeout(initialize, 2000);
          return;
        }
        const data = await api<{ regions: Region[] }>('/api/regions');
        if (!cancelled) {
          setRegions(data.regions);
          setRegion(data.regions[0]?.region ?? '');
          setReady(true);
        }
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 0) timer = setTimeout(initialize, 2000);
        else
          setStartupError(
            e instanceof Error ? e.message : 'Could not open the review tool.',
          );
      }
    }
    void initialize();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  function showSync(data: Sync) {
    syncRevision.current += 1;
    setSync(data);
    setSyncUnknown(false);
    if (data.error && stopCodes.has(data.error.code)) setStopped(true);
  }
  useEffect(() => {
    if (!reviewer) return;
    let cancelled = false;
    async function poll() {
      if (busyRef.current) return;
      const revision = syncRevision.current;
      try {
        const data = await api<Sync>('/api/sync/status');
        if (!cancelled && revision === syncRevision.current) showSync(data);
      } catch {
        if (!cancelled && revision === syncRevision.current) setSyncUnknown(true);
      }
    }
    void poll();
    const timer = setInterval(poll, 10000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [reviewer]);

  async function run(work: () => Promise<void>) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await work();
    } catch (e) {
      const failure =
        e instanceof ApiError
          ? e
          : new ApiError(e instanceof Error ? e.message : 'Request failed.');
      if (failure.code === 'no_op')
        setNotice('Already saved. To amend the value, choose Correct.');
      else setError(failure.message);
      if (stopCodes.has(failure.code)) setStopped(true);
      if (failure.status === 409) setNeedsReload(true);
      if (failure.status === 401) setReviewer('');
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  async function loadRegion(id: string) {
    setRegion(id);
    setQueue(null);
    setItem(null);
    setPage(0);
    setLastSaved(null);
    setDwellingItems(null);
    const data = await api<DwellingQueue>(
      `/api/dwellings?${new URLSearchParams({ region: id })}`,
    );
    setQueue(data);
  }
  async function openItem(id: string, retainDraft = false) {
    // Remove old evidence before the request; late image events cannot enable it.
    setScanLoaded('');
    setScanFailed(false);
    const next = await api<Item>(`/api/review-items/${id}`);
    if (retainDraft) {
      setDwellingItems(
        await api<Queue>(
          `/api/dwellings/${next.dwelling_id}/items?${new URLSearchParams({ region: next.region })}`,
        ),
      );
    }
    setItem(next);
    setScanAttempt((attempt) => attempt + 1);
    setNeedsReload(false);
    setAlternatives(false);
    setShowHistory(false);
    setExpandedColumns([]);
    if (!retainDraft) {
      setCorrecting(false);
      setDraft(next.field.value ?? '');
    }
  }
  async function signIn() {
    const data = await api<{ reviewer: string }>('/api/session', {
      name: name.trim(),
    });
    // Signing in remounts the scan; a previous reviewer's load is not current evidence.
    setScanLoaded('');
    setScanFailed(false);
    setScanAttempt((attempt) => attempt + 1);
    setReviewer(data.reviewer);
    setExited(false);
    if (!readPreference(HELP_KEY)) setShowHelp(true);
    if (!queue && region) await loadRegion(region);
  }
  async function refreshQueue() {
    setQueue(
      await api<DwellingQueue>(`/api/dwellings?${new URLSearchParams({ region })}`),
    );
  }
  async function openDwelling(row: Dwelling) {
    setLastSaved(null);
    const data = await api<Queue>(
      `/api/dwellings/${row.id}/items?${new URLSearchParams({ region })}`,
    );
    setDwellingItems(data);
    const next = data.items.find((i) => !i.resolved) ?? data.items[0];
    if (next) await openItem(next.id);
    else {
      await refreshQueue();
      setNotice(
        'This dwelling has no supported fields to open. Check the queue messages.',
      );
    }
  }
  function updateQueue(saved: Item) {
    setDwellingItems((previous) => {
      if (!previous) return previous;
      const items = previous.items.map((i) => (i.id === saved.id ? saved : i));
      const resolved = items.filter((i) => i.resolved).length;
      return {
        ...previous,
        items,
        resolved,
        unresolved: previous.total - resolved,
        complete: previous.total > 0 && previous.total === resolved,
      };
    });
  }
  async function submit(request: Pending) {
    setPending(request);
    let result: Saved;
    try {
      result = await api<Saved>(request.path, request.body);
    } catch (e) {
      // A lost response may already have saved. Retry its exact original body.
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) setPending(null);
      throw e;
    }
    if (!result.saved_locally)
      throw new ApiError('Saving has not been confirmed. Your correction is still here.');
    setPending(null);
    showSync(result.sync);
    updateQueue(result.item);
    setCorrecting(false);
    setDraft(result.item.field.value ?? '');
    const undone = result.decision.action === 'undo';
    setLastSaved(
      undone
        ? null
        : {
            item: result.item,
            decisionId: result.decision.id,
            text: `${result.item.review_state === 'accepted' ? 'Accepted' : 'Saved'}: ${result.item.label} ${result.item.field.value ?? statuses[result.item.field.status]}`,
          },
    );
    setItem(result.item);
    if (undone) {
      setScanLoaded('');
      setScanFailed(false);
      setNotice(
        'Undo saved on this computer. The original decision stays in the history.',
      );
    } else {
      const next = dwellingItems?.items.find(
        (i) =>
          i.id !== result.item.id && !i.resolved && dwellingKey(i) === dwellingKey(result.item),
      );
      if (next) {
        try {
          await openItem(next.id);
        } catch {
          setItem(result.item);
          setNotice(
            'Saved on this computer. The next field could not open; return to the queue to continue.',
          );
        }
      }
    }
  }
  async function decide(action: Action) {
    if (!item || !canDecide || !item.allowed_actions.includes(action)) return;
    if (action === 'correct' && !(item.field_kind === 'text' ? !!draft.trim() : /^[0-9]{1,64}$/.test(draft))) return;
    await submit({
      path: `/api/review-items/${item.id}/decisions`,
      body: {
        action,
        ...(action === 'correct' ? { value: draft } : {}),
        expected_version: item.version,
        request_id: crypto.randomUUID(),
      },
    });
  }
  async function undo(id: string, decisionId: string) {
    const target = await api<Item>(`/api/review-items/${id}`);
    await submit({
      path: `/api/decisions/${decisionId}/undo`,
      body: {
        expected_version: target.version,
        request_id: crypto.randomUUID(),
      },
    });
  }
  async function share() {
    showSync(await api<Sync>('/api/sync', {}));
  }
  async function finish() {
    if (busyRef.current || pending || correcting || stopped) return;
    await run(async () => {
      setFinishError('');
      try {
        await share();
      } catch (failure) {
        setSyncUnknown(true);
        setFinishError(
          failure instanceof Error ? failure.message : 'Sharing has not been confirmed.',
        );
      }
      setExited(true);
    });
  }
  function closeHelp() {
    savePreference(HELP_KEY, true);
    setShowHelp(false);
  }

  const groups = queue?.dwellings ?? [];
  const continueDwelling = groups.find((d) => d.unresolved > 0 && d.first_item_id);
  const dwelling = dwellingItems?.items ?? [];
  const cardItems = item
    ? dwelling.filter((i) => i.source.card_id === item.source.card_id)
    : [];
  const cardFields = item?.card_fields ?? cardItems;
  const cards = item?.cards ?? [];
  const scanKey = item ? `${item.id}:${item.version}:${scanAttempt}` : '';
  const canNavigate = !busy && !pending && !correcting && !showHelp && !exited;
  const canDecide =
    !!reviewer &&
    !busy &&
    !pending &&
    !stopped &&
    !needsReload &&
    !showHelp &&
    !exited &&
    !!item &&
    scanLoaded === scanKey &&
    !scanFailed &&
    !item.diagnostics.length;
  const textField = item?.field_kind === 'text';
  const validCorrection = textField ? !!draft.trim() : /^[0-9]{1,64}$/.test(draft);
  const syncText = syncUnknown
    ? 'Sharing status unavailable'
    : !sync
      ? 'Checking sharing…'
      : {
          uploaded: 'Shared',
          waiting_to_upload: 'Saved here · not shared yet',
          uploading: 'Sharing…',
          upload_failed: "Saved here · couldn't share yet",
        }[sync.state];
  const time = sync?.pushed_at
    ? new Date(sync.pushed_at).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      })
    : '';

  return (
    <div className="app">
      <header className="top">
        {item && reviewer ? (
          <>
            <button
              className="btn ghost sm"
              disabled={!canNavigate}
              onClick={() =>
                void run(async () => {
                  setItem(null);
                  setScanLoaded('');
                  await refreshQueue();
                })
              }
            >
              ← Queue
            </button>
            <strong className="rid">{item.source.role === 'survey-back' ? 'Dwelling interview notes' : item.source.role === 'survey-front' ? 'Dwelling survey front' : item.record_id ?? 'Number not identified'}</strong>
            <span className="cardscore">
              This card <Confidence score={item.card_score} />
            </span>
            <span className="meta">
              {item.address ?? 'Address not available'} · {item.region}
              {item.region_title ? ` · ${item.region_title}` : ''}
            </span>
          </>
        ) : (
          <strong className="prod">Survey Card Review</strong>
        )}
        <span className="sp" />
        {ready && (
          <button
            disabled={busy || exited}
            className="btn ghost sm"
            onClick={() => {
              setMoreHelp(false);
              setShowHelp(true);
            }}
          >
            Help
          </button>
        )}
        {reviewer && (
          <>
            <span
              role="status"
              className={`sync ${sync?.state === 'upload_failed' ? 'fail' : ''}`}
            >
              {sync?.state === 'uploaded' && !syncUnknown ? '✓ ' : ''}
              {syncText}
              {!syncUnknown && sync?.state === 'uploaded' && time ? ` ${time}` : ''}
            </span>
            <span className="who">
              <strong title={reviewer}>{reviewer}</strong> ·{' '}
              <button
                className="link small"
                disabled={!canNavigate}
                onClick={() => {
                  setReviewer('');
                  setExited(false);
                }}
              >
                Change
              </button>
            </span>
            <button
              className="btn sm"
              disabled={busy || !!pending || correcting || stopped}
              onClick={() => void run(share)}
            >
              Share now
            </button>
          </>
        )}
      </header>
      {error && (
        <div className="errbox" role="alert">
          {error}
          {item && !pending && !stopped && (
            <button
              className="link"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await openItem(item.id, true);
                  setNotice('Field reloaded. Your correction is still here.');
                })
              }
            >
              Reload current field
            </button>
          )}
        </div>
      )}
      {pending && (
        <div className={busy ? 'banner' : 'warnbox'} role="status">
          {busy ? (
            'Saving on this computer…'
          ) : (
            <>
              Saving has not been confirmed. Try again before moving on; your correction is
              still here.{' '}
              <button className="btn" onClick={() => void run(() => submit(pending))}>
                Try again
              </button>
            </>
          )}
        </div>
      )}
      {stopped && (
        <div className="errbox" role="alert">
          Stop reviewing and ask the team to reconcile this region. Local decisions are
          retained. Restart the tool after the team has resolved the problem.
        </div>
      )}
      {sync?.state === 'upload_failed' && !stopped && (
        <div className="warnbox" role="status">
          Your decisions are saved on this computer but not shared with the team yet.{' '}
          {sync.error?.message} We'll try again every few minutes. You can keep reviewing.
        </div>
      )}
      {notice && (
        <div className="banner" role="status">
          {notice}
        </div>
      )}
      {!ready ? (
        <main className="signin">
          <div className="sicol">
            <h1>
              {startupError ? 'The review tool could not open' : 'Loading the review tool…'}
            </h1>
            <p role="status">
              {startupError || 'Opening the results and checking them. This may take a minute.'}
            </p>
            {startupError && (
              <button className="btn" onClick={() => window.location.reload()}>
                Try again
              </button>
            )}
          </div>
        </main>
      ) : !reviewer ? (
        <main className="signin">
          <form
            className="sicol"
            onSubmit={(e) => {
              e.preventDefault();
              void run(signIn);
            }}
          >
            <h1>Who's reviewing today?</h1>
            <div>
              <label className="lbl" htmlFor="name">
                Your name
              </label>
              <input
                className="input wide"
                id="name"
                autoComplete="name"
                maxLength={100}
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoFocus
                disabled={busy}
              />
              <p className="small muted">
                Not a password. Your name is saved with each decision.
              </p>
            </div>
            <button className="btn primary lg" disabled={busy || !name.trim()}>
              {busy ? 'Opening…' : 'Start reviewing'}
            </button>
          </form>
        </main>
      ) : !item ? (
        <main className="qbody">
          <h1>Review queue</h1>
          <div className="strip">
            <label className="regsel">
              Region{' '}
              <select
                aria-label="Region"
                value={region}
                disabled={!canNavigate}
                onChange={(e) => void run(() => loadRegion(e.target.value))}
              >
                {regions.map((r) => (
                  <option key={r.region} value={r.region}>
                    {r.region}
                    {r.title ? ` · ${r.title}` : ''}
                    {!r.has_records
                      ? ' · no records'
                      : !r.has_scan_folder
                        ? ' · scans missing'
                        : ''}
                  </option>
                ))}
              </select>
            </label>
            <div className="prog">
              <b>
                {queue
                  ? `${region}: ${queue.summary.completed_dwellings} of ${queue.summary.queued_dwellings} queued dwellings`
                  : 'Loading dwellings…'}
              </b>
              {queue && (
                <>
                  <span>
                    All regions {queue.all_regions.completed_dwellings} of{' '}
                    {queue.all_regions.queued_dwellings} queued dwellings
                  </span>
                  <progress
                    aria-label="Region progress"
                    value={queue.summary.completed_dwellings}
                    max={Math.max(1, queue.summary.queued_dwellings)}
                  />
                </>
              )}
            </div>
            {queue && (
              <div className="averages small">
                <span>{queue.unresolved.toLocaleString()} fields to review</span>
                <span>
                  Average <Confidence score={queue.summary.average_card_score} /> · all so
                  far {queue.all_regions.average_card_score?.toFixed(2) ?? 'Not scored'}
                </span>
                <span className="muted">
                  {queue.summary.scored_cards} scored coding cards ·{' '}
                  {queue.summary.unscored_cards} not scored
                </span>
              </div>
            )}
            <span className="sp" />
            <button
              className="btn ghost sm"
              disabled={busy || !!pending}
              onClick={() => void run(refreshQueue)}
            >
              Refresh queue
            </button>
            <button
              className="btn"
              disabled={!queue || busy}
              onClick={() => {
                if (!queue) return;
                const url = URL.createObjectURL(
                  new Blob([reviewSummaryCsv(queue)], {
                    type: 'text/csv;charset=utf-8',
                  }),
                );
                const link = document.createElement('a');
                link.href = url;
                link.download = `review-summary-${region}.csv`;
                link.click();
                URL.revokeObjectURL(url);
              }}
            >
              Review summary (.csv)
            </button>
            {continueDwelling && (
              <button
                className="btn primary"
                disabled={!canNavigate}
                onClick={() => void run(() => openDwelling(continueDwelling!))}
              >
                Continue {continueDwelling.record_id ?? 'review'} →
              </button>
            )}
            <button
              className="btn"
              disabled={busy || !!pending || stopped}
              onClick={() => void finish()}
            >
              Save and Exit
            </button>
          </div>
          <p className="queue-scope small muted">
            Progress covers supplied supported flags only. Rows keep the queue's
            lowest-confidence order. Averages cover available coding-card scores, including
            cards outside this queue.
          </p>
          {queue?.diagnostics.length ? (
            <div className="warnbox">
              <strong>Some fields need the team's attention.</strong>
              <ul>
                {queue.diagnostics.map((d, i) => (
                  <li key={i}>{d.message}</li>
                ))}
              </ul>
              <p>These fields stay unresolved.</p>
            </div>
          ) : null}
          {queue && groups.length === 0 && (
            <p className="empty">
              {queue.diagnostics.length
                ? 'No supported coding fields can be opened in this region.'
                : 'No flagged coding fields in this region.'}
            </p>
          )}
          {groups.length > 0 && (
            <>
              <table className="qt">
                <thead>
                  <tr>
                    <th>Dwelling</th>
                    <th>Cards</th>
                    <th>Confidence</th>
                    <th>To review</th>
                    <th>Status</th>
                    <th>Last reviewed by</th>
                    <th>
                      <span className="sr-only">Action</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {groups.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).map((row) => (
                    <tr key={row.id}>
                      <td className="rid">
                        <strong>{row.record_id ?? 'Number not identified'}</strong>
                        <span className="sub">{row.address ?? 'Address not available'}</span>
                        {row.diagnostics?.map((d, i) => (
                          <span className="sub" key={i}>
                            {d.message}
                          </span>
                        ))}
                      </td>
                      <td>
                        {row.card_count} coding {row.card_count === 1 ? 'card' : 'cards'}
                      </td>
                      <td>
                        <Confidence score={row.score} />
                      </td>
                      <td>
                        {row.total} fields · {row.resolved} decided
                      </td>
                      <td>
                        {row.status === 'blocked'
                          ? 'Needs the team’s attention'
                          : row.status === 'complete'
                            ? '● Done'
                            : row.status === 'in_progress'
                              ? '◐ In progress'
                              : '○ Not started'}
                      </td>
                      <td>
                        {row.last_reviewer ?? 'Nobody yet'}
                        {row.last_reviewed_at && (
                          <span className="sub">
                            {new Date(row.last_reviewed_at).toLocaleString('en-AU')}
                          </span>
                        )}
                      </td>
                      <td className="act">
                        <button
                          className="btn sm"
                          disabled={!canNavigate || !row.first_item_id}
                          onClick={() => void run(() => openDwelling(row))}
                        >
                          {row.status === 'complete'
                            ? 'Reopen'
                            : row.status === 'in_progress'
                              ? 'Continue'
                              : 'Review'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="pager">
                <span>
                  {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, groups.length)}{' '}
                  of {groups.length} dwellings
                </span>
                <span className="sp" />
                <button
                  className="btn ghost sm"
                  disabled={busy || page === 0}
                  onClick={() => setPage(page - 1)}
                >
                  ‹ Previous
                </button>
                <span>
                  Page {page + 1} of {Math.ceil(groups.length / PAGE_SIZE)}
                </span>
                <button
                  className="btn ghost sm"
                  disabled={busy || (page + 1) * PAGE_SIZE >= groups.length}
                  onClick={() => setPage(page + 1)}
                >
                  Next ›
                </button>
              </div>
            </>
          )}
        </main>
      ) : (
        <main className="rv">
          <div className="stagecol">
            <nav className="tabs" aria-label="Cards in this dwelling">
              {cards.map((c) => (
                <button
                  key={c.card_id}
                  className={`tab ${c.card_id === item.source.card_id ? 'on' : ''}`}
                  aria-current={c.card_id === item.source.card_id ? 'page' : undefined}
                  disabled={!canNavigate || !c.first_item_id}
                  onClick={() => void run(() => openItem((c.next_item_id ?? c.first_item_id)!))}
                >
                  {c.role === 'survey-front' ? 'Survey front' : c.role === 'survey-back' ? 'Interview notes' : `Coding card · household ${c.household_no ?? 'not identified'}`}
                  {c.record_id && <span className="pg">{c.record_id}</span>}
                  {c.score !== undefined && <Confidence score={c.score} />}
                  {c.page && <span className="pg">p.{c.page}</span>}
                  <span className="ct">
                    {!c.first_item_id ? (
                      'Not queued'
                    ) : (
                      <>
                        {
                          dwelling.filter(
                            (i) => i.source.card_id === c.card_id && !i.resolved,
                          ).length
                        }{' '}
                        to review
                      </>
                    )}
                  </span>
                </button>
              ))}
            </nav>
            {(item.household_count ?? cards.length) > 1 && (
              <p className="household-context small">
                {item.household_count ?? cards.length} households in this dwelling. Shared
                building fields are reviewed on the first coding card only. A single verified survey front and its interview notes can be reviewed. Person columns and ambiguous source ownership need the team’s attention.
              </p>
            )}
            {!!item.dwelling_flags?.length && (
              <div className="warnbox household-context">
                This dwelling needs the team’s attention:{' '}
                {item.dwelling_flags
                  .map(
                    (flag) =>
                      ({
                        persons_unassigned:
                          'People have not been assigned to a household',
                        unplaced: 'The household could not be placed with a survey front',
                        duplicate_record_id:
                          'More than one card has this household number',
                        paired_by_position:
                          'The cards were grouped by their scan positions',
                        identity_reread: 'The identity block was read again',
                        identity_unreadable: 'The household number could not be read',
                      })[flag] ?? 'The card grouping or identity needs checking',
                  )
                  .join('. ')}
                . Identity fields can only be accepted; leave incorrect identities
                pending.
              </div>
            )}
            <ScanViewer
              key={item.source.card_id}
              evidenceKey={scanKey}
              cardId={item.source.card_id}
              scanUrl={item.scan_url}
              alt={`Original card: ${item.source.pdf}, page ${item.source.page}`}
              shortcutsEnabled={shortcuts}
              onLoad={() => {
                setScanLoaded(scanKey);
                setScanFailed(false);
              }}
              onError={() => {
                setScanLoaded('');
                setScanFailed(true);
              }}
            >
              {scanLoaded !== scanKey && (
                <div className="scan-placeholder" role="status">
                  <strong>
                    {scanFailed || item.diagnostics.length
                      ? "Image couldn't load"
                      : 'Opening the scan…'}
                  </strong>
                  <p>
                    {item.source.pdf}, page {item.source.page}
                  </p>
                  {(scanFailed || item.diagnostics.length > 0) && (
                    <>
                      <p>
                        Check that the original PDF is in the scans folder configured in
                        the launcher.
                      </p>
                      <button
                        className="btn"
                        disabled={busy}
                        onClick={() => void run(() => openItem(item.id, true))}
                      >
                        Try loading again
                      </button>
                    </>
                  )}
                </div>
              )}
            </ScanViewer>
          </div>
          <section
            className="panel"
            aria-label="Fields to review on this card"
            tabIndex={0}
            onKeyDown={(event) => {
              if (
                event.altKey ||
                event.ctrlKey ||
                event.metaKey ||
                event.repeat ||
                showHelp ||
                exited
              )
                return;
              const target = event.target as HTMLElement;
              if (event.key === 'Escape' && correcting && !busy && !pending) {
                event.preventDefault();
                setCorrecting(false);
                setDraft(item.field.value ?? '');
                return;
              }
              if (target.closest('input, textarea, select, [contenteditable="true"]')) {
                return;
              }
              const key = event.key.toLowerCase();
              if (shortcuts && key === 'a' && canDecide && !correcting) {
                event.preventDefault();
                void run(() => decide('accept'));
              }
              if (
                shortcuts &&
                key === 'e' &&
                canDecide &&
                item.allowed_actions.includes('correct') &&
                !correcting
              ) {
                event.preventDefault();
                setCorrecting(true);
                setAlternatives(false);
              }
              if (shortcuts && key === 'u' && canDecide && !correcting) {
                const target = lastSaved
                  ? { id: lastSaved.item.id, decision: lastSaved.decisionId }
                  : item.undo_decision_id
                    ? { id: item.id, decision: item.undo_decision_id }
                    : null;
                if (target) {
                  event.preventDefault();
                  void run(() => undo(target.id, target.decision));
                }
              }
              if (
                (event.key === 'ArrowLeft' || event.key === 'ArrowRight') &&
                canNavigate
              ) {
                const index = cardItems.findIndex((field) => field.id === item.id);
                const next = cardItems[index + (event.key === 'ArrowRight' ? 1 : -1)];
                if (next) {
                  event.preventDefault();
                  void run(() => openItem(next.id));
                }
              }
            }}
          >
            {lastSaved && (
              <div className="saved" role="status">
                <span>✓ {lastSaved.text} · saved here</span>
                <button
                  className="btn sm"
                  disabled={busy || !!pending || stopped || correcting}
                  onClick={() => void run(() => undo(lastSaved.item.id, lastSaved.decisionId))}
                >
                  Undo
                </button>
              </div>
            )}
            <div className="p-head">
              <h2>Needs your review ({cardItems.length})</h2>
              <span className="small muted">
                {cardItems.filter((i) => i.resolved).length} of {cardItems.length} decided · in
                card order
              </span>
            </div>
            <div className="p-list">
              {cardFields.map((row, index) => {
                const column = row.column;
                const rows = cardFields.filter((field) => field.column === column);
                const completed =
                  !!column &&
                  rows.every((field) => !field.id || field.review_state !== 'pending') &&
                  !rows.some((field) => field.id === item.id);
                const folded = completed && !expandedColumns.includes(column!);
                const heading = column && cardFields[index - 1]?.column !== column;
                return (
                  <div key={row.field_path}>
                    {heading &&
                      (completed ? (
                        <button
                          className="column-heading"
                          aria-expanded={!folded}
                          onClick={() =>
                            setExpandedColumns((previous) =>
                              folded
                                ? [...previous, column]
                                : previous.filter((value) => value !== column),
                            )
                          }
                        >
                          <b>{column}</b> · {rows[0].label} to {rows.at(-1)!.label}{' '}
                          <span>
                            {rows.filter((field) => field.id).length} decided ·{' '}
                            {folded ? 'Show' : 'Hide'}
                          </span>
                        </button>
                      ) : (
                        <h3 className="column-heading">{column}</h3>
                      ))}
                    {!folded &&
                      (row.id === item.id ? (
                        <article
                          className="open"
                          key={row.field_path}
                          ref={activeFieldRef}
                          tabIndex={-1}
                        >
                          <h3>{item.label}</h3>
                          <p className="where">
                            {item.column ? `${item.column} · ` : ''}{item.source.role === 'survey-back' ? 'Read the interview notes on this back. Nothing is highlighted.' : `Find “${item.label}” on the card. Nothing is highlighted.`}
                          </p>
                          <p className={`value ${textField ? 'text-value' : ''}`}>
                            <strong>
                              <Value item={item} />
                            </strong>
                            {item.field.label && (
                              <span className="mean">{item.field.label}</span>
                            )}
                          </p>
                          <div className="facts">
                            <span>
                              {item.field.code ? `Code ${item.field.code} · ` : ''}
                              {statuses[item.field.status]}
                            </span>
                            <Confidence score={item.field.confidence} />
                          </div>
                          <span
                            className={`tag ${item.review_state === 'pending' ? 'machine' : item.review_state}`}
                          >
                            {item.review_state === 'pending'
                              ? 'MACHINE'
                              : item.review_state.toUpperCase()}
                          </span>
                          <details className="why" open>
                            <summary>How reliable is this?</summary>
                            <p>
                              {item.field.confidence === 0.91
                                ? "Only one computer reader has read this card, so there's nothing to compare. In our tests its readings were right about 9 times in 10. A number is only “sure” once two readers agree."
                                : item.field.confidence === null
                                  ? "We can't say how sure the machine is: no score is available. Check this field against the card."
                                  : 'The score describes the machine reading, not a guarantee. Check the value and its status against the card.'}
                            </p>
                            {item.reason && <p>Flagged because: {item.reason}</p>}
                          </details>
                          {item.field.origin === 'corrected' && (
                            <p className="small">
                              Machine read:{' '}
                              {item.field.original_value ?? 'No readable value'}. The
                              original is kept.
                            </p>
                          )}
                          {item.warnings.length > 0 && (
                            <ul className="warnings">
                              {item.warnings.map((w) => (
                                <li key={w}>{w}</li>
                              ))}
                            </ul>
                          )}
                          {item.diagnostics.map((d) => (
                            <p className="errbox" key={d.code}>
                              {d.message}
                            </p>
                          ))}
                          {correcting ? (
                            <form
                              onSubmit={(e) => {
                                e.preventDefault();
                                void run(() => decide('correct'));
                              }}
                            >
                              <label className="lbl" htmlFor="correction">
                                Your correction
                              </label>
                              {textField ? (
                                <textarea
                                  id="correction"
                                  className="input"
                                  value={draft}
                                  onChange={(e) => setDraft(e.target.value)}
                                  disabled={busy || !!pending}
                                  rows={6}
                                  autoFocus
                                  aria-describedby="correction-help"
                                />
                              ) : (
                                <input
                                  id="correction"
                                  className={`input ${draft && !validCorrection ? 'err' : ''}`}
                                  value={draft}
                                  onChange={(e) => setDraft(e.target.value)}
                                  disabled={busy || !!pending}
                                  inputMode="numeric"
                                  maxLength={64}
                                  autoComplete="off"
                                  autoFocus
                                  aria-describedby="correction-help"
                                />
                              )}
                              <p id="correction-help" className="small">
                                {textField ? 'Copy the text as written. Line breaks and Unicode are kept. Use Nothing on the card for a blank source.' : 'Digits only. Type exactly what the card shows. Leading zeros are kept.'}
                              </p>
                              {draft && !validCorrection && (
                                <p className="errbox">
                                  {textField ? 'Enter text, or use Nothing on the card.' : 'Digits only. If the card shows a 1, type 1.'}
                                </p>
                              )}
                              {item.code_list.length > 0 && (
                                <>
                                  <p className="lbl">
                                    {item.field_kind === 'numeric_sentinel'
                                      ? 'Special codes for this field'
                                      : 'Codes for this field, from the code book'}
                                  </p>
                                  <p className="mean-live" aria-live="polite">
                                    {item.code_list.find((code) => code.value === draft)
                                      ?.label ??
                                      (item.field_kind === 'categorical'
                                        ? 'Code not in this list. Check the card; exact digits can still be saved.'
                                        : 'an amount or count')}
                                  </p>
                                  <ul className="codes" aria-label="Codes for this field">
                                    {item.code_list.map((code) => (
                                      <li
                                        key={code.value}
                                        className={code.value === draft ? 'hit' : ''}
                                      >
                                        <b>{code.value}</b> {code.label}
                                      </li>
                                    ))}
                                  </ul>
                                </>
                              )}
                              {item.field_kind === 'unknown' && (
                                <p className="small muted">
                                  This field has no confirmed code list. Copy the digits
                                  exactly.
                                </p>
                              )}
                              {!textField && item.field.value?.startsWith('0') &&
                                draft !== item.field.value && (
                                  <p className="warnbox">
                                    Check the leading zero. The machine read{' '}
                                    {item.field.value}. We save what you type.
                                  </p>
                                )}
                              <p className="diff">
                                <Value item={item} /> →{' '}
                                <b>{draft || 'Your correction'}</b>
                              </p>
                              <div className="acts">
                                <button
                                  className="btn primary lg"
                                  disabled={
                                    !canDecide ||
                                    !validCorrection ||
                                    !item.allowed_actions.includes('correct')
                                  }
                                >
                                  {textField ? 'Save correction' : `Save ${validCorrection ? draft : '(fix the digits first)'}`}
                                </button>
                                <button
                                  className="btn lg"
                                  type="button"
                                  disabled={busy || !!pending}
                                  onClick={() => {
                                    setCorrecting(false);
                                    setDraft(item.field.value ?? '');
                                  }}
                                >
                                  Cancel
                                </button>
                              </div>
                            </form>
                          ) : (
                            <>
                              <div className="acts">
                                <button
                                  className="btn lg"
                                  disabled={
                                    !canDecide || !item.allowed_actions.includes('accept')
                                  }
                                  onClick={() => void run(() => decide('accept'))}
                                >
                                  {textField ? 'Accept' : `Accept ${item.field.value ?? 'stored status'}`}
                                </button>
                                <button
                                  className="btn lg"
                                  disabled={
                                    !canDecide ||
                                    !item.allowed_actions.includes('correct')
                                  }
                                  onClick={() => {
                                    setCorrecting(true);
                                    setAlternatives(false);
                                  }}
                                >
                                  Correct
                                </button>
                              </div>
                              {item.allowed_actions.includes('no_data') && (
                                <div className="alt">
                                  <button
                                    className="link small"
                                    disabled={!canDecide}
                                    onClick={() => setAlternatives(!alternatives)}
                                  >
                                    Can't read it or blank?
                                  </button>
                                </div>
                              )}
                              {alternatives && (
                                <div className="choices">
                                  <button
                                    className="btn"
                                    disabled={
                                      !canDecide ||
                                      !item.allowed_actions.includes('no_data')
                                    }
                                    onClick={() => void run(() => decide('no_data'))}
                                  >
                                    Nothing written: it's blank
                                  </button>
                                  <button
                                    className="btn"
                                    disabled={
                                      !canDecide ||
                                      !item.allowed_actions.includes('illegible')
                                    }
                                    onClick={() => void run(() => decide('illegible'))}
                                  >
                                    Something's there but I can't read it
                                  </button>
                                </div>
                              )}
                            </>
                          )}
                          {scanLoaded !== scanKey && (
                            <p className="small muted">
                              Accept and Correct switch on once the scan and every detail
                              have loaded.
                            </p>
                          )}
                          <button
                            className="link small"
                            aria-expanded={showHistory}
                            onClick={() => setShowHistory(!showHistory)}
                          >
                            {showHistory ? 'Hide history' : 'Show history'}
                          </button>
                          {showHistory && (
                            <History item={item} onClose={() => setShowHistory(false)} />
                          )}
                          {item.undo_decision_id && (
                            <button
                              className="link small undo-field"
                              disabled={!canDecide || correcting}
                              onClick={() =>
                                void run(() => undo(item.id, item.undo_decision_id!))
                              }
                            >
                              Undo latest decision on this field
                            </button>
                          )}
                        </article>
                      ) : (
                        <button
                          className="r"
                          key={row.field_path}
                          disabled={!canNavigate || !row.id}
                          onClick={() =>
                            row.id &&
                            void run(async () => {
                              await openItem(row.id!);
                              setShowHistory(row.review_state !== 'pending');
                            })
                          }
                        >
                          <span className="nm">{row.label}</span>
                          <b className="val">
                            {row.field.value ?? statuses[row.field.status]}
                          </b>
                          <Confidence score={row.field.confidence} />
                          <span
                            className={`tag ${row.review_state === 'pending' ? 'machine' : row.review_state}`}
                          >
                            {!row.id
                              ? 'NOT QUEUED'
                              : row.review_state === 'pending'
                                ? 'MACHINE'
                                : row.review_state.toUpperCase()}
                          </span>
                        </button>
                      ))}
                  </div>
                );
              })}
            </div>
            <div className="exitbar">
              <button
                className="btn lg"
                disabled={busy || !!pending || correcting || stopped}
                onClick={() => void finish()}
              >
                Save and Exit
              </button>
            </div>
            <p className="agreed small muted">
              Fields follow the printed card order. Fields outside the supplied queue are shown
              for context only.
            </p>
          </section>
        </main>
      )}
      {showHelp && (
        <Help
          reviewer={reviewer || 'reviewer'}
          more={moreHelp}
          shortcuts={shortcuts}
          setMore={setMoreHelp}
          setShortcuts={(value) => {
            setShortcuts(value);
            savePreference(SHORTCUTS_KEY, value);
          }}
          onClose={closeHelp}
        />
      )}
      {exited && (
        <Dialog title="You're all saved" compact onClose={() => setExited(false)}>
          <p>Every decision saved as you made it.</p>
          {sync?.state === 'uploaded' && !sync.pending && !syncUnknown && !stopped ? (
            <p>Shared with the team{time ? ` at ${time}` : ''}.</p>
          ) : (
            <p className="warnbox">
              Sharing has not been confirmed. Your decisions remain on this computer. Keep
              the tool running to retry, or reopen it later.
            </p>
          )}
          {finishError && <p className="small">{finishError}</p>}
          {stopped && (
            <p className="errbox">
              Ask the team to reconcile this region before continuing.
            </p>
          )}
          {item && (
            <p>
              To continue, choose region {item.region}, dwelling{' '}
              {item.source.role === 'survey-back' ? 'Dwelling interview notes' : item.source.role === 'survey-front' ? 'Dwelling survey front' : item.record_id ?? 'Number not identified'} in the queue.
              {dwelling.find((field) => !field.resolved) && (
                <>
                  {' '}
                  Next:{' '}
                  <b>
                    coding card{' '}
                    {dwelling.find((field) => !field.resolved)!.record_id ??
                      'Number not identified'}
                    , page {dwelling.find((field) => !field.resolved)!.source.page},{' '}
                    {dwelling.find((field) => !field.resolved)!.label}
                  </b>
                  .
                </>
              )}
            </p>
          )}
          {item && !dwelling.some((field) => !field.resolved) && (
            <p>
              Every supported field in this dwelling has a decision. Return to the queue
              to check for diagnostics and choose the next dwelling.
            </p>
          )}
          <p className="small muted">
            You may close this tab. Stop the review tool with Ctrl+C in its console.
          </p>
          <div className="dfoot">
            <button
              className="btn primary lg"
              onClick={() => {
                setExited(false);
                setReviewer('');
              }}
            >
              Close
            </button>
            <button className="link" onClick={() => setExited(false)}>
              Keep reviewing
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
}
