'use client';

import { useEffect, useRef } from 'react';
import { listJobs, getJobStatus } from '@/lib/api';
import { showJobCompleteNotification, showJobFailedNotification } from '@/lib/notifications';
import { useAuth } from '@/contexts/auth-context';
import { JOB_POLL_INTERVAL_SECONDS } from '@/lib/constants';

export function JobPollingProvider() {
  const { user, isAuthenticated, refreshUser } = useAuth();
  const previousStatusRef = useRef<Map<string, string>>(new Map());

  useEffect(() => {
    if (!isAuthenticated) return;
    if ((user?.active_jobs_count ?? 0) <= 0) return;

    const pollJobStatuses = async () => {
      try {
        const { items: activeJobs } = await listJobs({
          limit: 100,
          status: ['pending', 'processing'],
        });
        const seen = new Set<string>();

        for (const job of activeJobs) {
          seen.add(job.job_id);
          previousStatusRef.current.set(job.job_id, job.status);
        }

        const prevEntries = Array.from(previousStatusRef.current.entries());
        for (const [jobId, oldStatus] of prevEntries) {
          if (seen.has(jobId)) continue;

          try {
            const status = await getJobStatus(jobId);
            if (status.status === 'completed' && oldStatus !== 'completed') {
              showJobCompleteNotification(status.company_name || 'Your', jobId);
              previousStatusRef.current.delete(jobId);
              await refreshUser();
              if (typeof window !== 'undefined') {
                window.dispatchEvent(new CustomEvent('tailortom:job-status-changed', { detail: { jobId, status: 'completed' } }));
              }
            } else if (status.status === 'failed' && oldStatus !== 'failed') {
              showJobFailedNotification(status.company_name || 'Your', jobId, status.error_message || null);
              previousStatusRef.current.delete(jobId);
              await refreshUser();
              if (typeof window !== 'undefined') {
                window.dispatchEvent(new CustomEvent('tailortom:job-status-changed', { detail: { jobId, status: 'failed' } }));
              }
            } else if (status.status === 'cancelled') {
              previousStatusRef.current.delete(jobId);
              await refreshUser();
              if (typeof window !== 'undefined') {
                window.dispatchEvent(new CustomEvent('tailortom:job-status-changed', { detail: { jobId, status: 'cancelled' } }));
              }
            } else {
              previousStatusRef.current.delete(jobId);
            }
          } catch (error) {
            console.error(`[JobPollingProvider] Error checking status for job ${jobId}:`, error);
          }
        }
      } catch (error) {
        console.error('[JobPollingProvider] Error polling job statuses:', error);
      }
    };

    pollJobStatuses();
    const interval = setInterval(pollJobStatuses, JOB_POLL_INTERVAL_SECONDS * 1000);
    return () => clearInterval(interval);
  }, [isAuthenticated, user?.active_jobs_count, refreshUser]);

  return null;
}
