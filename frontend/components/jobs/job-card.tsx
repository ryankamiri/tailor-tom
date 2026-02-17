'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { STATUS_COLORS, STATUS_LABELS } from '@/lib/constants';
import { format } from 'date-fns';
import { cancelJob, deleteJob, JobListItem } from '@/lib/api';
import { useAuth } from '@/contexts/auth-context';
import { toast } from 'sonner';
import { Trash2, X } from 'lucide-react';

export interface JobCardProps {
  job: JobListItem;
  onJobChanged?: () => void;
}

export function JobCard({ job, onJobChanged }: JobCardProps) {
  const { refreshUser } = useAuth();
  const [isCancelling, setIsCancelling] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [timestampText, setTimestampText] = useState<string>('');

  useEffect(() => {
    try {
      const terminal = job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled';
      const timestamp = terminal && job.completed_at ? job.completed_at : job.created_at;

      const date = new Date(timestamp);
      if (isNaN(date.getTime())) {
        throw new Error(`Invalid timestamp: ${timestamp}`);
      }

      const formatted = format(date, 'MMM d, yyyy h:mm a');

      if (job.status === 'completed') {
        setTimestampText(`Completed at ${formatted}`);
      } else if (job.status === 'failed') {
        setTimestampText(`Failed at ${formatted}`);
      } else if (job.status === 'cancelled') {
        setTimestampText(`Cancelled at ${formatted}`);
      } else {
        setTimestampText(`Started at ${formatted}`);
      }
    } catch (error) {
      console.error(`[JobCard ${job.job_id}] Error formatting timestamp:`, error);
      if (job.status === 'completed') {
        setTimestampText('Completed');
      } else if (job.status === 'failed') {
        setTimestampText('Failed');
      } else if (job.status === 'cancelled') {
        setTimestampText('Cancelled');
      } else {
        setTimestampText('Started');
      }
    }
  }, [job.status, job.created_at, job.completed_at, job.job_id]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <CardTitle className="text-lg">
              {job.company_name || 'Unknown Company'}
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
        <div className="flex items-center justify-end gap-2">
          {(job.status === 'pending' || job.status === 'processing') ? (
            <Button
              variant="destructive"
              size="sm"
              onClick={async () => {
                setIsCancelling(true);
                try {
                  await cancelJob(job.job_id);
                  await refreshUser();
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
          {(job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') ? (
            <Button
              variant="destructive"
              size="sm"
              onClick={async () => {
                setIsDeleting(true);
                try {
                  await deleteJob(job.job_id);
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
            <Link href={`/jobs/${job.job_id}`}>View Details</Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
