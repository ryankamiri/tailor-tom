'use client';

import { useEffect, useState, useCallback } from 'react';
import dynamic from 'next/dynamic';
import { listJobs, JobListItem } from '@/lib/api';
import { RequireAuth } from '@/components/layout/require-auth';
import type { JobStatusFilter } from '@/components/jobs/job-list';

const JobList = dynamic(() => import('@/components/jobs/job-list').then(mod => ({ default: mod.JobList })), {
  ssr: false,
  loading: () => (
    <div className="space-y-4">
      <div className="h-8 w-48 animate-pulse bg-muted rounded" />
      <div className="h-10 w-full animate-pulse bg-muted rounded" />
    </div>
  )
});

function JobsContent() {
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<JobStatusFilter>('all');
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  const refreshJobs = useCallback(async (status?: JobStatusFilter) => {
    const filter = status ?? statusFilter;
    setIsLoading(true);
    try {
      const res = await listJobs({
        limit: 20,
        status: filter === 'all' ? undefined : filter,
      });
      setJobs(res.items);
      setNextCursor(res.next_cursor);
    } finally {
      setIsLoading(false);
    }
  }, [statusFilter]);

  const handleFilterChange = useCallback((newFilter: JobStatusFilter) => {
    setStatusFilter(newFilter);
    setNextCursor(null);
    setIsLoading(true);
    listJobs({
      limit: 20,
      status: newFilter === 'all' ? undefined : newFilter,
    }).then((res) => {
      setJobs(res.items);
      setNextCursor(res.next_cursor);
    }).finally(() => setIsLoading(false));
  }, []);

  const loadMore = useCallback(async () => {
    if (!nextCursor || isLoadingMore) return;
    setIsLoadingMore(true);
    try {
      const res = await listJobs({
        limit: 20,
        cursor: nextCursor,
        status: statusFilter === 'all' ? undefined : statusFilter,
      });
      setJobs((prev) => [...prev, ...res.items]);
      setNextCursor(res.next_cursor);
    } finally {
      setIsLoadingMore(false);
    }
  }, [isLoadingMore, nextCursor, statusFilter]);

  useEffect(() => {
    refreshJobs();
  }, [refreshJobs]);

  // Refetch job list when a job completes or fails (notified by JobPollingProvider)
  useEffect(() => {
    const handler = () => refreshJobs();
    window.addEventListener('tailortom:job-status-changed', handler);
    return () => window.removeEventListener('tailortom:job-status-changed', handler);
  }, [refreshJobs]);

  return (
    <div className="container mx-auto py-8 max-w-7xl">
      {isLoading ? (
        <div className="space-y-4">
          <div className="h-8 w-48 animate-pulse bg-muted rounded" />
          <div className="h-10 w-full animate-pulse bg-muted rounded" />
        </div>
      ) : (
        <JobList
          jobs={jobs}
          statusFilter={statusFilter}
          onStatusFilterChange={handleFilterChange}
          onJobsChange={() => refreshJobs()}
          hasMore={!!nextCursor}
          onLoadMore={loadMore}
          isLoadingMore={isLoadingMore}
        />
      )}
    </div>
  );
}

export default function JobsPage() {
  return (
    <RequireAuth>
      <JobsContent />
    </RequireAuth>
  );
}
