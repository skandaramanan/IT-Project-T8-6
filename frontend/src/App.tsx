// A bounded review slice over IT-113: saves are confirmed before advancing.
import { useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError, dwellingKey, groupDwellings } from './api';
import type { Action, Item, Queue, Region, Saved, Sync } from './api';

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
  const band = score === null ? 'none' : score === 0.97 ? 'high' : score < 0.6 ? 'low' : 'med';
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
  const [queue, setQueue] = useState<Queue | null>(null);
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
  const [zoom, setZoom] = useState(1);
  const [exited, setExited] = useState(false);

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
        const health = await api<{ ready: boolean; diagnostics: { message: string }[] }>(
          '/api/health',
        );
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
        else setStartupError(e instanceof Error ? e.message : 'Could not open the review tool.');
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
      if (failure.code === 'no_op') setNotice('Already saved. To amend the value, choose Correct.');
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
    const data = await api<Queue>(`/api/queue?${new URLSearchParams({ region: id })}`);
    setQueue(data);
  }
  async function openItem(id: string, retainDraft = false) {
    // Remove old evidence before the request; late image events cannot enable it.
    setScanLoaded('');
    setScanFailed(false);
    const next = await api<Item>(`/api/review-items/${id}`);
    setItem(next);
    setScanAttempt((attempt) => attempt + 1);
    setNeedsReload(false);
    setAlternatives(false);
    setZoom(1);
    if (!retainDraft) {
      setCorrecting(false);
      setDraft(next.field.value ?? '');
    }
  }
  async function signIn() {
    const data = await api<{ reviewer: string }>('/api/session', { name: name.trim() });
    setReviewer(data.reviewer);
    if (!queue && region) await loadRegion(region);
  }
  function updateQueue(saved: Item) {
    setQueue((previous) => {
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
      setNotice('Undo saved on this computer. The original decision stays in the history.');
    } else {
      const next = queue?.items.find(
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
    if (action === 'correct' && !/^[0-9]{1,64}$/.test(draft)) return;
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

  const groups = useMemo(() => groupDwellings(queue?.items ?? []), [queue]);
  const dwelling = item
    ? (groups.find((g) => dwellingKey(g[0]) === dwellingKey(item)) ?? [item])
    : [];
  const cardItems = item ? dwelling.filter((i) => i.source.card_id === item.source.card_id) : [];
  const cards = [...new Map(dwelling.map((i) => [i.source.card_id, i])).values()];
  const scanKey = item ? `${item.id}:${item.version}:${scanAttempt}` : '';
  const canNavigate = !busy && !pending && !correcting;
  const canDecide =
    !!reviewer &&
    !busy &&
    !pending &&
    !stopped &&
    !needsReload &&
    !!item &&
    scanLoaded === scanKey &&
    !scanFailed &&
    !item.diagnostics.length;
  const validDigits = /^[0-9]{1,64}$/.test(draft);
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
    ? new Date(sync.pushed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '';

  return (
    <div className="app">
      <header className="top">
        {item && reviewer ? (
          <>
            <button className="btn ghost sm" disabled={!canNavigate} onClick={() => setItem(null)}>
              ← Queue
            </button>
            <strong className="rid">{item.record_id}</strong>
            <span className="meta">{item.region}</span>
          </>
        ) : (
          <strong className="prod">Survey Card Review</strong>
        )}
        <span className="sp" />
        {reviewer && (
          <>
            <span role="status" className={`sync ${sync?.state === 'upload_failed' ? 'fail' : ''}`}>
              {sync?.state === 'uploaded' && !syncUnknown ? '✓ ' : ''}
              {syncText}
              {!syncUnknown && sync?.state === 'uploaded' && time ? ` ${time}` : ''}
            </span>
            <span className="who">
              <strong>{reviewer}</strong> ·{' '}
              <button
                className="link small"
                disabled={!canNavigate}
                onClick={() => setReviewer('')}
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
              Saving has not been confirmed. Try again before moving on; your correction is still
              here.{' '}
              <button className="btn" onClick={() => void run(() => submit(pending))}>
                Try again
              </button>
            </>
          )}
        </div>
      )}
      {stopped && (
        <div className="errbox" role="alert">
          Stop reviewing and ask the team to reconcile this region. Local decisions are retained.
          Restart the tool after the team has resolved the problem.
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
            <h1>{startupError ? 'The review tool could not open' : 'Loading the review tool…'}</h1>
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
              <p className="small muted">Not a password. Your name is saved with each decision.</p>
            </div>
            <button className="btn primary lg" disabled={busy || !name.trim()}>
              {busy ? 'Opening…' : 'Start reviewing'}
            </button>
          </form>
        </main>
      ) : exited ? (
        <main className="signin">
          <div className="sicol">
            <h1>You're all saved</h1>
            <p>Every decision saved as you made it.</p>
            <p className={sync?.pending || syncUnknown ? 'warnbox' : 'muted'}>
              {sync?.pending || syncUnknown
                ? 'Sharing has not been confirmed. Your decisions remain on this computer. Reopen the tool to retry sharing.'
                : 'Shared with the team.'}
            </p>
            <p>You may close this tab. Stop the review tool with Ctrl+C in its console.</p>
            <button className="btn" onClick={() => setExited(false)}>
              Keep reviewing
            </button>
          </div>
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
                  ? `${queue.resolved} of ${queue.total} flagged fields decided`
                  : 'Loading flagged fields…'}
              </b>
              <span>Progress covers the supplied coding-card flags only.</span>
            </div>
            <span className="sp" />
            <button
              className="btn"
              disabled={busy || !!pending || stopped}
              onClick={() =>
                void run(async () => {
                  await share();
                  setExited(true);
                })
              }
            >
              Save and Exit
            </button>
          </div>
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
                    <th>To review</th>
                    <th>Status</th>
                    <th>
                      <span className="sr-only">Action</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {groups.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).map((group) => {
                    const resolved = group.filter((i) => i.resolved).length;
                    const next = group.find((i) => !i.resolved) ?? group[0];
                    return (
                      <tr key={dwellingKey(group[0])}>
                        <td>
                          <strong>{group[0].record_id.slice(0, -3)}</strong>
                          <span className="sub">{group[0].batch}</span>
                        </td>
                        <td>
                          {new Set(group.map((i) => i.source.card_id)).size} coding{' '}
                          {new Set(group.map((i) => i.source.card_id)).size === 1
                            ? 'card'
                            : 'cards'}
                        </td>
                        <td>
                          {group.length} fields · {resolved} decided
                        </td>
                        <td>
                          {resolved === group.length
                            ? '● Done'
                            : resolved
                              ? '◐ In progress'
                              : '○ Not started'}
                        </td>
                        <td className="act">
                          <button
                            className="btn sm"
                            disabled={!canNavigate}
                            onClick={() => void run(() => openItem(next.id))}
                          >
                            {resolved === group.length
                              ? 'Reopen'
                              : resolved
                                ? 'Continue'
                                : 'Review'}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="pager">
                <span>
                  {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, groups.length)} of{' '}
                  {groups.length} dwellings
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
            <nav className="tabs" aria-label="Coding cards in this dwelling">
              {cards.map((c) => (
                <button
                  key={c.source.card_id}
                  className={`tab ${c.source.card_id === item.source.card_id ? 'on' : ''}`}
                  aria-current={c.source.card_id === item.source.card_id ? 'page' : undefined}
                  disabled={!canNavigate}
                  onClick={() => void run(() => openItem(c.id))}
                >
                  Coding card · household {Number(c.record_id.slice(-2))}
                  <span className="pg">p.{c.source.page}</span>
                </button>
              ))}
            </nav>
            <section className="stage" aria-label="Scanned coding card">
              <div className="ctrls">
                <button
                  aria-label="Zoom out"
                  disabled={scanLoaded !== scanKey}
                  onClick={() => setZoom(Math.max(0.5, zoom - 0.25))}
                >
                  −
                </button>
                <span className="zv">{Math.round(zoom * 100)}%</span>
                <button
                  aria-label="Zoom in"
                  disabled={scanLoaded !== scanKey}
                  onClick={() => setZoom(Math.min(4, zoom + 0.25))}
                >
                  +
                </button>
                <button aria-label="Fit whole card" onClick={() => setZoom(1)}>
                  ⛶
                </button>
              </div>
              <div className="scan-scroll">
                <img
                  key={scanKey}
                  className="scan"
                  src={item.scan_url}
                  alt={`Original coding card: ${item.source.pdf}, page ${item.source.page}`}
                  style={{ width: `${zoom * 100}%`, maxHeight: zoom === 1 ? '100%' : undefined }}
                  onLoad={() => {
                    setScanLoaded(scanKey);
                    setScanFailed(false);
                  }}
                  onError={() => {
                    setScanLoaded('');
                    setScanFailed(true);
                  }}
                />
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
                          Check that the original PDF is in the scans folder configured in the
                          launcher.
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
              </div>
            </section>
          </div>
          <section className="panel" aria-label="Fields to review on this card">
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
                {cardItems.filter((i) => i.resolved).length} of {cardItems.length} decided
              </span>
            </div>
            <div className="p-list">
              {cardItems.map((row) =>
                row.id === item.id ? (
                  <article className="open" key={row.id}>
                    <h3>{item.label}</h3>
                    <p className="where">
                      Find this printed label on the card. Nothing is highlighted.
                    </p>
                    <p className="value">
                      <strong>
                        <Value item={item} />
                      </strong>
                      {item.field.label && <span className="mean">{item.field.label}</span>}
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
                        Machine read: {item.field.original_value ?? 'No numeric value'}. The
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
                        <input
                          id="correction"
                          className={`input ${draft && !validDigits ? 'err' : ''}`}
                          value={draft}
                          onChange={(e) => setDraft(e.target.value)}
                          disabled={busy || !!pending}
                          inputMode="numeric"
                          maxLength={64}
                          autoComplete="off"
                          autoFocus
                          aria-describedby="digits-help"
                        />
                        <p id="digits-help" className="small">
                          Digits only. Type exactly what the card shows. Leading zeros are kept.
                        </p>
                        {draft && !validDigits && (
                          <p className="errbox">Digits only. If the card shows a 1, type 1.</p>
                        )}
                        {item.field.value?.startsWith('0') && draft !== item.field.value && (
                          <p className="warnbox">
                            Check the leading zero. The machine read {item.field.value}. We save
                            what you type.
                          </p>
                        )}
                        <p className="diff">
                          <Value item={item} /> → <b>{draft || 'Your correction'}</b>
                        </p>
                        <div className="acts">
                          <button
                            className="btn primary lg"
                            disabled={
                              !canDecide ||
                              !validDigits ||
                              !item.allowed_actions.includes('correct')
                            }
                          >
                            Save {validDigits ? draft : '(fix the digits first)'}
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
                            disabled={!canDecide || !item.allowed_actions.includes('accept')}
                            onClick={() => void run(() => decide('accept'))}
                          >
                            Accept {item.field.value ?? 'stored status'}
                          </button>
                          <button
                            className="btn lg"
                            disabled={!canDecide || !item.allowed_actions.includes('correct')}
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
                              disabled={!canDecide || !item.allowed_actions.includes('no_data')}
                              onClick={() => void run(() => decide('no_data'))}
                            >
                              Nothing written: it's blank
                            </button>
                            <button
                              className="btn"
                              disabled={!canDecide || !item.allowed_actions.includes('illegible')}
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
                        Accept and Correct switch on once the scan and every detail have loaded.
                      </p>
                    )}
                    {item.undo_decision_id && (
                      <button
                        className="link small undo-field"
                        disabled={!canDecide || correcting}
                        onClick={() => void run(() => undo(item.id, item.undo_decision_id!))}
                      >
                        Undo latest decision on this field
                      </button>
                    )}
                  </article>
                ) : (
                  <button
                    className="r"
                    key={row.id}
                    disabled={!canNavigate}
                    onClick={() => void run(() => openItem(row.id))}
                  >
                    <span className="nm">{row.label}</span>
                    <b className="val">
                      <Value item={row} />
                    </b>
                    <Confidence score={row.field.confidence} />
                    <span
                      className={`tag ${row.review_state === 'pending' ? 'machine' : row.review_state}`}
                    >
                      {row.review_state === 'pending' ? 'MACHINE' : row.review_state.toUpperCase()}
                    </span>
                  </button>
                ),
              )}
            </div>
            <div className="exitbar">
              <button
                className="btn lg"
                disabled={busy || !!pending || correcting || stopped}
                onClick={() =>
                  void run(async () => {
                    await share();
                    setExited(true);
                  })
                }
              >
                Save and Exit
              </button>
            </div>
            <p className="agreed small muted">
              Only supplied coding-card flags are listed, in queue order.
            </p>
          </section>
        </main>
      )}
    </div>
  );
}
