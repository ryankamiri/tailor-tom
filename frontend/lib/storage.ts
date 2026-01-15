/** localStorage helpers for TailorTom. */

import { STORAGE_PREFIX, MAX_JOBS, JOB_STORAGE_KEY, JOB_MAX_AGE_DAYS, ADMIN_RESUMES_STORAGE_KEY, DAILY_JOB_LIMIT } from './constants';

export interface StoredJob {
  jobId: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  createdAt: string; // ISO timestamp
  completedAt?: string | null; // ISO timestamp (optional, only for completed/failed jobs)
  companyName: string | null;
  targetPages: number;
  originalLatex: string; // Store for diff comparison
  optimizedLatex?: string | null; // Store optimized LaTeX (only for completed jobs, stored after fetching from backend)
  filename?: string | null; // Store filename for completed jobs
  errorMessage?: string | null; // Store error message (only for failed jobs)
}

/**
 * Resume LaTeX template.
 */
export function getResumeLatex(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(`${STORAGE_PREFIX}resume_latex`);
}

export function saveResumeLatex(latex: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(`${STORAGE_PREFIX}resume_latex`, latex);
}

export function deleteResumeLatex(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(`${STORAGE_PREFIX}resume_latex`);
}

/**
 * User UUID management.
 * Each user gets a unique UUID stored in localStorage.
 */
export function getUserId(): string {
  if (typeof window === 'undefined') return '';
  
  let userId = localStorage.getItem(`${STORAGE_PREFIX}user_id`);
  
  // Generate new UUID if doesn't exist
  if (!userId) {
    // Generate UUID v4
    userId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
      const r = Math.random() * 16 | 0;
      const v = c === 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
    localStorage.setItem(`${STORAGE_PREFIX}user_id`, userId);
  }
  
  return userId;
}

/**
 * User settings.
 */
export interface UserSettings {
  first_name: string;
  last_name: string;
  target_pages: number;
  max_iterations: number;
  max_bullet_lines: number;
}

export function getSettings(): UserSettings {
  if (typeof window === 'undefined') {
    return {
      first_name: '',
      last_name: '',
      target_pages: 1,
      max_iterations: 3,
      max_bullet_lines: 2,
    };
  }
  
  return {
    first_name: localStorage.getItem(`${STORAGE_PREFIX}first_name`) || '',
    last_name: localStorage.getItem(`${STORAGE_PREFIX}last_name`) || '',
    target_pages: parseInt(localStorage.getItem(`${STORAGE_PREFIX}target_pages`) || '1'),
    max_iterations: parseInt(localStorage.getItem(`${STORAGE_PREFIX}max_iterations`) || '3'),
    max_bullet_lines: parseInt(localStorage.getItem(`${STORAGE_PREFIX}max_bullet_lines`) || '2'),
  };
}

export function saveSettings(settings: UserSettings): void {
  if (typeof window === 'undefined') return;
  
  localStorage.setItem(`${STORAGE_PREFIX}first_name`, settings.first_name);
  localStorage.setItem(`${STORAGE_PREFIX}last_name`, settings.last_name);
  localStorage.setItem(`${STORAGE_PREFIX}target_pages`, settings.target_pages.toString());
  localStorage.setItem(`${STORAGE_PREFIX}max_iterations`, settings.max_iterations.toString());
  localStorage.setItem(`${STORAGE_PREFIX}max_bullet_lines`, settings.max_bullet_lines.toString());
}

/**
 * Job management.
 */

/**
 * Get all stored jobs.
 */
export function getStoredJobs(): StoredJob[] {
  if (typeof window === 'undefined') return [];
  
  const stored = localStorage.getItem(JOB_STORAGE_KEY);
  if (!stored) return [];
  
  try {
    return JSON.parse(stored);
  } catch {
    return [];
  }
}

/**
 * Get a single stored job by jobId.
 */
export function getStoredJob(jobId: string): StoredJob | null {
  if (typeof window === 'undefined') return null;
  
  const jobs = getStoredJobs();
  return jobs.find((j) => j.jobId === jobId) || null;
}

