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

export const MAX_JOBS = 50;
export const JOB_STORAGE_KEY = `${STORAGE_PREFIX}jobs`;
export const JOB_MAX_AGE_DAYS = 7;
export const DAILY_JOB_LIMIT = 6; // Max completed jobs per day
export const DAILY_JOB_COMPLETIONS_KEY = `${STORAGE_PREFIX}daily_job_completions`;

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
} as const;

export const STATUS_LABELS = {
  pending: 'Pending',
  processing: 'Processing',
  completed: 'Completed',
  failed: 'Failed',
} as const;

// Admin session timeout: 30 minutes
export const ADMIN_SESSION_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes

export const ADMIN_RESUMES_STORAGE_KEY = `${STORAGE_PREFIX}admin_resumes`;

