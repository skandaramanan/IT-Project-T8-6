import { useEffect, useState } from 'react';
import Dialog from './Dialog';
import { api } from './api';
import type { CardContext, EvidenceScan, Item, LinkCandidates, RetainedBundle } from './api';

function EvidenceImage({ scan }: { scan: Pick<EvidenceScan, 'scan_url' | 'image' | 'page'> }) {
  const [failed, setFailed] = useState(false);
  return <div className="comparison-scan">
    <p>{scan.image}, page {scan.page ?? 'unknown'}</p>
    {failed ? <p role="status">Scan unavailable. The retained readings remain preserved.</p>
      : <a href={scan.scan_url} target="_blank" rel="noreferrer" aria-label={`Open scan page ${scan.page}`}>
        <img src={scan.scan_url} alt={`Original scan, page ${scan.page}`} onError={() => setFailed(true)} />
      </a>}
  </div>;
}

export function CardComparison({ cardIds, onFix }: { cardIds: string[]; onFix?: (id: string) => void }) {
  const [cards, setCards] = useState<CardContext[]>([]);
  const [error, setError] = useState('');
  const key = cardIds.join(',');
  useEffect(() => {
    let cancelled = false;
    setCards([]); setError('');
    Promise.all(key.split(',').filter(Boolean).map((id) => api<CardContext>(`/api/cards/${id}`)))
      .then((data) => { if (!cancelled) setCards(data); })
      .catch((e: Error) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [key]);
  if (error) return <p role="alert">{error}</p>;
  if (!cards.length) return <p role="status">Opening comparison…</p>;
  return <div className="card-comparison">{cards.map((card) => <section key={card.card_id}>
    <h3>Coding page {card.page} · {card.identity ?? 'Identity incomplete'}</h3>
    <p>{card.address ?? 'No associated address'} · {card.region}</p>
    <EvidenceImage scan={{ scan_url: card.scan_url, image: card.pdf, page: card.page }} />
    {onFix && <div className="comparison-actions">{card.fields.filter((f) => f.id && /\/(municipality|dwelling_no|household_no)$/.test(f.field_path)).map((f) =>
      <button key={f.id} className="btn sm" onClick={() => onFix(f.id!)}>Fix {f.label} on page {card.page}</button>)}</div>}
    <details><summary>Compare transcribed readings</summary>
      <table><thead><tr><th>Field</th><th>Reading</th></tr></thead><tbody>{card.fields.map((f) => {
        const differs = cards.some((c) => c.fields.find((other) => other.label === f.label)?.field.value !== f.field.value);
        return <tr key={f.field_path} className={differs ? 'reading-differs' : ''}><td>{f.label}</td><td>{f.field.value ?? f.field.status.replaceAll('_', ' ')}</td></tr>;
      })}</tbody></table>
    </details>
    {!!card.fronts.length && <details><summary>Associated survey scans ({card.fronts.length})</summary>
      {card.fronts.map((scan) => <EvidenceImage key={scan.card_id} scan={scan} />)}
    </details>}
  </section>)}</div>;
}

function RetainedEvidence({ bundle }: { bundle: RetainedBundle }) {
  const data = bundle.payload;
  return <section className="retained-bundle">
    <h3>Retained evidence from former dwelling</h3>
    <p>This evidence is preserved read-only and is not associated with the current dwelling. Undo can restore the former arrangement when its dependencies remain safe. Attaching it elsewhere is not available here.</p>
    {data.address && <p><strong>Former address:</strong> {data.address.value ?? data.address.status}</p>}
    {data.families_in_dwelling && <p>Families in former dwelling: {data.families_in_dwelling.value ?? data.families_in_dwelling.status}</p>}
    {!!data.handwritten && <dl>{Object.entries(data.handwritten).map(([name, field]) => <div key={name}><dt>{name.replaceAll('_', ' ')}</dt><dd>{field.value ?? field.status}</dd></div>)}</dl>}
    {data.notes?.map((note, i) => <div key={i}><h4>Notes for front page {note.front_page}</h4><p className="verbatim">{note.text.value ?? note.text.status}</p></div>)}
    {!!data.persons?.length && <details><summary>Retained person rows ({data.persons.length})</summary>{data.persons.map((person, i) => <dl key={i}>{Object.entries(person).map(([name, field]) => <div key={name}><dt>{name.replaceAll('_', ' ')}</dt><dd>{field.value ?? field.status}</dd></div>)}</dl>)}</details>}
    {bundle.scans.map((scan) => <EvidenceImage key={scan.card_id} scan={scan} />)}
  </section>;
}

export default function RelinkingTools({ item, savedItem, disabled, onFix, onSubmit }: {
  item: Item;
  savedItem?: Item;
  disabled: boolean;
  onFix: (id: string) => void;
  onSubmit: (path: string, body: object) => Promise<boolean>;
}) {
  const [compareIds, setCompareIds] = useState<string[] | null>(null);
  const [candidates, setCandidates] = useState<LinkCandidates | null>(null);
  const [context, setContext] = useState<CardContext | null>(null);
  const [target, setTarget] = useState('');
  const [retain, setRetain] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [dismissed, setDismissed] = useState('');
  if (!item.prepared_review || item.source.role !== 'coding-front') return null;
  const conflict = item.duplicate_peers?.length ? item : savedItem?.duplicate_peers?.length ? savedItem : null;
  const conflictKey = conflict ? `${conflict.source.card_id}:${conflict.version}` : '';
  async function openLinks() {
    setLoading(true); setError('');
    try {
      const fresh = await api<LinkCandidates>(`/api/cards/${item.source.card_id}/link-candidates`);
      setCandidates(fresh); setTarget(''); setRetain(false);
    } catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }
  async function openRetained() {
    setLoading(true); setError('');
    try { setContext(await api<CardContext>(`/api/cards/${item.source.card_id}`)); }
    catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }
  return <div className="relinking-tools">
    {conflict && dismissed !== conflictKey && <div className="duplicate-banner" role="status">
      <strong>Duplicate identity on coding page {conflict.source.page}.</strong>{' '}
      Also read on {conflict.duplicate_peers!.map((p) => `page ${p.page}`).join(', ')}. All physical cards are preserved. This flag does not block transcription completion.
      <button className="btn sm" disabled={disabled} onClick={() => setCompareIds([conflict.source.card_id, ...conflict.duplicate_peers!.map((p) => p.card_id)])}>Compare</button>
      <button className="btn ghost sm" aria-label="Dismiss duplicate save notice" onClick={() => setDismissed(conflictKey)}>Dismiss</button>
    </div>}
    {item.assigned === false && <p>Identity correction outside your assigned queue. Assigned totals stay unchanged.</p>}
    {item.relink && <p role="status">{item.relink.reason}</p>}
    <div className="comparison-actions">
      <button className="btn sm" disabled={disabled || loading} onClick={() => void openLinks()}>Link to dwelling</button>
      {!!item.retained_bundle_count && <button className="btn sm" disabled={disabled || loading} onClick={() => void openRetained()}>Retained evidence ({item.retained_bundle_count})</button>}
      {!!item.link_history_count && <button className="btn sm" disabled={disabled || loading} onClick={() => void openRetained()}>Link history</button>}
      {item.undo_link_id && <button className="btn sm" disabled={disabled} onClick={async () => {
        setError('');
        try {
          const fresh = await api<CardContext>(`/api/cards/${item.source.card_id}`);
          await onSubmit(`/api/decisions/${item.undo_link_id}/undo`, { expected_version: fresh.version, request_id: crypto.randomUUID() });
        } catch (e) { setError((e as Error).message); }
      }}>Undo last link</button>}
    </div>
    {error && <p role="alert">{error}</p>}
    {compareIds && <Dialog title="Compare coding cards" wide onClose={() => setCompareIds(null)}>
      <CardComparison cardIds={compareIds} onFix={(id) => { setCompareIds(null); setCandidates(null); onFix(id); }} />
    </Dialog>}
    {context && <Dialog title={context.retained_supplements.length ? 'Retained supplementary evidence' : 'Link history'} wide onClose={() => setContext(null)}>
      {context.retained_supplements.map((bundle) => <RetainedEvidence key={bundle.id} bundle={bundle} />)}
      {!!context.link_history?.length && <section><h3>Link history</h3><ol>{context.link_history.map((e) => <li key={e.id}>
        {e.action === 'undo' ? 'Undo of link' : 'Link saved'} · {e.reviewer} · {new Date(e.timestamp).toLocaleString('en-AU')}
        <p>Coding groups: {e.source_pages.map((p) => p.join(', ')).join(' / ')} → {e.destination_pages.map((p) => p.join(', ')).join(' / ')}</p>
      </li>)}</ol></section>}
    </Dialog>}
    {candidates && <Dialog title="Link coding card to dwelling" wide onClose={() => { if (!disabled) setCandidates(null); }}>
      <p>Move this physical coding card with its own readings. Numbers and other coding cards will be preserved.</p>
      {candidates.candidates.filter((c) => !c.current).map((c) => <div className="link-candidate" key={c.card_id}>
        <label><input type="radio" name="link-target" value={c.card_id} checked={target === c.card_id} disabled={disabled} onChange={() => setTarget(c.card_id)} />
          {c.address ?? 'No associated address'} · coding pages {c.coding_pages.join(', ')} · front pages {c.front_pages.join(', ') || 'none'}</label>
        <p>{c.reason}</p>
        <button className="btn sm" disabled={disabled} onClick={() => setCompareIds([item.source.card_id, c.card_id])}>Compare scans</button>
      </div>)}
      <label><input type="radio" name="link-target" value="provisional" checked={target === 'provisional'} disabled={disabled} onChange={() => setTarget('provisional')} /> Keep in a separate coding-only provisional dwelling</label>
      {candidates.requires_retention && <div className="retention-choice"><p>The last coding card would leave survey evidence behind. Keep that evidence separately; it will not become evidence for the destination.</p>
        <label><input type="checkbox" checked={retain} disabled={disabled} onChange={(e) => setRetain(e.target.checked)} /> Retain all former fronts, notes, address and person rows outside the review queue</label>
      </div>}
      <div className="dfoot">
        <button className="btn" disabled={disabled} onClick={() => setCandidates(null)}>Go back</button>
        <button className="btn primary" disabled={disabled || !target || (candidates.requires_retention && !retain)} onClick={async () => {
          await onSubmit(`/api/cards/${item.source.card_id}/link`, { target_card_id: target === 'provisional' ? null : target,
            expected_version: candidates.version, request_id: crypto.randomUUID(), retain_supplements: retain });
          // An uncertain save is retried with the exact body by the app-level
          // retry control. Close the native modal so that control is reachable.
          setCandidates(null);
        }}>Save link</button>
      </div>
    </Dialog>}
  </div>;
}
