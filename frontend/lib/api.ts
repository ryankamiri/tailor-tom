/** API client functions for TailorTom backend. */

// Remove trailing slash to avoid double slashes in URLs
const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/+$/, '');

export interface OptimizationRequest {
  resume_latex: string;
  job_description: string;
  target_pages: number;
  first_name: string;
  last_name: string;
  company_name: string;
  max_iterations?: number;
  max_bullet_lines: number;
}

export interface JobStatus {
  job_id: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
  company_name: string | null;
  result: {
    optimized_latex: string;
    filename: string;
  } | null;
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

/**
 * Create a new optimization job.
 */
export async function createOptimizationJob(
  data: OptimizationRequest
): Promise<{ job_id: string; status: string; created_at: string }> {
  const res = await fetch(`${API_BASE}/api/optimize`, {
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

/**
 * Get the status of an optimization job.
 * @throws Error with message containing status information if request fails
 */
export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
  
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Job not found' }));
    const errorMessage = error.detail || 'Failed to get job status';
    // Include status code in error message for better error handling
    const errorWithStatus = new Error(`${errorMessage} (${res.status})`);
    throw errorWithStatus;
  }
  
  return res.json();
}

/**
 * Get the optimized LaTeX for a completed job.
 */
export async function getJobLatex(jobId: string): Promise<LatexResponse> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}/latex`);
  
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to get LaTeX' }));
    throw new Error(error.detail || 'Failed to get optimized LaTeX');
  }
  
  return res.json();
}

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
 * Returns base64-encoded PDF strings.
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
 * Cancel a pending or processing job.
 */
export async function cancelJob(jobId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}/cancel`, {
    method: 'POST',
  });
  
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to cancel job' }));
    throw new Error(error.detail || 'Failed to cancel job');
  }
}

/**
 * Delete a completed or failed job.
 */
export async function deleteJob(jobId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}`, {
    method: 'DELETE',
  });
  
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to delete job' }));
    throw new Error(error.detail || 'Failed to delete job');
  }
}

/**
 * Validate LaTeX by attempting to compile it.
 * This doesn't return a PDF, just validates the syntax.
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
 * This is a general endpoint that doesn't require a job ID.
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

/**
 * Save resume to backend (from settings page).
 */
export async function saveResumeToBackend(
  firstName: string,
  lastName: string,
  userId: string,
  latex: string
): Promise<{ success: boolean; resume_id: string; message: string }> {
  const res = await fetch(`${API_BASE}/api/settings/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      first_name: firstName,
      last_name: lastName,
      user_id: userId,
      latex: latex,
    }),
  });
  
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to save resume' }));
    throw new Error(error.detail || 'Failed to save resume to backend');
  }
  
  return res.json();
}

/**
 * Delete user's resume from Redis (backend).
 */
export async function deleteResumeFromBackend(
  userId: string
): Promise<{ success: boolean; message: string }> {
  const res = await fetch(`${API_BASE}/api/settings/resume`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      user_id: userId,
    }),
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to delete resume' }));
    throw new Error(error.detail || 'Failed to delete resume from backend');
  }
  return res.json();
}

/**
 * Admin: List all saved resumes.
 */
export async function listAdminResumes(password: string): Promise<{
  resumes: Array<{
    resume_id: string;
    first_name: string;
    last_name: string;
    created_at: string;
    filename: string;
  }>;
  count: number;
}> {
  // Create basic auth header
  const credentials = btoa(`admin:${password}`);
  
  const res = await fetch(`${API_BASE}/api/admin/resumes`, {
    method: 'GET',
    headers: {
      'Authorization': `Basic ${credentials}`,
    },
  });
  
  if (!res.ok) {
    if (res.status === 401) {
      throw new Error('Invalid admin password');
    }
    const error = await res.json().catch(() => ({ detail: 'Failed to list resumes' }));
    throw new Error(error.detail || 'Failed to list resumes');
  }
  
  return res.json();
}

/**
 * Admin: Get full resume data including LaTeX.
 */
export async function getAdminResume(
  resumeId: string,
  password: string
): Promise<{
  resume_id: string;
  user_id: string;
  first_name: string;
  last_name: string;
  latex: string;
  created_at: string;
  filename: string;
}> {
  // Create basic auth header
  const credentials = btoa(`admin:${password}`);
  
  const res = await fetch(`${API_BASE}/api/admin/resumes/${resumeId}`, {
    method: 'GET',
    headers: {
      'Authorization': `Basic ${credentials}`,
    },
  });
  
  if (!res.ok) {
    if (res.status === 401) {
      throw new Error('Invalid admin password');
    }
    if (res.status === 404) {
      throw new Error('Resume not found');
    }
    const error = await res.json().catch(() => ({ detail: 'Failed to get resume' }));
    throw new Error(error.detail || 'Failed to get resume');
  }
  
  return res.json();
}

/**
 * Admin: Download a resume as PDF or LaTeX.
 */
export async function downloadResume(
  resumeId: string,
  format: 'pdf' | 'latex',
  password: string
): Promise<Blob> {
  // Create basic auth header
  const credentials = btoa(`admin:${password}`);
  
  const res = await fetch(`${API_BASE}/api/admin/resumes/${resumeId}/download?format=${format}`, {
    method: 'GET',
    headers: {
      'Authorization': `Basic ${credentials}`,
    },
  });
  
  if (!res.ok) {
    if (res.status === 401) {
      throw new Error('Invalid admin password');
    }
    if (res.status === 404) {
      throw new Error('Resume not found');
    }
    const error = await res.json().catch(() => ({ detail: 'Failed to download resume' }));
    throw new Error(error.detail || 'Failed to download resume');
  }
  
  return res.blob();
}

/**
 * Admin: Delete a resume.
 */
export async function deleteResume(
  resumeId: string,
  password: string
): Promise<void> {
  // Create basic auth header
  const credentials = btoa(`admin:${password}`);
  
  const res = await fetch(`${API_BASE}/api/admin/resumes/${resumeId}`, {
    method: 'DELETE',
    headers: {
      'Authorization': `Basic ${credentials}`,
    },
  });
  
  if (!res.ok) {
    if (res.status === 401) {
      throw new Error('Invalid admin password');
    }
    if (res.status === 404) {
      throw new Error('Resume not found');
    }
    const error = await res.json().catch(() => ({ detail: 'Failed to delete resume' }));
    throw new Error(error.detail || 'Failed to delete resume');
  }
}

