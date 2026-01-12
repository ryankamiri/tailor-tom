/** Constants for TailorTom frontend. */

export const STORAGE_PREFIX = 'tailortom:';

export const MAX_JOBS = 50;
export const JOB_STORAGE_KEY = `${STORAGE_PREFIX}jobs`;
export const JOB_MAX_AGE_DAYS = 7;
export const DAILY_JOB_LIMIT = 6; // Max completed jobs per day

// Bullet lines configuration
export const MIN_BULLET_LINES = 1;
export const MAX_BULLET_LINES = 5;

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

