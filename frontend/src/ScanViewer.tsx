import { useEffect, useId, useRef, useState } from 'react';
import type { KeyboardEvent, PointerEvent, ReactNode } from 'react';
import './scan-viewer.css';

type Props = {
  scanUrl: string;
  cardId: string;
  alt: string;
  onLoad: () => void;
  onError: () => void;
  children?: ReactNode;
  shortcutsEnabled?: boolean;
  evidenceKey?: string;
};

const MAGNIFICATION = 2.5;

// Keep view settings for one physical card; reload evidence independently for each field/retry.
export default function ScanViewer({
  scanUrl,
  cardId,
  alt,
  onLoad,
  onError,
  children,
  shortcutsEnabled = true,
  evidenceKey,
}: Props) {
  const image = useRef<HTMLImageElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const drag = useRef<{
    x: number;
    y: number;
    left: number;
    top: number;
  } | null>(null);
  const instructions = useId();
  const revision = evidenceKey ?? scanUrl;
  const [loadedKey, setLoadedKey] = useState('');
  const loaded = loadedKey === revision;
  const [zoom, setZoom] = useState(1);
  const [magnifier, setMagnifier] = useState(false);
  const [lensSize, setLensSize] = useState(240);
  const [fitWidth, setFitWidth] = useState(0);
  const [lens, setLens] = useState<{
    x: number;
    y: number;
    width: number;
    height: number;
  } | null>(null);

  useEffect(() => {
    setLens(null);
    drag.current = null;
  }, [revision]);

  useEffect(() => {
    const area = viewport.current;
    if (!area) return;
    function measure() {
      const scan = image.current;
      if (!area || !scan?.naturalWidth || !scan.naturalHeight) return;
      setFitWidth(
        Math.min(
          area.clientWidth,
          (area.clientHeight * scan.naturalWidth) / scan.naturalHeight,
        ),
      );
      setLens(null);
    }
    measure();
    const observer =
      typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
    observer?.observe(area);
    window.addEventListener('resize', measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [loaded]);

  function changeZoom(direction: number) {
    if (magnifier) {
      setLensSize((value) => Math.min(360, Math.max(160, value + direction * 40)));
      return;
    }
    setZoom((value) => Math.min(4, Math.max(0.5, value + direction * 0.25)));
    setLens(null);
  }

  function toggleMagnifier() {
    setMagnifier((value) => !value);
    setLens(null);
  }

  function keyboard(event: KeyboardEvent<HTMLElement>) {
    if (!loaded || event.ctrlKey || event.altKey || event.metaKey) return;
    if (event.key === '+' || event.key === '=') {
      event.preventDefault();
      changeZoom(1);
    } else if (event.key === '-') {
      event.preventDefault();
      changeZoom(-1);
    } else if (shortcutsEnabled && event.key.toLowerCase() === 'm') {
      event.preventDefault();
      toggleMagnifier();
    }
  }

  function moveLens(event: PointerEvent<HTMLImageElement>) {
    if (!loaded || !magnifier || (event.pointerType && event.pointerType !== 'mouse'))
      return;
    const rect = event.currentTarget.getBoundingClientRect();
    setLens({
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
      width: rect.width,
      height: rect.height,
    });
  }

  return (
    <section
      className="stage scan-viewer"
      aria-label="Scanned card"
      onKeyDown={keyboard}
    >
      <div className="ctrls" role="group" aria-label="Scan controls">
        <button
          type="button"
          aria-label={magnifier ? 'Smaller magnifier lens' : 'Zoom out'}
          disabled={!loaded || (magnifier ? lensSize === 160 : zoom === 0.5)}
          onClick={() => changeZoom(-1)}
        >
          −
        </button>
        <span
          className="zv"
          aria-live="polite"
          title={magnifier ? 'Magnifier lens diameter' : 'Scan zoom'}
        >
          {magnifier ? `${lensSize}px` : `${Math.round(zoom * 100)}%`}
        </span>
        <button
          type="button"
          aria-label={magnifier ? 'Larger magnifier lens' : 'Zoom in'}
          disabled={!loaded || (magnifier ? lensSize === 360 : zoom === 4)}
          onClick={() => changeZoom(1)}
        >
          +
        </button>
        <span className="sep" aria-hidden="true" />
        <button
          type="button"
          aria-label="Fit whole card"
          disabled={!loaded}
          onClick={() => {
            setZoom(1);
            setLens(null);
            viewport.current?.scrollTo?.({ top: 0, left: 0 });
          }}
        >
          ⛶
        </button>
        <button
          type="button"
          aria-label="Magnifier (M)"
          aria-pressed={magnifier}
          disabled={!loaded}
          onClick={toggleMagnifier}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <circle
              cx="7"
              cy="7"
              r="4.6"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.7"
            />
            <path
              d="M10.4 10.4l3.6 3.6"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </div>
      <div
        ref={viewport}
        className="scan-scroll"
        tabIndex={0}
        role="region"
        aria-label="Scan image, scroll to inspect"
        aria-describedby={instructions}
        onScroll={() => setLens(null)}
        onPointerDown={(event) => {
          if (
            !loaded ||
            event.button !== 0 ||
            (event.pointerType && event.pointerType !== 'mouse')
          )
            return;
          const area = event.currentTarget;
          drag.current = {
            x: event.clientX,
            y: event.clientY,
            left: area.scrollLeft,
            top: area.scrollTop,
          };
          area.setPointerCapture?.(event.pointerId);
          area.focus();
          event.preventDefault();
        }}
        onPointerMove={(event) => {
          if (!drag.current) return;
          event.currentTarget.scrollLeft =
            drag.current.left - (event.clientX - drag.current.x);
          event.currentTarget.scrollTop =
            drag.current.top - (event.clientY - drag.current.y);
          setLens(null);
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
        onLostPointerCapture={() => {
          drag.current = null;
        }}
      >
        <div
          className="scan-card"
          style={{ width: fitWidth ? fitWidth * zoom : `${zoom * 100}%` }}
        >
          <img
            key={revision}
            ref={image}
            className="scan"
            src={scanUrl}
            data-card-id={cardId}
            alt={alt}
            draggable={false}
            onLoad={() => {
              setLoadedKey(revision);
              onLoad();
            }}
            onError={() => {
              setLoadedKey('');
              setLens(null);
              setMagnifier(false);
              onError();
            }}
            onPointerMove={moveLens}
            onPointerLeave={() => setLens(null)}
          />
          {loaded && magnifier && lens && (
            <div
              className="scan-lens"
              aria-hidden="true"
              style={{
                width: lensSize,
                height: lensSize,
                left: lens.x - lensSize / 2,
                top: lens.y - lensSize / 2,
              }}
            >
              <img
                src={scanUrl}
                alt=""
                draggable={false}
                style={{
                  width: lens.width * MAGNIFICATION,
                  height: lens.height * MAGNIFICATION,
                  left: lensSize / 2 - 3 - lens.x * MAGNIFICATION,
                  top: lensSize / 2 - 3 - lens.y * MAGNIFICATION,
                }}
              />
              <span className="lens-level">2.5×</span>
            </div>
          )}
        </div>
        {children}
      </div>
      <p id={instructions} className="scan-instructions">
        Use + and − to zoom, or change the lens size while the magnifier is on.{' '}
        {shortcutsEnabled
          ? 'M switches the mouse magnifier on or off.'
          : 'Use the Magnifier button to switch it on or off.'}{' '}
        Drag with the mouse or use arrow keys to scroll the scan.
      </p>
    </section>
  );
}