/**
 * Save a job to storage.
 */
export function saveJob(job: StoredJob): void {
  if (typeof window === 'undefined') return;
  
  let jobs = getStoredJobs();
  
  // Remove old jobs (older than 7 days)
  const now = new Date();
  jobs = jobs.filter((j) => {
    const created = new Date(j.createdAt);
    const ageDays = (now.getTime() - created.getTime()) / (1000 * 60 * 60 * 24);
    return ageDays < JOB_MAX_AGE_DAYS;
  });
  
  // Remove oldest completed job if we're at max capacity
  if (jobs.length >= MAX_JOBS) {
    // First try to remove oldest completed job
    const completedJobs = jobs.filter((j) => j.status === 'completed');
    if (completedJobs.length > 0) {
      completedJobs.sort((a, b) => 
        new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
      );
      const oldestCompleted = completedJobs[0];
      jobs = jobs.filter((j) => j.jobId !== oldestCompleted.jobId);
    } else {
      // All jobs are pending/processing, can't add more
      const error = new Error('Too many active jobs. Please wait for some to complete.');
      // This error will be caught and shown as a toast in the calling component
      throw error;
    }
  }
  
  // Add new job
  jobs.push(job);
  
  // Sort by created date (newest first)
  jobs.sort((a, b) => 
    new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  );
  
  localStorage.setItem(JOB_STORAGE_KEY, JSON.stringify(jobs));
}

/**
 * Update a job's status.
 */
export function updateJobStatus(
  jobId: string,
  status: StoredJob['status'],
  companyName?: string | null,
  completedAt?: string | null,
  errorMessage?: string | null
): void {
  if (typeof window === 'undefined') return;
  
  const jobs = getStoredJobs();
  const jobIndex = jobs.findIndex((j) => j.jobId === jobId);
  
  if (jobIndex !== -1) {
    jobs[jobIndex].status = status;
    if (companyName !== undefined) {
      jobs[jobIndex].companyName = companyName;
    }
    if (completedAt !== undefined && (status === 'completed' || status === 'failed')) {
      jobs[jobIndex].completedAt = completedAt;
    }
    if (errorMessage !== undefined && status === 'failed') {
      jobs[jobIndex].errorMessage = errorMessage;
    }
    localStorage.setItem(JOB_STORAGE_KEY, JSON.stringify(jobs));
    // Dispatch custom event to notify components of localStorage change (for same-tab updates)
    window.dispatchEvent(new Event('localStorageChange'));
  }
}

/**
 * Store optimized LaTeX and filename for a completed job.
 * After storing, the backend can delete the job to save memory.
 */
export function storeOptimizedLatex(jobId: string, optimizedLatex: string, filename?: string): void {
  if (typeof window === 'undefined') return;

  const jobs = getStoredJobs();
  const jobIndex = jobs.findIndex((j) => j.jobId === jobId);

  if (jobIndex !== -1) {
    jobs[jobIndex].optimizedLatex = optimizedLatex;
    if (filename) {
      jobs[jobIndex].filename = filename;
    }
    localStorage.setItem(JOB_STORAGE_KEY, JSON.stringify(jobs));
  }
}

/**
 * Get filename for a completed job from localStorage.
 */
export function getJobFilename(jobId: string): string | null {
  if (typeof window === 'undefined') return null;
  
  const jobs = getStoredJobs();
  const job = jobs.find((j) => j.jobId === jobId);
  return job?.filename || null;
}

/**
 * Get optimized LaTeX for a completed job from localStorage.
 */
export function getOptimizedLatex(jobId: string): string | null {
  if (typeof window === 'undefined') return null;
  
  const jobs = getStoredJobs();
  const job = jobs.find((j) => j.jobId === jobId);
  return job?.optimizedLatex || null;
}

