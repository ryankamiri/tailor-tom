'use client';

import { useState, useEffect } from 'react';
import dynamic from 'next/dynamic';
import { getStoredJobs, cleanupOldJobs, StoredJob } from '@/lib/storage';

// Dynamically import JobList with SSR disabled to avoid hydration issues
// JobList depends on localStorage which is not available on the server
const JobList = dynamic(() => import('@/components/jobs/job-list').then(mod => ({ default: mod.JobList })), {
  ssr: false,
  loading: () => (
    <div className="space-y-4">
      <div className="h-8 w-48 animate-pulse bg-muted rounded" />
      <div className="h-10 w-full animate-pulse bg-muted rounded" />
    </div>
  )
});

export default function JobsPage() {
  // Use lazy initializer to load jobs from localStorage on mount
  const [jobs, setJobs] = useState<StoredJob[]>(() => {
    cleanupOldJobs();
    return getStoredJobs();
  });

  // Refresh jobs from localStorage
  const refreshJobs = () => {
    cleanupOldJobs();
    setJobs(getStoredJobs());
  };

  // Refresh jobs periodically and on focus
  useEffect(() => {

    // Refresh on window focus
    window.addEventListener('focus', refreshJobs);

    // Refresh every 2 seconds to catch updates from global polling
    const interval = setInterval(refreshJobs, 2000);

    return () => {
      window.removeEventListener('focus', refreshJobs);
      clearInterval(interval);
    };
  }, []);

  const handleJobsChange = () => {
    refreshJobs();
  };

  return (
    <div className="container mx-auto py-8 max-w-7xl">
      <JobList jobs={jobs} onJobsChange={handleJobsChange} />
    </div>
  );
}

