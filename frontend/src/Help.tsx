import Dialog from './Dialog';

export function readPreference(key: string, fallback = false): boolean {
  try {
    const value = localStorage.getItem(key);
    return value === null ? fallback : value === 'true';
  } catch {
    return fallback;
  }
}
export function savePreference(key: string, value: boolean) {
  try {
    localStorage.setItem(key, String(value));
  } catch {
    /* Review still works without browser storage. */
  }
}
export const SHORTCUTS_KEY = 'review-single-letter-shortcuts';
export const HELP_KEY = 'review-help-seen';

const tips = [
  [
    'The cards',
    'Each dwelling has one coding card per household. Use Card to review above the scan to choose a coding card, survey front or interview notes. Open survey front takes you straight to the front. Nothing is highlighted, so find the field yourself; focus the scan and press M for a magnifier.',
  ],
  [
    "Why it's asking",
    'A computer program read every card. A readable field skips review only when two programs read it the same. The score describes the machine reading; always compare it to the scan.',
  ],
  ['Accept', 'If the card shows the same value, choose Accept or press A.'],
  [
    'Fix',
    'Choose Fix or press E and copy the value on the card. Numeric fields keep leading zeros; text fields keep line breaks and Unicode. Enter saves numeric corrections; use Save correction for text. Esc cancels.',
  ],
  [
    "Blank or can't read it",
    'Use the link under the buttons. Identity and crossed-out fields can only be accepted; leave them pending and ask the team if they are wrong.',
  ],
  [
    'Saving',
    'Every confirmed decision saves on this computer. Sharing with the team is separate. Use Undo or press U to undo the latest decision, or Save and Exit to stop.',
  ],
];
export default function Help({
  reviewer,
  more,
  shortcuts,
  setMore,
  setShortcuts,
  onClose,
}: {
  reviewer: string;
  more: boolean;
  shortcuts: boolean;
  setMore: (value: boolean) => void;
  setShortcuts: (value: boolean) => void;
  onClose: () => void;
}) {
  return (
    <Dialog
      title={more ? 'More help' : `Welcome, ${reviewer}. Six things to know.`}
      onClose={onClose}
      wide={more}
    >
      <div className={`tips ${more ? 'more-help' : ''}`}>
        {tips.map(([title, text], index) => (
          <section className="tipc" key={title}>
            {!more && <span className="n">{index + 1}</span>}
            <div>
              <h3>{title}</h3>
              <p>{text}</p>
            </div>
          </section>
        ))}
        {more && (
          <>
            <section>
              <h3>The magnifier</h3>
              <p>
                Focus the scan, then press M for a lens that follows your mouse at 2.5×.
                With the lens on, + and − change its size; with it off, they zoom the
                card. Drag the scan with the mouse to move it. No mouse? Use Zoom + and −
                and the scrollbars instead. The lens never moves to a field on its own.
              </p>
            </section>
            <section>
              <h3>The queue</h3>
              <p>
                Each row is a dwelling. Pending dwellings stay in lowest-confidence order; reviewed dwellings move to the bottom.
                Choose a region to work through one at a time. Open Review details and scans for progress, averages and scan controls. Review summary (.csv)
                downloads one row per queued dwelling, showing progress; the JSONL results
                contain the corrected dataset.
              </p>
            </section>
            <section>
              <h3>Saving and sharing</h3>
              <p>
                If saving is uncertain, press Try again before moving on. Your correction
                stays here. If sharing fails, local decisions remain saved and the tool
                retries while it is running. For a same-region conflict, stop and ask the
                team to reconcile it.
              </p>
            </section>
            <section>
              <h3>Your name and the scans folder</h3>
              <p>
                Your name isn't a password; it's saved with each decision. Type it the
                same way each time. The scans folder is configured in the launcher. Survey
                fields with one verified front and interview notes with verified front/back provenance can be reviewed. Person fields and ambiguous ownership remain unresolved.
              </p>
            </section>
          </>
        )}
      </div>
      {more && (
        <section className="shortcut-setting">
          <h3>Keyboard shortcuts</h3>
          <label>
            <input
              type="checkbox"
              role="switch"
              aria-label="Single-letter shortcuts"
              checked={shortcuts}
              onChange={(event) => setShortcuts(event.target.checked)}
            />{' '}
            Single-letter shortcuts: {shortcuts ? 'On' : 'Off'}
          </label>
          <p className="small muted">
            Turn off if you use a screen reader or speech input. Remembered on this
            computer when browser storage is available. With them off, use Tab and Enter;
            Enter and Esc still work while correcting.
          </p>
          <p>
            A · Accept　 E · Fix　 U · Undo　 M · Magnifier (scan focus)　 ← / → ·
            Previous / next field (panel focus)
          </p>
        </section>
      )}
      <div className="dfoot">
        <button className="link" onClick={() => setMore(!more)}>
          {more ? 'Six things to know' : 'More help'}
        </button>
        <button className="btn primary lg" onClick={onClose}>
          Got it
        </button>
      </div>
    </Dialog>
  );
}