/**
 * Get count of completed jobs for today (current local timezone).
 * Only counts jobs with status === 'completed' and completedAt set.
 * Respects admin reset timestamp if set for today.
 * 
 * Timezone handling: Uses current local timezone, so if user travels to a different
 * timezone, "today" is recalculated based on their current location.
 */
function getTodayCompletedJobs(): number {
  if (typeof window === 'undefined') return 0;
  
  // Check if daily count was reset today (in current local timezone)
  const resetKey = `${STORAGE_PREFIX}daily_job_reset`;
  const resetTimestamp = localStorage.getItem(resetKey);
  if (resetTimestamp) {
    // Get reset date in current local timezone
    const resetDate = new Date(parseInt(resetTimestamp, 10));
    resetDate.setHours(0, 0, 0, 0);
    
    // Get today in current local timezone
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    
    // If reset was today (in current timezone), return 0 (bypass active)
    if (resetDate.getTime() === today.getTime()) {
      return 0;
    }
  }
  
  const jobs = getStoredJobs();
  // Get today in current local timezone (automatically adjusts if user changed timezones)
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  
  // Filter to only completed jobs with completedAt set, and count those completed today
  const completedToday = jobs.filter(job => {
    // Only count completed jobs
    if (job.status !== 'completed') return false;
    // Must have completedAt timestamp
    if (!job.completedAt) return false;
    
    try {
      // Parse completedAt (ISO string) and convert to current local timezone
      const completedDate = new Date(job.completedAt);
      // Validate the date was parsed correctly
      if (isNaN(completedDate.getTime())) {
        console.warn(`Invalid completedAt date for job ${job.jobId}: ${job.completedAt}`);
        return false;
      }
      // Set to midnight in current local timezone for comparison
      completedDate.setHours(0, 0, 0, 0);
      
      // Compare dates in current local timezone
      return completedDate.getTime() === today.getTime();
    } catch (error) {
      console.warn(`Error parsing completedAt for job ${job.jobId}:`, error);
      return false;
    }
  });
  
  return completedToday.length;
}

/**
 * Get count of pending and processing jobs.
 */
function getPendingAndProcessingJobs(): number {
  if (typeof window === 'undefined') return 0;
  
  const jobs = getStoredJobs();
  return jobs.filter(
    (j) => j.status === 'pending' || j.status === 'processing'
  ).length;
}

/**
 * Check if user can create a new job based on daily limit.
 * Returns detailed information about remaining jobs.
 * 
 * Edge case handling:
 * - Accounts for pending/processing jobs: total (completed + pending + processing) <= limit
 * - This prevents users from queuing 6 jobs, then completing them all to hit the limit
 * - If user has 3 completed and 2 pending, they can only create 1 more (3+2+1=6)
 */
export function canCreateJobWithinDailyLimit(): { 
  canCreate: boolean; 
  reason?: string;
  completedToday: number;
  pendingAndProcessing: number;
  limit: number;
  remaining: number;
} {
  const completedToday = getTodayCompletedJobs();
  const pendingAndProcessing = getPendingAndProcessingJobs();
  const limit = DAILY_JOB_LIMIT;
  const totalJobs = completedToday + pendingAndProcessing;
  const remaining = Math.max(0, limit - totalJobs);
  
  // Check if total jobs (completed + pending + processing) exceeds limit
  if (totalJobs >= limit) {
    if (completedToday >= limit) {
      // All limit used by completed jobs
      return {
        canCreate: false,
        reason: `Daily limit reached. You've completed ${completedToday} jobs today (limit: ${limit}). Please try again tomorrow.`,
        completedToday,
        pendingAndProcessing,
        limit,
        remaining: 0,
      };
    } else {
      // Some limit used by pending/processing jobs
      return {
        canCreate: false,
        reason: `Daily limit reached. You have ${completedToday} completed and ${pendingAndProcessing} pending/processing jobs (limit: ${limit}). Please wait for some jobs to complete.`,
        completedToday,
        pendingAndProcessing,
        limit,
        remaining: 0,
      };
    }
  }
  
  return {
    canCreate: true,
    completedToday,
    pendingAndProcessing,
    limit,
    remaining,
  };
}

