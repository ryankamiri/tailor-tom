/** localStorage helpers for TailorTom. */

import { STORAGE_PREFIX, MAX_JOBS, JOB_STORAGE_KEY, JOB_MAX_AGE_DAYS, ADMIN_RESUMES_STORAGE_KEY } from './constants';

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
 * Check if we can create a new job.
 */
export function canCreateNewJob(): { canCreate: boolean; reason?: string } {
  const jobs = getStoredJobs();
  
  // Count pending/processing jobs
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

