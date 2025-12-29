'use client';

import { useState } from 'react';
import dynamic from 'next/dynamic';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs';
import { StoredJob } from '../../lib/storage';
import { Button } from '../ui/button';
import Link from 'next/link';
import { Plus } from 'lucide-react';

// Dynamically import JobCard with SSR disabled to avoid hydration issues
const JobCard = dynamic(() => import('./job-card').then(mod => ({ default: mod.JobCard })), {
  ssr: false,
  loading: () => <div className="h-32 w-full animate-pulse bg-muted rounded-lg" />
});

export interface JobListProps {
  jobs: StoredJob[];
  onJobsChange?: () => void;
}

export function JobList({ jobs, onJobsChange }: JobListProps) {
  const [filter, setFilter] = useState<string>('all');

  const handleJobChanged = () => {
    // Notify parent component to refresh jobs list
    onJobsChange?.();
  };

  const filteredJobs = jobs.filter((job) => {
    if (filter === 'all') return true;
    return job.status === filter;
  });

  const pendingCount = jobs.filter((j) => j.status === 'pending').length;
  const processingCount = jobs.filter((j) => j.status === 'processing').length;
  const completedCount = jobs.filter((j) => j.status === 'completed').length;
  const failedCount = jobs.filter((j) => j.status === 'failed').length;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Your Jobs</h2>
        <Button asChild>
          <Link href="/jobs/new">
            <Plus className="mr-2 h-4 w-4" />
            New Job
          </Link>
        </Button>
      </div>

      <Tabs value={filter} onValueChange={setFilter}>
        <TabsList>
          <TabsTrigger value="all">
            All ({jobs.length})
          </TabsTrigger>
          <TabsTrigger value="pending">
            Pending ({pendingCount})
          </TabsTrigger>
          <TabsTrigger value="processing">
            Processing ({processingCount})
          </TabsTrigger>
          <TabsTrigger value="completed">
            Completed ({completedCount})
          </TabsTrigger>
          <TabsTrigger value="failed">
            Failed ({failedCount})
          </TabsTrigger>
        </TabsList>

        <TabsContent value={filter} className="space-y-4 mt-4">
          {filteredJobs.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <p className="text-lg mb-2">No jobs found</p>
              <p className="text-sm mb-4">
                {filter === 'all'
                  ? 'Create your first optimization job to get started.'
                  : `No ${filter} jobs.`}
              </p>
              {filter === 'all' && (
                <Button asChild>
                  <Link href="/jobs/new">Create New Job</Link>
                </Button>
              )}
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {filteredJobs.map((job) => (
                <JobCard key={job.jobId} job={job} onJobChanged={handleJobChanged} />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

