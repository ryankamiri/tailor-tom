'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import {
  getAdminUserJobStatus,
  getAdminUserJobLatex,
  compileLatexToPdf,
  type JobStatus,
} from '@/lib/api';
import { JobStatusBadge } from '@/components/jobs/job-status-badge';
import { JobStatusView } from '@/components/jobs/job-status-view';
import { JobResultsView } from '@/components/jobs/job-results-view';
import { RequireAuth } from '@/components/layout/require-auth';
import { toast } from 'sonner';
import { Download } from 'lucide-react';

function AdminJobDetailContent() {
  const params = useParams();
  const userId = typeof params.userId === 'string' ? params.userId : '';
  const jobId = typeof params.jobId === 'string' ? params.jobId : '';

  const [jobStatus, setJobStatus] = useState<(JobStatus & { owner_user_id?: string }) | null>(null);
  const [originalLatex, setOriginalLatex] = useState('');
  const [optimizedLatex, setOptimizedLatex] = useState('');
  const [loading, setLoading] = useState(true);
  const [isDownloading, setIsDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadJobData = useCallback(async () => {
    if (!userId || !jobId) return;
    try {
      setError(null);
      const status = await getAdminUserJobStatus(userId, jobId);
      setJobStatus(status);
      setOriginalLatex(status.original_latex ?? '');

      if (status.status === 'completed' || status.status === 'failed') {
        try {
          const latexData = await getAdminUserJobLatex(userId, jobId);
          setOptimizedLatex(latexData.latex);
        } catch {
          if (status.result?.optimized_latex?.length) {
            setOptimizedLatex(status.result.optimized_latex);
          }
        }
      } else if (status.status === 'cancelled' && status.result?.optimized_latex?.length) {
        setOptimizedLatex(status.result.optimized_latex);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load job');
      setJobStatus(null);
    } finally {
      setLoading(false);
    }
  }, [userId, jobId]);

  useEffect(() => {
    loadJobData();
  }, [loadJobData]);

  if (loading && !jobStatus) {
    return (
      <div className="container mx-auto py-8 max-w-6xl">
        <Skeleton className="h-8 w-64 mb-4" />
        <Skeleton className="h-32 w-full mb-4" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (error || !jobStatus) {
    return (
      <div className="container mx-auto py-8 max-w-6xl space-y-4">
        <p className="text-destructive">{error || 'Job not found'}</p>
        <div className="flex gap-2">
          <Button variant="outline" asChild>
            <Link href={`/admin/users/${userId}/jobs`}>Back to user jobs</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href="/admin">Back to admin</Link>
          </Button>
        </div>
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
      toast.success('PDF downloaded');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to compile PDF');
    } finally {
      setIsDownloading(false);
    }
  };

  return (
    <div className="container mx-auto py-8 max-w-6xl space-y-6">
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <Link href="/admin" className="hover:underline">
          Admin
        </Link>
        <span>/</span>
        <Link href="/admin" className="hover:underline">
          Users
        </Link>
        <span>/</span>
        <Link href={`/admin/users/${userId}/jobs`} className="hover:underline">
          Jobs
        </Link>
        <span>/</span>
        <span className="font-medium text-foreground">{jobId}</span>
      </div>

      <div className="rounded-md border border-amber-500/50 bg-amber-500/5 px-3 py-2 text-sm">
        Read-only admin view. You cannot cancel or delete this job.
      </div>

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Job Details</h1>
          <p className="text-muted-foreground mt-2">{jobStatus.company_name || 'Optimization Job'}</p>
        </div>
        <div className="flex items-center gap-3">
          {optimizedLatex && (
            <Button onClick={handleDownload} disabled={isDownloading} variant="default" className="gap-2">
              <Download className="h-4 w-4" />
              {isDownloading ? 'Compiling…' : 'Download PDF'}
            </Button>
          )}
          <JobStatusBadge status={jobStatus.status} />
        </div>
      </div>

      <JobStatusView status={jobStatus.status} errorMessage={jobStatus.error_message} />

      {jobStatus.error_log && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-muted-foreground">Error Log</h2>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                navigator.clipboard.writeText(jobStatus.error_log ?? '');
                toast.success('Copied to clipboard');
              }}
            >
              Copy
            </Button>
          </div>
          <pre className="rounded-md border bg-muted px-4 py-3 text-xs font-mono overflow-x-auto max-h-[60vh] overflow-y-auto whitespace-pre-wrap break-words">
            {jobStatus.error_log}
          </pre>
        </div>
      )}

      {optimizedLatex && (
        <JobResultsView
          originalLatex={originalLatex || optimizedLatex}
          optimizedLatex={optimizedLatex}
          filename={jobStatus.result?.filename}
          isFailed={jobStatus.status === 'failed'}
        />
      )}

      <div className="flex gap-2">
        <Button variant="outline" asChild>
          <Link href={`/admin/users/${userId}/jobs`}>Back to user jobs</Link>
        </Button>
        <Button variant="outline" asChild>
          <Link href="/admin">Back to admin</Link>
        </Button>
      </div>
    </div>
  );
}

export default function AdminJobDetailPage() {
  return (
    <RequireAuth requireAdmin>
      <AdminJobDetailContent />
    </RequireAuth>
  );
}
