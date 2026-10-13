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
  record_id: string | null;
  dwelling_id: string;
  address: string | null;
  region_title: string | null;
  card_score: number | null;
  field_kind: string;
  column?: string;
  household_count?: number;
  dwelling_flags?: string[];
  code_list: { value: string; label: string }[];
  card_fields?: CardField[];
  cards?: Card[];
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
export interface CardField {
  column?: string;
  id: string | null;
  label: string;
  field_path: string;
  field: Field;
  review_state: ReviewState;
}
export interface Card {
  score?: number | null;
  card_id: string;
  household_index: number;
  household_no: string | null;
  page?: number;
  record_id: string | null;
  next_item_id: string | null;
  first_item_id: string | null;
}
export interface Dwelling {
  id: string;
  region: string;
  record_id: string | null;
  address: string | null;
  score: number | null;
  card_count: number;
  total: number;
  resolved: number;
  unresolved: number;
  status: 'pending' | 'in_progress' | 'complete' | 'blocked';
  diagnostics: Diagnostic[];
  next_item_id: string | null;
  first_item_id: string | null;
  last_reviewer: string | null;
  last_reviewed_at: string | null;
}
export interface Summary {
  dwellings: number;
  queued_dwellings: number;
  completed_dwellings: number;
  average_card_score: number | null;
  scored_cards: number;
  unscored_cards: number;
}
export interface DwellingQueue {
  dwellings: Dwelling[];
  diagnostics: Diagnostic[];
  total: number;
  resolved: number;
  unresolved: number;
  complete: boolean;
  summary: Summary;
  all_regions: Summary;
  region_title: string | null;
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
  title?: string | null;
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
// A dwelling's physical identity comes from the backend, never its read number.
export function dwellingKey(item: Item): string {
  return item.dwelling_id;
}

// A progress summary, not a replacement for the authoritative JSONL dataset.
export function reviewSummaryCsv(queue: DwellingQueue): string {
  const rows: unknown[][] = [
    [
      'Region',
      'Dwelling',
      'Address',
      'Coding cards',
      'Confidence',
      'Flagged fields',
      'Decided',
      'To review',
      'Status',
      'Last reviewed by',
      'Last reviewed at',
    ],
    ...queue.dwellings.map((d) => [
      d.region,
      d.record_id,
      d.address,
      d.card_count,
      d.score,
      d.total,
      d.resolved,
      d.unresolved,
      {pending:'Not started',in_progress:'In progress',complete:'Done',blocked:'Needs the team’s attention'}[d.status],
      d.last_reviewer,
      d.last_reviewed_at,
    ]),
  ];
  const cell = (value: unknown) => {
    const text = value == null ? '' : String(value);
    const literal = /^[=+\-@\t\r\n]/.test(text) ? "'" + text : text;
    return '"' + literal.replaceAll('"', '""') + '"';
  };
  return '\ufeff' + rows.map((row) => row.map(cell).join(',')).join('\r\n') + '\r\n';
}
