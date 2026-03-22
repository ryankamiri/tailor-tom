'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { getJobStatus, getJobLatex, createOptimizationJob, JobStatus, compileLatexToPdf } from '@/lib/api';
import { type TargetPages } from '@/lib/constants';
import { showJobCompleteNotification, showJobFailedNotification } from '@/lib/notifications';
import { JobStatusBadge } from '@/components/jobs/job-status-badge';
import { JobStatusView } from '@/components/jobs/job-status-view';
import { JobResultsView } from '@/components/jobs/job-results-view';
import { RequireAuth } from '@/components/layout/require-auth';
import { useAuth } from '@/contexts/auth-context';
import { toast } from 'sonner';
import { Download } from 'lucide-react';

function JobDetailsContent() {
  const params = useParams();
  const router = useRouter();
  const jobId = params.jobId as string;

  const { user } = useAuth();

  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [originalLatex, setOriginalLatex] = useState<string>('');
  const [optimizedLatex, setOptimizedLatex] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);
  const [isDownloading, setIsDownloading] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);

  const loadJobResults = useCallback(async (status: JobStatus) => {
    try {
      if (status.result?.optimized_latex && status.result.optimized_latex.length > 0) {
        setOptimizedLatex(status.result.optimized_latex);
        return;
      }
      // Fetch latex for completed or failed (failed may have partial output); don't fetch for cancelled.
      if (status.status === 'completed' || status.status === 'failed') {
        const latexData = await getJobLatex(jobId);
        setOptimizedLatex(latexData.latex);
      }
    } catch (error) {
      console.error(`Failed to load results for job ${jobId}:`, error);
    }
  }, [jobId]);

  const loadJobData = useCallback(async () => {
    try {
      const status = await getJobStatus(jobId);
      setJobStatus(status);
      setOriginalLatex(status.original_latex ?? '');

      if (status.status === 'completed' || status.status === 'failed' || status.status === 'cancelled') {
        await loadJobResults(status);
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
  }, [loadJobData]);

  // Refetch when global poller detects this job completed/failed (so UI updates without waiting for local poll)
  useEffect(() => {
    const handler = (e: CustomEvent<{ jobId: string; status: string }>) => {
      if (e.detail?.jobId === jobId) loadJobData();
    };
    window.addEventListener('tailortom:job-status-changed', handler as EventListener);
    return () => window.removeEventListener('tailortom:job-status-changed', handler as EventListener);
  }, [jobId, loadJobData]);

  useEffect(() => {
    const terminal = jobStatus?.status === 'completed' || jobStatus?.status === 'failed' || jobStatus?.status === 'cancelled';
    if (terminal) return;

    const interval = setInterval(async () => {
      try {
        const status = await getJobStatus(jobId);
        setJobStatus(status);

        if (status.status === 'completed') {
          clearInterval(interval);
          await loadJobResults(status);
          if (status.company_name) showJobCompleteNotification(status.company_name, jobId);
        } else if (status.status === 'failed') {
          clearInterval(interval);
          await loadJobResults(status);
          showJobFailedNotification(status.company_name || 'Your', jobId, status.error_message);
        } else if (status.status === 'cancelled') {
          clearInterval(interval);
          await loadJobResults(status);
        }
      } catch (error) {
        console.error('Error polling job status:', error);
      }
    }, 60000);

    return () => clearInterval(interval);
  }, [jobId, jobStatus?.status, loadJobResults]);

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

  const handleDownload = async () => {
    if (!optimizedLatex) {
      toast.error('No optimized resume available to download');
      return;
    }

    setIsDownloading(true);
    try {
      const downloadFilename = jobStatus.result?.filename || 'optimized_resume.pdf';
      const pdfBlob = await compileLatexToPdf(optimizedLatex, downloadFilename);

      const url = URL.createObjectURL(pdfBlob);
      const a = document.createElement('a');
      a.href = url;
      a.download = downloadFilename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      toast.success('PDF downloaded successfully!');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to compile PDF';
      toast.error(errorMessage);
    } finally {
      setIsDownloading(false);
    }
  };

  const handleRetry = async () => {
    if (!user?.resume_latex) {
      toast.error('No resume on file. Please upload a resume in Settings first.');
      return;
    }
    setIsRetrying(true);
    try {
      await createOptimizationJob({
        resume_latex: user.resume_latex,
        job_description: jobStatus!.job_description!,
        target_pages: (user.target_pages ?? 1) as TargetPages,
        max_iterations: user.max_iterations ?? 3,
        first_name: user.first_name ?? '',
        last_name: user.last_name ?? '',
        company_name: jobStatus!.company_name ?? '',
      });
      toast.success('Job retried — check your jobs list.');
      router.push('/jobs');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to retry job');
    } finally {
      setIsRetrying(false);
    }
  };

  return (
    <div className="container mx-auto py-8 max-w-6xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Job Details</h1>
          <p className="text-muted-foreground mt-2">{jobStatus.company_name || 'Optimization Job'}</p>
        </div>
        <div className="flex items-center gap-3">
          {['failed', 'completed', 'cancelled'].includes(jobStatus.status) && (
            <Button
              variant="outline"
              size="sm"
              disabled={isRetrying || !user?.resume_latex}
              onClick={handleRetry}
            >
              {isRetrying ? 'Retrying…' : 'Retry'}
            </Button>
          )}
          {jobStatus.job_description && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                navigator.clipboard.writeText(jobStatus.job_description!);
                toast.success('Job description copied');
              }}
            >
              Copy Job Description
            </Button>
          )}
          {optimizedLatex && (
            <Button onClick={handleDownload} disabled={isDownloading} variant="default" className="gap-2">
              <Download className="h-4 w-4" />
              {isDownloading ? 'Compiling...' : 'Download Optimized Resume'}
            </Button>
          )}
          <JobStatusBadge status={jobStatus.status} />
        </div>
      </div>

      <JobStatusView status={jobStatus.status} errorMessage={jobStatus.error_message} />

      {optimizedLatex && (
        <JobResultsView
          originalLatex={originalLatex || optimizedLatex}
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

export default function JobDetailsPage() {
  return (
    <RequireAuth>
      <JobDetailsContent />
    </RequireAuth>
  );
}
