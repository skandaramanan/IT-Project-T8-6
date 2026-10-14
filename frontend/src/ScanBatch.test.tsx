import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import ScanBatch from './ScanBatch';
import type { ScanBatchStatus } from './ScanBatch';

const batch: ScanBatchStatus = { region: '216418', pdf: 'original.pdf', size: 4, downloaded: 0, state: 'missing', automatic_download: true, active_region: null, local_file_exists: false, drive_url: 'https://drive.google.com/file/d/original/view', error: null };
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
afterEach(() => { vi.unstubAllGlobals(); });

it('starts an explicit batch download and refreshes the queue once ready', async () => {
  const onReady = vi.fn();
  let state: ScanBatchStatus = batch;
  const fetch = vi.fn(async (_path: string, options?: RequestInit) => {
    if (options?.method === 'POST') state = { ...batch, state: 'ready', downloaded: 4 };
    return response(state);
  });
  vi.stubGlobal('fetch', fetch);
  render(<ScanBatch region="216418" onReady={onReady} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Download scans' }));
  expect(await screen.findByText('Scans ready')).toBeVisible();
  expect(onReady).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenCalledWith('/api/scan-batches/216418/download', expect.objectContaining({ method: 'POST', body: '{}' }));
});

it('shows manual fallback without a Google login when the key is absent', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => response({ ...batch, automatic_download: false })));
  render(<ScanBatch region="216418" onReady={vi.fn()} />);
  expect(await screen.findByRole('button', { name: 'Download scans' })).toBeDisabled();
  expect(screen.getByRole('link', { name: 'Open in Drive' })).toHaveAttribute('href', batch.drive_url);
  expect(screen.getByRole('button', { name: 'Import downloaded PDF' })).toBeEnabled();
  expect(screen.queryByText(/sign in/i)).not.toBeInTheDocument();
});

it('imports a selected PDF as bytes and refreshes review evidence', async () => {
  const onReady = vi.fn();
  const fetch = vi.fn(async (_path: string, options?: RequestInit) => response(options?.method === 'POST' ? { ...batch, state: 'ready' } : batch));
  vi.stubGlobal('fetch', fetch);
  render(<ScanBatch region="216418" onReady={onReady} />);
  await screen.findByRole('button', { name: 'Import downloaded PDF' });
  const file = new File(['test'], 'original.pdf', { type: 'application/pdf' });
  fireEvent.change(screen.getByLabelText('Choose downloaded PDF'), { target: { files: [file] } });
  await waitFor(() => expect(onReady).toHaveBeenCalledTimes(1));
  expect(fetch).toHaveBeenCalledWith('/api/scan-batches/216418/import', expect.objectContaining({ method: 'POST', headers: { 'Content-Type': 'application/pdf' }, body: file }));
});

it('rejects a wrong-size import before uploading and protects existing files', async () => {
  const fetch = vi.fn(async () => response(batch));
  vi.stubGlobal('fetch', fetch);
  const { rerender } = render(<ScanBatch region="216418" onReady={vi.fn()} />);
  await screen.findByRole('button', { name: 'Import downloaded PDF' });
  fireEvent.change(screen.getByLabelText('Choose downloaded PDF'), { target: { files: [new File(['wrong'], 'other.pdf')] } });
  expect(await screen.findByRole('alert')).toHaveTextContent('different size');
  expect(fetch).toHaveBeenCalledTimes(1);
  fetch.mockImplementation(async () => response({ ...batch, region: '216419', local_file_exists: true }));
  rerender(<ScanBatch region="216419" onReady={vi.fn()} />);
  expect(await screen.findByText(/A different PDF exists/)).toBeVisible();
  expect(screen.getByRole('button', { name: 'Download scans' })).toBeDisabled();
});

it('renders progress and cancels a transfer', async () => {
  let state: ScanBatchStatus = { ...batch, state: 'downloading', downloaded: 2, active_region: '216418' };
  const fetch = vi.fn(async (_path: string, options?: RequestInit) => {
    if (options?.method === 'POST') state = { ...batch, state: 'cancelled' };
    return response(state);
  });
  vi.stubGlobal('fetch', fetch);
  render(<ScanBatch region="216418" onReady={vi.fn()} />);
  expect(await screen.findByRole('progressbar')).toHaveAttribute('value', '2');
  fireEvent.click(screen.getByRole('button', { name: 'Cancel transfer' }));
  expect(await screen.findByRole('button', { name: 'Retry download' })).toBeVisible();
  expect(fetch).toHaveBeenCalledWith('/api/scan-batches/216418/cancel', expect.objectContaining({ method: 'POST' }));
});

it('ignores a late availability response from a previous region', async () => {
  let resolve!: (value: Response) => void;
  vi.stubGlobal('fetch', vi.fn((path: string) => path.endsWith('216418') ? new Promise<Response>((r) => { resolve = r; }) : Promise.resolve(response({ ...batch, region: '216419', pdf: 'new.pdf' }))));
  const { rerender } = render(<ScanBatch region="216418" onReady={vi.fn()} />);
  rerender(<ScanBatch region="216419" onReady={vi.fn()} />);
  expect(await screen.findByText(/new.pdf/)).toBeVisible();
  resolve(response(batch));
  await waitFor(() => expect(screen.queryByText(/original.pdf/)).not.toBeInTheDocument());
});
