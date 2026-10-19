import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';

export interface ScanBatchStatus {
  region: string;
  pdf: string;
  size: number;
  downloaded: number;
  state: 'missing' | 'downloading' | 'importing' | 'validating' | 'ready' | 'failed' | 'cancelled';
  automatic_download: boolean;
  active_region: string | null;
  local_file_exists: boolean;
  local_ready?: boolean;
  drive_url: string;
  error: { code: string; message: string } | null;
}
const transferring = (state?: string) => ['downloading', 'importing', 'validating'].includes(state ?? '');
const megabytes = (bytes: number) => `${(bytes / 1_000_000).toFixed(1)} MB`;

export default function ScanBatch({ region, onReady }: { region: string; onReady: () => void | Promise<void> }) {
  const [batch, setBatch] = useState<ScanBatchStatus | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const callback = useRef(onReady);
  callback.current = onReady;
  const scope = useRef(region);
  scope.current = region;
  const awaitingReady = useRef(false);
  const upload = useRef<AbortController | null>(null);
  const input = useRef<HTMLInputElement>(null);

  function receive(data: ScanBatchStatus) {
    if (scope.current !== data.region) return;
    if (transferring(data.state)) awaitingReady.current = true;
    setBatch(data);
    if (awaitingReady.current && data.state === 'ready') {
      awaitingReady.current = false;
      void Promise.resolve(callback.current()).catch((e: unknown) => {
        if (scope.current === data.region) setError(e instanceof Error ? e.message : 'Scans are ready. Refresh the queue to continue.');
      });
    }
  }

  useEffect(() => {
    setBatch(null);
    setError('');
    awaitingReady.current = false;
  }, [region]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const data = await api<ScanBatchStatus>(`/api/scan-batches?${new URLSearchParams({ region })}`);
        if (cancelled) return;
        receive(data);
        timer = setTimeout(poll, transferring(data.state) || data.active_region || uploading ? 1000 : 10000);
      } catch (e) {
        if (cancelled) return;
        // Custom/local datasets need not have a Drive counterpart.
        if (e instanceof ApiError && e.status === 404) return;
        setError(e instanceof Error ? e.message : 'Could not check scan availability.');
        timer = setTimeout(poll, 5000);
      }
    }
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [region, busy, uploading]);

  useEffect(() => () => { upload.current?.abort(); }, []);

  async function action(kind: 'download' | 'cancel') {
    setError('');
    setBusy(true);
    try {
      if (kind === 'download') awaitingReady.current = true;
      receive(await api<ScanBatchStatus>(`/api/scan-batches/${encodeURIComponent(region)}/${kind}`, {}));
      if (kind === 'cancel') upload.current?.abort();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start the transfer.');
    } finally { if (scope.current === region) setBusy(false); }
  }

  async function importPdf(file: File) {
    if (!batch) return;
    if (!file.size || file.size > 1024 ** 3) {
      setError('Choose a PDF between 1 byte and 1 GiB.');
      return;
    }
    setBusy(true);
    setUploading(true);
    setBatch({ ...batch, size: file.size, downloaded: 0, state: 'importing' });
    awaitingReady.current = true;
    setError('');
    const controller = new AbortController();
    upload.current = controller;
    try {
      const response = await fetch(`/api/scan-batches/${encodeURIComponent(region)}/import`, {
        method: 'POST', headers: { 'Content-Type': 'application/pdf', 'X-Scan-Size': String(file.size) }, body: file, signal: controller.signal,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error?.message ?? 'Could not import the PDF.');
      receive(data as ScanBatchStatus);

    } catch (e) {
      if (scope.current === region) setError(controller.signal.aborted ? 'Import cancelled.' : e instanceof Error ? e.message : 'Import failed. Retry with the original PDF.');
    } finally {
      if (scope.current === region) { setBusy(false); setUploading(false); }
      if (upload.current === controller) upload.current = null;
    }
  }

  if (!batch && !error) return null;
  const active = transferring(batch?.state) || uploading;
  const otherActive = batch?.active_region && batch.active_region !== region;
  return <section className="scan-batch" aria-label="Scans for this region">
    {batch && <>
      <strong>{active ? 'Preparing scans…' : batch.state === 'ready' ? 'Scans ready' : batch.local_ready ? 'Scans available; refresh not completed' : 'Scans not ready'}</strong>
      <span className="scan-batch-file">{batch.pdf} · {megabytes(batch.size)}</span>
      {active && <div role="status">
        <progress aria-label="Scan transfer progress" value={batch.downloaded} max={batch.size} />
        <span>{batch.state === 'validating' ? 'Checking PDF…' : `${megabytes(batch.downloaded)} of ${megabytes(batch.size)}`}</span>
      </div>}
      {batch.error && !active && batch.state !== 'ready' && <p role="alert">{batch.error.message}</p>}
      {otherActive && <p role="status">A scan transfer is running for region {batch.active_region}.</p>}
      <div className="scan-batch-actions">
        {!active && <button disabled={busy || !batch.automatic_download || !!otherActive} onClick={() => void action('download')}>
          {batch.state === 'failed' || batch.state === 'cancelled' ? 'Retry download' : batch.local_file_exists ? 'Download latest scans' : 'Download scans'}
        </button>}
        {active && <button disabled={busy && !uploading} onClick={() => void action('cancel')}>Cancel transfer</button>}
        <a href={batch.drive_url} target="_blank" rel="noopener noreferrer">Open in Drive</a>
        <>
          <button disabled={busy || active || !!otherActive} onClick={() => input.current?.click()}>Import downloaded PDF</button>
          <input ref={input} hidden type="file" accept="application/pdf,.pdf" aria-label="Choose downloaded PDF" onChange={(event) => {
            const file = event.target.files?.[0]; event.target.value = ''; if (file) void importPdf(file);
          }} />
        </>
      </div>
      {!batch.automatic_download && batch.state !== 'ready' && <p>Open the PDF in Drive, download it, then import it here. Automatic downloads need a configured Drive API key.</p>}
      {batch.local_file_exists && !active && <p>Downloading or importing replaces the local PDF after validation and keeps a backup.</p>}
      <p>Manual imports are checked for a readable PDF and valid page references; their bytes are not verified against Drive.</p>
    </>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