/**
 * Clear daily job count for admin bypass.
 * Stores a reset timestamp in localStorage that makes getTodayCompletedJobs()
 * return 0 for the current day (in current local timezone), effectively resetting the count.
 * 
 * Timezone handling: Uses current local timezone, so reset applies to "today" in
 * the user's current location.
 */
export function clearDailyJobCount(): void {
  if (typeof window === 'undefined') return;
  
  // Get today in current local timezone (automatically adjusts if user changed timezones)
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  
  // Store reset timestamp - when getTodayCompletedJobs checks this and
  // sees it's from today (in current timezone), it will return 0 regardless of actual completed jobs
  const resetKey = `${STORAGE_PREFIX}daily_job_reset`;
  localStorage.setItem(resetKey, today.getTime().toString());
}

/**
 * Check if we can create a new job.
 */
export function canCreateNewJob(): { canCreate: boolean; reason?: string } {
  // Check daily limit first
  const dailyLimitCheck = canCreateJobWithinDailyLimit();
  if (!dailyLimitCheck.canCreate) {
    return {
      canCreate: false,
      reason: dailyLimitCheck.reason,
    };
  }
  
  // Then check active jobs (existing logic)
  const jobs = getStoredJobs();
  const activeJobs = jobs.filter(
    (j) => j.status === 'pending' || j.status === 'processing'
  );
  
  // If all 50 jobs are pending/processing, can't create new one
  if (activeJobs.length >= MAX_JOBS) {
    return {
      canCreate: false,
      reason: 'Too many active jobs. Please wait for some to complete.',
    };
  }
  
  return { canCreate: true };
}

/**
 * Clean up old jobs (called on app load).
 */
export function cleanupOldJobs(): void {
  if (typeof window === 'undefined') return;
  
  const jobs = getStoredJobs();
  const now = new Date();
  
  const filtered = jobs.filter((j) => {
    const created = new Date(j.createdAt);
    const ageDays = (now.getTime() - created.getTime()) / (1000 * 60 * 60 * 24);
    return ageDays < JOB_MAX_AGE_DAYS;
  });
  
  // Keep only the 50 most recent
  const sorted = filtered.sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  );
  const kept = sorted.slice(0, MAX_JOBS);
  
  if (kept.length !== jobs.length) {
    localStorage.setItem(JOB_STORAGE_KEY, JSON.stringify(kept));
  }
}

/**
 * Delete a job from storage.
 */
export function deleteStoredJob(jobId: string): void {
  if (typeof window === 'undefined') return;
  
  const jobs = getStoredJobs();
  const filtered = jobs.filter((j) => j.jobId !== jobId);
  
  if (filtered.length !== jobs.length) {
    localStorage.setItem(JOB_STORAGE_KEY, JSON.stringify(filtered));
    // Dispatch custom event to notify components of localStorage change (for same-tab updates)
    // The 'storage' event only fires for cross-tab changes, so we need a custom event
    window.dispatchEvent(new Event('localStorageChange'));
  }
}

/**
 * Admin resume cache management (localStorage).
 * Used to cache resumes from Redis for offline viewing and merging.
 */
export interface CachedResume {
  resume_id: string;
  user_id?: string;
  first_name: string;
  last_name: string;
  created_at: string;
  filename: string;
  latex?: string; // Full LaTeX content for viewing
}

export function getCachedAdminResumes(): CachedResume[] {
  if (typeof window === 'undefined') return [];
  const cached = localStorage.getItem(ADMIN_RESUMES_STORAGE_KEY);
  if (!cached) return [];
  try {
    return JSON.parse(cached);
  } catch {
    return [];
  }
}

export function saveCachedAdminResumes(resumes: CachedResume[]): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(ADMIN_RESUMES_STORAGE_KEY, JSON.stringify(resumes));
}

export function clearCachedAdminResumes(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(ADMIN_RESUMES_STORAGE_KEY);
}

