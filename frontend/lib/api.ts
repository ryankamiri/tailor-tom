/** API client functions for TailorTom backend. */

import { type TargetPages, DEFAULT_TARGET_PAGES } from './constants';
import { authFetch } from './auth';

// Remove trailing slash to avoid double slashes in URLs
const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/+$/, '');

/** Parse error detail from failed response body. */
export async function parseErrorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    const detail = body?.detail;
    if (typeof detail === 'string') return detail;
    if (typeof detail === 'object' && detail !== null) return JSON.stringify(detail);
    return fallback;
  } catch {
    return fallback;
  }
}

export interface AssertOkOptions {
  fallback: string;
  adminForbidden?: boolean;
  notFound?: boolean;
}

/** Throw with appropriate message if !res.ok. */
export async function assertOkOrThrow(res: Response, options: AssertOkOptions): Promise<void> {
  if (res.ok) return;
  const detail = await parseErrorDetail(res, options.fallback);
  if (res.status === 403 && options.adminForbidden) throw new Error('Admin access required');
  if (res.status === 404 && options.notFound) throw new Error(detail || 'Not found');
  throw new Error(detail);
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface OptimizationRequest {
  resume_latex: string;
  job_description: string;
  target_pages: TargetPages;
  first_name: string;
  last_name: string;
  company_name: string;
  max_iterations?: number;
  max_bullet_lines: number;
}

/** V3 analysis payload (from analysis_json). */
export interface V3TokenUsage {
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  estimated_cost_usd?: number | null;
  usage_source?: string | null;
}

export interface JobDetailAnalysis {
  passes_done?: number | null;
  quality_passes?: boolean | null;
  quality_issues_summary?: string | null;
  diagnostics?: Record<string, unknown> | null;
  token_usage?: V3TokenUsage | null;
}

export interface JobStatus {
  job_id: string;
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
  company_name: string | null;
  result: {
    optimized_latex: string;
    filename: string;
    error_details?: {
      iterations: number;
      optimized_latex_available: boolean;
      original_latex_length: number;
      optimized_latex_length: number;
    };
  } | null;
  /** Original LaTeX for diff view (detail only). */
  original_latex?: string | null;
  /** optimizer_version (3 for V3 jobs). */
  optimizer_version?: number | null;
  /** llm_usage_source: actual | mixed | estimated (detail only). */
  llm_usage_source?: string | null;
  /** V3 analysis (detail only, from analysis_json). */
  analysis?: JobDetailAnalysis | null;
  /** True when stored analysis could not be parsed. */
  analysis_parse_failed?: boolean;
}

/** One item in GET /api/jobs list (cursor-paginated). */
export interface JobListItem {
  job_id: string;
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';
  created_at: string;
  completed_at: string | null;
  company_name: string | null;
  error_message: string | null;
}

export interface DiffItemChange {
  type: 'removed' | 'added' | 'unchanged';
  text: string;
  position: number;
}

export interface DiffItemChanges {
  removed_phrases: string[];
  added_phrases: string[];
  word_changes: DiffItemChange[];
}

export interface DiffItem {
  index: number;
  original: {
    text: string;
    latex: string;
  };
  optimized: {
    text: string;
    latex: string;
  };
  changes: DiffItemChanges | null;
}

export interface DiffResponse {
  items: DiffItem[];
  summary: {
    total_items: number;
    changed_items: number;
    original_word_count: number;
    optimized_word_count: number;
    word_change_percent: number;
  };
}

export interface LatexResponse {
  job_id: string;
  latex: string;
  filename: string;
}

/** Shape returned by GET /auth/me and PATCH /auth/me (only fields the frontend uses). */
export interface UserProfile {
  email: string;
  name: string | null;
  first_name: string | null;
  last_name: string | null;
  avatar_url: string | null;
  is_admin: boolean;
  resume_latex: string | null;
  max_iterations: number;
  target_pages: number;
  max_bullet_lines: number;
  /** Max completed + active jobs per day (UTC). */
  daily_job_limit: number;
  /** Completed jobs today (UTC). */
  daily_completions_today: number;
  /** Pending + processing jobs. */
  active_jobs_count: number;
  /** max(0, limit - daily_completions_today - active_jobs_count). */
  daily_limit_remaining: number;
}

// ---------------------------------------------------------------------------
// Auth / Profile
// ---------------------------------------------------------------------------

/** Fetch the authenticated user's profile. */
export async function fetchMe(): Promise<UserProfile> {
  const res = await authFetch(`${API_BASE}/auth/me`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to fetch profile' }));
    throw new Error(err.detail || 'Failed to fetch profile');
  }
  return res.json();
}

/** Partial-update the authenticated user's editable fields. */
export async function updateMe(
  fields: Partial<Pick<UserProfile, 'resume_latex' | 'max_iterations' | 'target_pages' | 'max_bullet_lines'>>,
): Promise<UserProfile> {
  const res = await authFetch(`${API_BASE}/auth/me`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(fields),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to update profile' }));
    throw new Error(err.detail || 'Failed to update profile');
  }
  return res.json();
}

/** Reset the authenticated admin's daily job completions count to 0 for today (UTC). Returns updated profile. Admin only. */
export async function resetMyDailyCount(
  currentUser: Pick<UserProfile, 'is_admin'> | null,
): Promise<UserProfile> {
  if (!currentUser?.is_admin) {
    throw new Error('Admin access required');
  }
  const res = await authFetch(`${API_BASE}/auth/me/reset-daily-count`, { method: 'POST' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to reset daily count' }));
    throw new Error(err.detail || 'Failed to reset daily count');
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Protected endpoints (use authFetch)
// ---------------------------------------------------------------------------

/**
 * Create a new optimization job.
 */
export async function createOptimizationJob(
  data: OptimizationRequest
): Promise<{ job_id: string; status: string; created_at: string }> {
  const res = await authFetch(`${API_BASE}/api/optimize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to create job' }));
    throw new Error(error.detail || 'Failed to create optimization job');
  }

  return res.json();
}

/** Job status filter: single value or list (backend accepts multiple ?status=). */
export type JobStatusFilter =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | ('pending' | 'processing' | 'completed' | 'failed' | 'cancelled')[]
  | null;

/**
 * List current user's jobs with cursor pagination.
 * status: single status, or array of statuses (e.g. ['pending', 'processing'] for active jobs).
 */
export async function listJobs(params: {
  limit: number;
  cursor?: string | null;
  status?: JobStatusFilter;
}): Promise<{ items: JobListItem[]; next_cursor: string | null }> {
  const sp = new URLSearchParams();
  sp.set('limit', String(params.limit));
  if (params.cursor) sp.set('cursor', params.cursor);
  if (params.status != null) {
    if (Array.isArray(params.status)) {
      params.status.forEach((s) => sp.append('status', s));
    } else {
      sp.set('status', params.status);
    }
  }
  const res = await authFetch(`${API_BASE}/api/jobs?${sp.toString()}`);
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to list jobs' }));
    throw new Error(error.detail || 'Failed to list jobs');
  }
  return res.json();
}

/**
 * Get the status of an optimization job.
 */
export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const res = await authFetch(`${API_BASE}/api/jobs/${jobId}`);

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Job not found' }));
    const errorMessage = error.detail || 'Failed to get job status';
    const errorWithStatus = new Error(`${errorMessage} (${res.status})`);
    throw errorWithStatus;
  }

  return res.json();
}

/**
 * Get the optimized LaTeX for a completed job.
 */
export async function getJobLatex(jobId: string): Promise<LatexResponse> {
  const res = await authFetch(`${API_BASE}/api/jobs/${jobId}/latex`);

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to get LaTeX' }));
    throw new Error(error.detail || 'Failed to get optimized LaTeX');
  }

  return res.json();
}

/**
 * Cancel a pending or processing job.
 */
/** Cancel a pending or processing job. Returns the updated job status. */
export async function cancelJob(jobId: string): Promise<{ job_id: string; status: 'cancelled' }> {
  const res = await authFetch(`${API_BASE}/api/jobs/${jobId}/cancel`, {
    method: 'POST',
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to cancel job' }));
    throw new Error(error.detail || 'Failed to cancel job');
  }
  return res.json();
}

/**
 * Delete a completed, failed, or cancelled job.
 */
export async function deleteJob(jobId: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/api/jobs/${jobId}`, {
    method: 'DELETE',
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to delete job' }));
    throw new Error(error.detail || 'Failed to delete job');
  }
}

// ---------------------------------------------------------------------------
// Public endpoints (no auth required)
// ---------------------------------------------------------------------------

/**
 * Compute diff between two LaTeX strings.
 */
export async function computeLatexDiff(originalLatex: string, optimizedLatex: string): Promise<DiffResponse> {
  const res = await fetch(`${API_BASE}/api/diff`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      original_latex: originalLatex,
      optimized_latex: optimizedLatex,
    }),
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to compute diff' }));
    throw new Error(error.detail || 'Failed to compute diff');
  }

  return res.json();
}

/**
 * Get annotated PDFs with highlighted differences.
 */
export async function getAnnotatedDiffPdfs(originalLatex: string, optimizedLatex: string): Promise<{ original_pdf: string; optimized_pdf: string }> {
  const res = await fetch(`${API_BASE}/api/diff-pdfs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      original_latex: originalLatex,
      optimized_latex: optimizedLatex,
    }),
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to generate PDF diffs' }));
    throw new Error(error.detail || 'Failed to generate PDF diffs');
  }

  return res.json();
}

/**
 * Validate LaTeX by attempting to compile it.
 */
export async function validateLatex(latex: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/compile/validate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ latex }),
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Invalid LaTeX syntax' }));
    throw new Error(error.detail || 'Invalid LaTeX syntax');
  }
}

/**
 * Compile LaTeX to PDF.
 */
export async function compileLatexToPdf(
  latex: string,
  filename: string = 'resume.pdf'
): Promise<Blob> {
  const res = await fetch(`${API_BASE}/api/compile`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ latex, filename }),
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to compile PDF' }));
    throw new Error(error.detail || 'Failed to compile LaTeX to PDF');
  }

  return res.blob();
}

// ---------------------------------------------------------------------------
// Admin (JWT-protected — uses authFetch with Bearer token)
// ---------------------------------------------------------------------------

/**
 * Admin: Get global job statistics.
 */
export async function getAdminJobStats(): Promise<{
  processed: number;
  completed: number;
  failed: number;
  cancelled: number;
}> {
  const res = await authFetch(`${API_BASE}/api/admin/stats`);
  if (!res.ok) {
    if (res.status === 403) throw new Error('Admin access required');
    const error = await res.json().catch(() => ({ detail: 'Failed to get stats' }));
    throw new Error(error.detail || 'Failed to get stats');
  }
  return res.json();
}

/** Admin users list: one row (GET /api/admin/users). */
export interface AdminUserRow {
  user_id: string;
  email: string;
  first_name: string;
  last_name: string;
  is_admin: boolean;
  has_resume: boolean;
  active_jobs_count: number;
  daily_quota_used: number;
  month_cost_usd: number;
  total_cost_usd: number;
  completed_count: number;
  failed_count: number;
  last_job_at: string | null;
}

/** Admin users list response (GET /api/admin/users). */
export interface AdminUsersResponse {
  month: { year: number; month: number };
  pagination: AdminPagination;
  users: AdminUserRow[];
}

/** Admin user summary for drawer (GET /api/admin/users/{id}/summary). */
export interface AdminUserSummaryResponse {
  user_id: string;
  email: string;
  first_name: string;
  last_name: string;
  is_admin: boolean;
  has_resume: boolean;
  profile: { email: string; first_name: string; last_name: string; avatar_url: string | null };
  quota: { daily_quota_used: number; active_jobs_count: number };
  job_summary: { completed_count: number; failed_count: number; last_job_at: string | null };
  cost_summary: { month_cost_usd: number; total_cost_usd: number; month: { year: number; month: number } };
  recent_jobs: Array<{
    job_id: string;
    status: string;
    created_at: string;
    completed_at: string | null;
    company_name: string | null;
  }>;
  resume_metadata: { has_resume: boolean; filename: string | null };
}

/** Pass1 reason buckets (V3 health): error / warning / neutral. */
export interface AdminV3HealthReasonBuckets {
  pass1_error_reasons?: Record<string, number>;
  pass1_warning_reasons?: Record<string, number>;
  pass1_neutral_reasons?: Record<string, number>;
  apply_no_effect_count?: number;
  apply_no_effect_rate?: number;
}

/** V3 optimizer health (admin only). */
export interface AdminV3HealthResponse {
  v3_jobs_completed: number;
  v3_jobs_failed: number;
  v3_jobs_sampled: number;
  avg_passes_done: number;
  top_pass1_reasons: Record<string, number>;
  top_pass2_reasons: Record<string, number>;
  chooser_selections_total: number;
  token_prompt_total: number;
  token_completion_total: number;
  cost_usd_total: number;
  usage_source_actual_count: number;
  usage_source_mixed_count?: number;
  usage_source_estimated_count: number;
  /** Error bucket (e.g. too_long_words, compile_failed). */
  pass1_error_reasons?: Record<string, number>;
  /** Warning bucket (e.g. too_short_words). */
  pass1_warning_reasons?: Record<string, number>;
  /** Neutral bucket (e.g. apply_no_effect). */
  pass1_neutral_reasons?: Record<string, number>;
  apply_no_effect_count?: number;
  apply_no_effect_rate?: number;
}

export async function getAdminV3Health(): Promise<AdminV3HealthResponse> {
  const res = await authFetch(`${API_BASE}/api/admin/v3-health`);
  if (!res.ok) {
    if (res.status === 403) throw new Error('Admin access required');
    const error = await res.json().catch(() => ({ detail: 'Failed to get V3 health' }));
    throw new Error(error.detail || 'Failed to get V3 health');
  }
  return res.json();
}

/** Common pagination metadata from admin list endpoints. */
export interface AdminPagination {
  page: number;
  limit: number;
  total_items: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
}

/**
 * Admin: List saved resumes (paginated).
 */
export async function listAdminResumes(params?: {
  page?: number;
  limit?: number;
}): Promise<{
  resumes: Array<{
    user_id: string;
    email: string;
    first_name: string;
    last_name: string;
    avatar_url: string | null;
    created_at: string;
    filename: string;
  }>;
  pagination: AdminPagination;
}> {
  const sp = new URLSearchParams();
  if (params?.page != null) sp.set('page', String(params.page));
  if (params?.limit != null) sp.set('limit', String(params.limit));
  const qs = sp.toString();
  const url = qs ? `${API_BASE}/api/admin/resumes?${qs}` : `${API_BASE}/api/admin/resumes`;
  const res = await authFetch(url);
  await assertOkOrThrow(res, { fallback: 'Failed to list resumes', adminForbidden: true });
  return res.json();
}

/** Admin user-costs response (GET /api/admin/user-costs). */
export interface AdminUserCostsResponse {
  month: {
    year: number;
    month: number;
    utc_start: string;
    utc_end_exclusive: string;
  };
  summary: {
    lifetime_total_cost_usd: number;
    month_total_cost_usd: number;
    users_with_cost_count: number;
  };
  pagination: AdminPagination;
  users: AdminUserCostRow[];
}

export interface AdminUserCostRow {
  user_id: string;
  email: string;
  first_name: string;
  last_name: string;
  total_cost_usd: number;
  month_cost_usd: number;
  job_count_with_cost_lifetime: number;
  job_count_with_cost_month: number;
  last_cost_job_at: string | null;
}

/**
 * Admin: Per-user cost analytics (lifetime + selected UTC month). Requires admin. Paginated.
 */
export async function getAdminUserCosts(params?: {
  year?: number;
  month?: number;
  page?: number;
  limit?: number;
}): Promise<AdminUserCostsResponse> {
  const sp = new URLSearchParams();
  if (params?.year != null) sp.set('year', String(params.year));
  if (params?.month != null) sp.set('month', String(params.month));
  if (params?.page != null) sp.set('page', String(params.page));
  if (params?.limit != null) sp.set('limit', String(params.limit));
  const qs = sp.toString();
  const url = qs ? `${API_BASE}/api/admin/user-costs?${qs}` : `${API_BASE}/api/admin/user-costs`;
  const res = await authFetch(url);
  await assertOkOrThrow(res, { fallback: 'Failed to get user costs', adminForbidden: true });
  return res.json();
}

/** Admin: Aggregated user list for workspace. Paginated, filterable, sortable. */
export async function getAdminUsers(params?: {
  page?: number;
  limit?: number;
  search?: string;
  year?: number;
  month?: number;
  sort?: string;
  order?: 'asc' | 'desc';
  has_resume?: boolean;
  active_only?: boolean;
  failed_only?: boolean;
}): Promise<AdminUsersResponse> {
  const sp = new URLSearchParams();
  if (params?.page != null) sp.set('page', String(params.page));
  if (params?.limit != null) sp.set('limit', String(params.limit));
  if (params?.search != null && params.search.trim()) sp.set('search', params.search.trim());
  if (params?.year != null) sp.set('year', String(params.year));
  if (params?.month != null) sp.set('month', String(params.month));
  if (params?.sort != null) sp.set('sort', params.sort);
  if (params?.order != null) sp.set('order', params.order);
  if (params?.has_resume != null) sp.set('has_resume', String(params.has_resume));
  if (params?.active_only) sp.set('active_only', 'true');
  if (params?.failed_only) sp.set('failed_only', 'true');
  const qs = sp.toString();
  const url = qs ? `${API_BASE}/api/admin/users?${qs}` : `${API_BASE}/api/admin/users`;
  const res = await authFetch(url);
  await assertOkOrThrow(res, { fallback: 'Failed to get admin users', adminForbidden: true });
  return res.json();
}

/** Admin: One user's detailed summary for drawer (recent jobs, quota, cost). */
export async function getAdminUserSummary(
  userId: string
): Promise<AdminUserSummaryResponse> {
  const res = await authFetch(`${API_BASE}/api/admin/users/${userId}/summary`);
  await assertOkOrThrow(res, {
    fallback: 'Failed to get user summary',
    adminForbidden: true,
    notFound: true,
  });
  return res.json();
}

/**
 * Admin: Get full resume data including LaTeX.
 */
export async function getAdminResume(userId: string): Promise<{
  user_id: string;
  email: string;
  first_name: string;
  last_name: string;
  avatar_url: string | null;
  latex: string;
  created_at: string;
  filename: string;
}> {
  const res = await authFetch(`${API_BASE}/api/admin/resumes/${userId}`);
  await assertOkOrThrow(res, {
    fallback: 'Failed to get resume',
    adminForbidden: true,
    notFound: true,
  });
  return res.json();
}

// ---------------------------------------------------------------------------
// DOCX conversion (public)
// ---------------------------------------------------------------------------

export type DocxConversionStatus =
  | { status: 'pending' }
  | { status: 'processing' }
  | { status: 'completed'; latex: string; compiled_pdf: string }
  | { status: 'failed'; error_message: string };

/**
 * Start a DOCX-to-LaTeX conversion job.
 */
export async function startDocxConversion(
  file: File,
  targetPages: TargetPages = DEFAULT_TARGET_PAGES
): Promise<{ conversion_id: string }> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('target_pages', targetPages.toString());

  const res = await fetch(`${API_BASE}/api/convert/docx`, {
    method: 'POST',
    body: formData,
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Conversion failed' }));
    throw new Error(error.detail || 'Failed to start .docx conversion');
  }

  return res.json();
}

/**
 * Poll the status of an in-flight DOCX conversion.
 */
export async function getDocxConversionStatus(
  conversionId: string
): Promise<DocxConversionStatus> {
  const res = await fetch(`${API_BASE}/api/convert/docx/${conversionId}`);

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Conversion not found' }));
    throw new Error(error.detail || 'Failed to get conversion status');
  }

  return res.json();
}
