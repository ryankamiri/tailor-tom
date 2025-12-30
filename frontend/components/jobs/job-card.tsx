'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { StoredJob } from '@/lib/storage';
import { STATUS_COLORS, STATUS_LABELS } from '@/lib/constants';
import { format } from 'date-fns';
import { cancelJob, deleteJob } from '@/lib/api';
import { updateJobStatus, deleteStoredJob } from '@/lib/storage';
import { toast } from 'sonner';
import { Trash2, X } from 'lucide-react';

export interface JobCardProps {
  job: StoredJob;
  onJobChanged?: () => void;
}

export function JobCard({ job, onJobChanged }: JobCardProps) {
  const [isCancelling, setIsCancelling] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [timestampText, setTimestampText] = useState<string>('');

  useEffect(() => {
    // Compute timestamp
    try {
      // Use completedAt for completed/failed jobs if available, otherwise use createdAt
      const timestamp = (job.status === 'completed' || job.status === 'failed') && job.completedAt
        ? job.completedAt
        : job.createdAt;
      
      // Parse UTC timestamp (backend sends timestamps with 'Z' suffix)
      // Ensure timestamp ends with 'Z' if it doesn't already to indicate UTC
      const utcTimestamp = timestamp.endsWith('Z') ? timestamp : timestamp + 'Z';
      const date = new Date(utcTimestamp);
      
      // Validate date was parsed correctly
      if (isNaN(date.getTime())) {
        throw new Error(`Invalid timestamp: ${timestamp}`);
      }
      
      // Format in user's local timezone
      const formatted = format(date, 'MMM d, yyyy h:mm a');
      
      if (job.status === 'completed') {
        setTimestampText(`Completed at ${formatted}`);
      } else if (job.status === 'failed') {
        setTimestampText(`Failed at ${formatted}`);
      } else {
        setTimestampText(`Started at ${formatted}`);
      }
    } catch (error) {
      console.error(`[JobCard ${job.jobId}] Error formatting timestamp:`, error);
      if (job.status === 'completed') {
        setTimestampText('Completed');
      } else if (job.status === 'failed') {
        setTimestampText('Failed');
      } else {
        setTimestampText('Started');
      }
    }
  }, [job.status, job.createdAt, job.completedAt, job.jobId]);
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <CardTitle className="text-lg">
              {job.companyName || 'Unknown Company'}
            </CardTitle>
            <CardDescription className="text-xs">
              {timestampText || '\u00A0'}
            </CardDescription>
          </div>
          <Badge className={STATUS_COLORS[job.status]}>
            {STATUS_LABELS[job.status]}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-between">
          <div className="text-sm text-muted-foreground">
            Target: {job.targetPages} page{job.targetPages !== 1 ? 's' : ''}
          </div>
          <div className="flex gap-2">
            {(job.status === 'pending' || job.status === 'processing') ? (
              <Button
                variant="destructive"
                size="sm"
                onClick={async () => {
                  setIsCancelling(true);
                  try {
                    await cancelJob(job.jobId);
                    updateJobStatus(job.jobId, 'failed', undefined, new Date().toISOString(), 'Job cancelled by user');
                    toast.success('Job cancelled successfully');
                    onJobChanged?.();
                  } catch (error) {
                    const errorMessage = error instanceof Error ? error.message : 'Failed to cancel job';
                    toast.error(errorMessage);
                  } finally {
                    setIsCancelling(false);
                  }
                }}
                disabled={isCancelling || isDeleting}
              >
                <X className="h-4 w-4 mr-1" />
                {isCancelling ? 'Cancelling...' : 'Cancel'}
              </Button>
            ) : null}
            {(job.status === 'completed' || job.status === 'failed') ? (
              <Button
                variant="destructive"
                size="sm"
                onClick={async () => {
                  setIsDeleting(true);
                  try {
                    // Delete from backend (idempotent - returns 200 even if already deleted)
                    await deleteJob(job.jobId);
                    // Delete from localStorage (our source of truth)
                    deleteStoredJob(job.jobId);
                    toast.success('Job deleted successfully');
                    onJobChanged?.();
                  } catch (error) {
                    const errorMessage = error instanceof Error ? error.message : 'Failed to delete job';
                    toast.error(errorMessage);
                  } finally {
                    setIsDeleting(false);
                  }
                }}
                disabled={isCancelling || isDeleting}
              >
                <Trash2 className="h-4 w-4 mr-1" />
                {isDeleting ? 'Deleting...' : 'Delete'}
              </Button>
            ) : null}
            <Button asChild variant="outline" size="sm">
              <Link href={`/jobs/${job.jobId}`}>View Details</Link>
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
