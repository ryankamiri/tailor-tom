'use client';

import dynamic from 'next/dynamic';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import Link from 'next/link';
import { Plus } from 'lucide-react';
import { DailyLimitBadge } from './daily-limit-badge';
import { useAuth } from '@/contexts/auth-context';
import { JobListItem } from '@/lib/api';

const JobCard = dynamic(() => import('./job-card').then(mod => ({ default: mod.JobCard })), {
  ssr: false,
  loading: () => <div className="h-32 w-full animate-pulse bg-muted rounded-lg" />
});

export type JobStatusFilter = 'all' | 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';

export interface JobListProps {
  jobs: JobListItem[];
  statusFilter: JobStatusFilter;
  onStatusFilterChange: (filter: JobStatusFilter) => void;
  onJobsChange?: () => void;
  isLoadingMore?: boolean;
  hasMore?: boolean;
  onLoadMore?: () => void;
}

export function JobList({
  jobs,
  statusFilter,
  onStatusFilterChange,
  onJobsChange,
  isLoadingMore = false,
  hasMore = false,
  onLoadMore,
}: JobListProps) {
  const { user } = useAuth();
  const canCreateByDailyLimit = (user?.daily_limit_remaining ?? 0) > 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h2 className="text-2xl font-bold">Your Jobs</h2>
          <DailyLimitBadge />
        </div>
        <Button asChild disabled={!canCreateByDailyLimit}>
          <Link href="/jobs/new">
            <Plus className="mr-2 h-4 w-4" />
            New Job
          </Link>
        </Button>
      </div>

      <Tabs value={statusFilter} onValueChange={(v) => onStatusFilterChange(v as JobStatusFilter)}>
        <TabsList>
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger value="pending">Pending</TabsTrigger>
          <TabsTrigger value="processing">Processing</TabsTrigger>
          <TabsTrigger value="completed">Completed</TabsTrigger>
          <TabsTrigger value="failed">Failed</TabsTrigger>
          <TabsTrigger value="cancelled">Cancelled</TabsTrigger>
        </TabsList>

        <TabsContent value={statusFilter} className="space-y-4 mt-4">
          {jobs.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <p className="text-lg mb-2">No jobs found</p>
              <p className="text-sm mb-4">
                {statusFilter === 'all' ? 'Create your first optimization job to get started.' : `No ${statusFilter} jobs.`}
              </p>
              {statusFilter === 'all' && (
                <Button asChild>
                  <Link href="/jobs/new">Create New Job</Link>
                </Button>
              )}
            </div>
          ) : (
            <>
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {jobs.map((job) => (
                  <JobCard key={job.job_id} job={job} onJobChanged={onJobsChange} />
                ))}
              </div>
              {hasMore && onLoadMore && (
                <div className="flex justify-center pt-2">
                  <Button variant="outline" onClick={onLoadMore} disabled={isLoadingMore}>
                    {isLoadingMore ? 'Loading...' : 'Load More'}
                  </Button>
                </div>
              )}
            </>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
