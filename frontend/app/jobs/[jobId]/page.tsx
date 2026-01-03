'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { getJobStatus, getJobLatex, JobStatus, deleteJob } from '@/lib/api';
import { updateJobStatus, storeOptimizedLatex, getOptimizedLatex, getStoredJob, getJobFilename } from '@/lib/storage';
import { showJobCompleteNotification, isTabFocused } from '@/lib/notifications';
import { JobStatusBadge } from '@/components/jobs/job-status-badge';
import { JobStatusView } from '@/components/jobs/job-status-view';
import { JobResultsView } from '@/components/jobs/job-results-view';
import { toast } from 'sonner';

export default function JobDetailsPage() {
  const params = useParams();
  const router = useRouter();
  const jobId = params.jobId as string;

  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [originalLatex, setOriginalLatex] = useState<string>('');
  const [optimizedLatex, setOptimizedLatex] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);

  const loadJobResults = useCallback(async () => {
    try {
      // First check if we already have the optimized LaTeX in localStorage
      const storedLatex = getOptimizedLatex(jobId);
      
      if (storedLatex) {
        // We already have it stored, use that
        setOptimizedLatex(storedLatex);
      } else {
        // Check if current jobStatus has LaTeX in result (from backend fetch)
        const currentStatus = jobStatus;
        if (currentStatus?.result?.optimized_latex && currentStatus.result.optimized_latex.length > 0) {
          // Use LaTeX directly from status result (only if not empty)
          setOptimizedLatex(currentStatus.result.optimized_latex);
          const filename = currentStatus.result.filename || 'resume.pdf';
          storeOptimizedLatex(jobId, currentStatus.result.optimized_latex, filename);
        } else {
          // Try to fetch from backend API (works for both completed and failed jobs with LaTeX)
          try {
            const latexData = await getJobLatex(jobId);
            setOptimizedLatex(latexData.latex);
            
            // Store in localStorage
            storeOptimizedLatex(jobId, latexData.latex, latexData.filename);
          } catch (fetchError) {
            // No LaTeX available from any source
            // Use console.error instead of console.warn for better visibility in production
            console.error(`[loadJobResults] No LaTeX available for job ${jobId}:`, fetchError);
          }
        }
      }
      
      // Always delete job from backend after loading results (whether from cache or fetched)
      // This saves backend memory since localStorage is now the source of truth
      try {
        await deleteJob(jobId);
      } catch (error) {
        // Error is logged on backend if job exists but deletion failed
        // Don't show error to user - it's not critical, just means backend keeps the data longer
        // Use console.error for better visibility in production (console.warn may be stripped)
        console.error(`[loadJobResults] Failed to delete job ${jobId} from backend:`, error);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to load job results';
      // Log full error to console
      console.error(`[loadJobResults] Failed to load results for job ${jobId}:`, error);
      toast.error(errorMessage);
    }
  }, [jobId, jobStatus]);

  const loadJobData = useCallback(async () => {
    try {
      // First check localStorage - if job exists there, the backend may have already deleted it
      const storedJob = getStoredJob(jobId);
      
      if (storedJob) {
        // Convert stored job to JobStatus format
        const filename = getJobFilename(jobId);
        const optimizedLatex = getOptimizedLatex(jobId);
          const status: JobStatus = {
            job_id: storedJob.jobId,
            status: storedJob.status,
            created_at: storedJob.createdAt,
            completed_at: storedJob.completedAt || null,
            error_message: storedJob.errorMessage || null,
            company_name: storedJob.companyName || null,
            result: (storedJob.status === 'completed' || storedJob.status === 'failed') && filename && optimizedLatex
              ? { optimized_latex: optimizedLatex, filename } 
              : null,
          };
        setJobStatus(status);
        
        // Set original LaTeX from stored job
        setOriginalLatex(storedJob.originalLatex);

        if (status.status === 'completed' || status.status === 'failed') {
          // Always try to load results for completed or failed jobs
          // loadJobResults() will handle fetching LaTeX from backend if available
          await loadJobResults();
        }
      } else {
        // Job not in localStorage, try to fetch from backend
        try {
          const status = await getJobStatus(jobId);
          setJobStatus(status);

          if (status.status === 'completed' || status.status === 'failed') {
            // Always try to load results for completed or failed jobs
            // loadJobResults() will handle fetching LaTeX from backend if available
            await loadJobResults();
          }
        } catch (error) {
          // Backend returned 404 or error, show not found
          const errorMessage = error instanceof Error ? error.message : 'Failed to load job';
          toast.error(errorMessage);
          setJobStatus(null);
        }
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to load job';
      toast.error(errorMessage);
      setJobStatus(null);
    } finally {
      setIsLoading(false);
    }
  }, [jobId, loadJobResults]);

  useEffect(() => {
    loadJobData();

    // Check if we should poll - only poll for pending/processing jobs
    const storedJob = getStoredJob(jobId);
    const shouldPoll = !storedJob || (storedJob.status !== 'completed' && storedJob.status !== 'failed');

    if (!shouldPoll) {
      // Job is already completed/failed, no need to poll
      return;
    }

    // Poll for status updates if job is not completed/failed
    const interval = setInterval(async () => {
      try {
        const status = await getJobStatus(jobId);
        setJobStatus(status);

        // Update localStorage
        updateJobStatus(
          jobId,
          status.status,
          status.company_name,
          status.completed_at,
          status.error_message
        );

        // If job completed, stop polling and load results
        if (status.status === 'completed') {
          clearInterval(interval);
          await loadJobResults();

          // Show notification
          if (status.company_name) {
            showJobCompleteNotification(status.company_name, jobId, isTabFocused());
          }
        } else if (status.status === 'failed') {
          clearInterval(interval);
          // Always try to load results for failed jobs
          // loadJobResults() will handle fetching LaTeX from backend if available
          await loadJobResults();
          // Log full error details to frontend console
          console.group(`%c[Job ${jobId}] Optimization Failed`, 'color: red; font-weight: bold; font-size: 14px;');
          console.error('Error Message:', status.error_message || 'Unknown error');
          if (status.company_name) {
            console.log('Company:', status.company_name);
          }
          if (status.completed_at) {
            console.log('Failed At:', status.completed_at);
          }
          if (status.result?.error_details) {
            console.group('Error Details:');
            console.log('Iterations:', status.result.error_details.iterations);
            console.log('Optimized LaTeX Available:', status.result.error_details.optimized_latex_available);
            console.log('Original LaTeX Length:', status.result.error_details.original_latex_length, 'chars');
            console.log('Optimized LaTeX Length:', status.result.error_details.optimized_latex_length, 'chars');
            console.groupEnd();
          }
          console.log('Has LaTeX in Result:', !!status.result?.optimized_latex);
          console.groupEnd();
        }
      } catch (error) {
        // If we get a 404, check if job exists in localStorage
        // If it's completed in localStorage, the backend deleted it (expected behavior)
        const storedJob = getStoredJob(jobId);
        if (storedJob && (storedJob.status === 'completed' || storedJob.status === 'failed')) {
          // Job is in localStorage and completed/failed, backend deleted it - stop polling
          clearInterval(interval);
          console.log(`Job ${jobId} was deleted from backend (expected after completion)`);
        } else {
          // Real error - log it but continue polling
          console.error('Error polling job status:', error);
        }
      }
    }, 60000); // Poll every 60 seconds (1 minute) to reduce Redis reads

    return () => {
      clearInterval(interval);
    };
  }, [jobId, loadJobData, loadJobResults]);


  if (isLoading) {
    return (
      <div className="container mx-auto py-8 max-w-6xl">
        <Skeleton className="h-8 w-64 mb-4" />
        <Skeleton className="h-32 w-full mb-4" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (!jobStatus) {
    return (
      <div className="container mx-auto py-8 max-w-6xl">
        <Card>
          <CardContent className="pt-6">
            <p>Job not found</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-8 max-w-6xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Job Details</h1>
          <p className="text-muted-foreground mt-2">
            {jobStatus.company_name || 'Optimization Job'}
          </p>
        </div>
        <JobStatusBadge status={jobStatus.status} />
      </div>

      <JobStatusView status={jobStatus.status} errorMessage={jobStatus.error_message} />

      {/* Show results if we have LaTeX, even for failed jobs */}
      {optimizedLatex && originalLatex && (
        <JobResultsView
          jobId={jobId}
          originalLatex={originalLatex}
          optimizedLatex={optimizedLatex}
          filename={jobStatus.result?.filename}
          isFailed={jobStatus.status === 'failed'}
        />
      )}

      <Button variant="outline" onClick={() => router.push('/jobs')}>
        Back to Jobs
      </Button>
    </div>
  );
}

