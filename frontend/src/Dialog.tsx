import { useEffect, useId, useRef } from 'react';
import type { ReactNode } from 'react';

// Native modal dialogs keep keyboard focus away from the review actions below.
export default function Dialog({
  title,
  onClose,
  children,
  compact = false,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  compact?: boolean;
  wide?: boolean;
}) {
  const titleId = useId();
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = ref.current!;
    if (dialog.showModal) dialog.showModal();
    else dialog.setAttribute('open', '');
    dialog.querySelector<HTMLElement>('button, input, a[href]')?.focus();
    return () => {
      dialog.close?.();
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={`dialog ${compact ? 'fin' : ''} ${wide ? 'wide' : ''}`}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className="dialog-head">
        <h2 id={titleId}>{title}</h2>
        <button className="btn ghost sm" aria-label="Close dialog" onClick={onClose}>
          ×
        </button>
      </div>
      {children}
    </dialog>
  );
}
