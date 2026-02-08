'use client';

import { useEffect } from 'react';
import { getStoredJobs, updateJobStatus } from '@/lib/storage';
import { getJobStatus } from '@/lib/api';
import { showJobCompleteNotification, showJobFailedNotification } from '@/lib/notifications';

/**
 * Global job polling provider that runs on all pages.
 * Polls for pending/processing jobs and shows notifications when they complete.
 * 
 * Optimizations:
 * - Polls every 60 seconds (1 minute) instead of 10 seconds to reduce Redis reads
 * - Automatically stops polling jobs that complete or fail (filtered out on next poll)
 */
export function JobPollingProvider() {
  useEffect(() => {
    const pollJobStatuses = async () => {
      const jobs = getStoredJobs();
      
      // Only poll jobs that are pending or processing
      // Completed/failed jobs are automatically excluded, so polling stops for them
      const jobsToPoll = jobs.filter(
        (job) => job.status === 'pending' || job.status === 'processing'
      );

      if (jobsToPoll.length === 0) {
        return; // No jobs to poll - polling effectively stops
      }

      // Poll each job in parallel
      await Promise.allSettled(
        jobsToPoll.map(async (job) => {
          try {
            const status = await getJobStatus(job.jobId);
            
            // Update localStorage if status changed
            if (status.status !== job.status) {
              updateJobStatus(
                job.jobId,
                status.status,
                status.company_name,
                status.completed_at,
                status.error_message
              );
              
              // Show notification when job completes or fails
              if (status.status === 'completed') {
                showJobCompleteNotification(
                  status.company_name || 'Your',
                  job.jobId,
                );
              } else if (status.status === 'failed') {
                showJobFailedNotification(
                  status.company_name || 'Your',
                  job.jobId,
                  status.error_message || null,
                );
              }
            }
          } catch (error) {
            // Check if it's a 404 (job not found)
            const errorMessage = error instanceof Error ? error.message : String(error);
            const isNotFound = errorMessage.includes('(404)') || errorMessage.toLowerCase().includes('not found');
            
            if (isNotFound) {
              // Job doesn't exist on backend, mark as failed with server error
              console.warn(`[JobPollingProvider] Job ${job.jobId} not found on backend (404), marking as failed`);
              updateJobStatus(
                job.jobId,
                'failed',
                job.companyName,
                new Date().toISOString(),
                'Internal server error: Job was deleted or lost on the server'
              );
            } else {
              // Other errors, just log but don't change status
              console.error(`[JobPollingProvider] Error polling job ${job.jobId}:`, error);
            }
          }
        })
      );
    };

    // Poll immediately on mount
    pollJobStatuses();

    // Set up interval to poll every 60 seconds (1 minute)
    const interval = setInterval(pollJobStatuses, 60000);

    return () => {
      clearInterval(interval);
    };
  }, []); // Run once on mount

  return null; // This component doesn't render anything
}

