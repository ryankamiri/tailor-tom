/** Constants for TailorTom frontend. */

export const STORAGE_PREFIX = 'tailortom:';

// Target pages for resume (optimization and DOCX conversion)
export type TargetPages = 1 | 2 | 3;

export const TARGET_PAGES_OPTIONS: readonly TargetPages[] = [1, 2, 3] as const;

export const DEFAULT_TARGET_PAGES: TargetPages = 1;

/** Parse a value to TargetPages; returns DEFAULT_TARGET_PAGES if invalid. */
export function parseTargetPages(value: unknown): TargetPages {
  const n = typeof value === 'string' ? parseInt(value, 10) : Number(value);
  if (n === 1 || n === 2 || n === 3) return n;
  return DEFAULT_TARGET_PAGES;
}

// Bullet lines configuration
export const MIN_BULLET_LINES = 1;
export const MAX_BULLET_LINES = 5;

// DOCX upload (Settings)
export const MAX_DOCX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB

export const STATUS_COLORS = {
  pending: 'bg-amber-100 text-amber-800 border-amber-200',
  processing: 'bg-blue-100 text-blue-800 border-blue-200',
  completed: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  failed: 'bg-red-100 text-red-800 border-red-200',
  cancelled: 'bg-slate-100 text-slate-700 border-slate-200',
} as const;

export const STATUS_LABELS = {
  pending: 'Pending',
  processing: 'Processing',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
} as const;

// Job polling (active jobs: pending + processing)
export const JOB_POLL_INTERVAL_SECONDS = 20;

