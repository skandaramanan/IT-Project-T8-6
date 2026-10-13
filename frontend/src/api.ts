// IT-113's HTTP contract. Exact digits and opaque item IDs cross this boundary.
export type Action = 'accept' | 'correct' | 'no_data' | 'illegible';
export type ReviewState = 'pending' | 'accepted' | 'corrected';
export interface Field {
  value: string | null;
  status: 'ok' | 'no_data' | 'illegible' | 'damaged' | 'omitted';
  confidence: number | null;
  code?: string | null;
  label?: string | null;
  negated?: boolean;
  origin?: string;
  original_value?: string | null;
  review?: { state: ReviewState; history: Decision[] };
}
export interface Decision {
  id: string;
  action: Action | 'undo';
  reviewer: string;
  timestamp: string;
  before: Field;
  after: Field;
}
export interface Diagnostic {
  code: string;
  message: string;
  region?: string;
}
export interface Item {
  id: string;
  region: string;
  batch: string;
  record_id: string;
  field_path: string;
  label: string;
  field: Field;
  review_state: ReviewState;
  version: string;
  source: { pdf: string; page: number; card_id: string };
  scan_url: string;
  reason: string;
  allowed_actions: Action[];
  warnings: string[];
  diagnostics: Diagnostic[];
  resolved: boolean;
  undo_decision_id: string | null;
}
export interface Queue {
  items: Item[];
  diagnostics: Diagnostic[];
  total: number;
  resolved: number;
  unresolved: number;
  complete: boolean;
}
export interface Region {
  region: string;
  has_records: boolean;
  has_scan_folder: boolean;
}
export interface Sync {
  state: 'uploaded' | 'waiting_to_upload' | 'uploading' | 'upload_failed';
  pending: boolean;
  pushed_at?: string | null;
  error?: Diagnostic | null;
}
export interface Saved {
  saved_locally: boolean;
  item: Item;
  decision: Decision;
  sync: Sync;
}
export class ApiError extends Error {
  constructor(
    message: string,
    public status = 0,
    public code = '',
  ) {
    super(message);
  }
}
export async function api<T>(path: string, body?: object): Promise<T> {
  let response: Response;
  try {
    response = await fetch(
      path,
      body === undefined
        ? {}
        : {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          },
    );
  } catch {
    throw new ApiError('The review tool is not responding. Your correction is still here.');
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(
      'The review tool returned an unreadable response. Your correction is still here.',
      response.status,
    );
  }
  if (!response.ok)
    throw new ApiError(
      data.error?.message ?? 'Request failed. Your correction is still here.',
      response.status,
      data.error?.code,
    );
  return data as T;
}
// PR 1 has no durable dwelling ID: grouping is for display only. Saves use item.id.
export function dwellingKey(item: Item): string {
  return JSON.stringify([item.region, item.batch, item.record_id.slice(0, -3)]);
}
export function groupDwellings(items: Item[]): Item[][] {
  const groups = new Map<string, Item[]>();
  for (const item of items) {
    const key = dwellingKey(item);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(item);
  }
  return [...groups.values()];
}
