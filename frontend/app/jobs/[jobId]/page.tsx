'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Card, CardContent } from '../../../components/ui/card';
import { Button } from '../../../components/ui/button';
import { Skeleton } from '../../../components/ui/skeleton';
import { getJobStatus, getJobLatex, JobStatus, deleteJob } from '../../../lib/api';
import { updateJobStatus, storeOptimizedLatex, getOptimizedLatex, getStoredJob, getJobFilename } from '../../../lib/storage';
import { showJobCompleteNotification, isTabFocused } from '../../../lib/notifications';
import { JobStatusBadge } from '../../../components/jobs/job-status-badge';
import { JobStatusView } from '../../../components/jobs/job-status-view';
import { JobResultsView } from '../../../components/jobs/job-results-view';
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
        // Fetch from backend and store in localStorage
        const latexData = await getJobLatex(jobId);
        setOptimizedLatex(latexData.latex);
        
        // Store in localStorage
        storeOptimizedLatex(jobId, latexData.latex, latexData.filename);
        
        // Delete job from backend after successfully storing in localStorage
        // This saves backend memory since localStorage is now the source of truth
        try {
          await deleteJob(jobId);
        } catch (error) {
          console.warn(`Failed to delete job ${jobId} from backend:`, error);
          // Don't show error to user - it's not critical, just means backend keeps the data longer
        }
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to load job results';
      toast.error(errorMessage);
    }
  }, [jobId]);

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
          result: storedJob.status === 'completed' && filename && optimizedLatex
            ? { optimized_latex: optimizedLatex, filename } 
            : null,
        };
        setJobStatus(status);
        
        // Set original LaTeX from stored job
        setOriginalLatex(storedJob.originalLatex);

        if (status.status === 'completed') {
          await loadJobResults();
        }
      } else {
        // Job not in localStorage, try to fetch from backend
        try {
          const status = await getJobStatus(jobId);
          setJobStatus(status);

          if (status.status === 'completed') {
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
    }, 30000); // Poll every 30 seconds

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

      {jobStatus.status === 'completed' && optimizedLatex && originalLatex && (
        <JobResultsView
          jobId={jobId}
          originalLatex={originalLatex}
          optimizedLatex={optimizedLatex}
          filename={jobStatus.result?.filename}
        />
      )}

      <Button variant="outline" onClick={() => router.push('/jobs')}>
        Back to Jobs
      </Button>
    </div>
  );
}

