import type { Field, Item } from './api';
const statusText = {
  ok: 'Readable',
  no_data: 'Blank',
  illegible: "Can't read it",
  damaged: 'Damaged or covered',
  omitted: 'Not read',
};
function value(field: Field) {
  return field.value ?? statusText[field.status];
}
export default function History({ item, onClose }: { item: Item; onClose: () => void }) {
  const history = item.field.review?.history ?? [];
  const original = history[0]?.before;
  const undone = new Set(
    history
      .filter((decision) => decision.action === 'undo')
      .map((decision) => decision.undo_target),
  );
  const actionText = {
    accept: 'Accepted',
    correct: 'Corrected',
    no_data: 'Marked blank',
    illegible: 'Marked illegible',
    undo: 'Undone',
  };
  return (
    <section className="hist" aria-label={`History of ${item.label}`}>
      <div className="dialog-head">
        <h3>{item.label} · History</h3>
        <button className="btn ghost sm" aria-label="Close history" onClick={onClose}>
          ×
        </button>
      </div>
      <p>
        Machine read:{' '}
        <b>
          {original
            ? original.origin === 'corrected'
              ? (original.original_value ?? 'No numeric value')
              : value(original)
            : item.field.origin === 'corrected'
              ? (item.field.original_value ?? 'No numeric value')
              : value(item.field)}
        </b>
        {' · '}
        {original
          ? original.origin === 'corrected'
            ? 'Original status not recorded'
            : statusText[original.status]
          : item.field.origin === 'corrected'
            ? 'Original status not recorded'
            : statusText[item.field.status]}
        {' · '}
        {(original ? original.confidence : item.field.confidence) === null
          ? 'Not scored'
          : (original ? original.confidence : item.field.confidence)?.toFixed(2)}
      </p>
      {history.length ? (
        <ol>
          {history.map((decision) => (
            <li key={decision.id}>
              <p>
                {actionText[decision.action]}: <b>{value(decision.before)}</b> →{' '}
                <b>{value(decision.after)}</b>
              </p>
              {undone.has(decision.id) && (
                <p className="small">This decision was undone.</p>
              )}
              <p className="small">
                {statusText[decision.after.status]} · by {decision.reviewer} ·{' '}
                <time dateTime={decision.timestamp}>
                  {new Date(decision.timestamp).toLocaleString('en-AU')}
                </time>
              </p>
            </li>
          ))}
        </ol>
      ) : (
        <p>No review decisions recorded on this field.</p>
      )}
      <p className="small muted">
        The original is never deleted. Undo restores the latest applicable decision; the
        history stays.
      </p>
    </section>
  );
}
