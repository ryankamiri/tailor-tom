'use client';

import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import type { AdminUserSummaryResponse } from '@/lib/api';
import { formatLocalDateSafe, formatUsdCompact } from '@/lib/formatting';

export interface AdminUserDetailDrawerProps {
  open: boolean;
  onClose: () => void;
  summary: AdminUserSummaryResponse | null;
  loading: boolean;
}

export function AdminUserDetailDrawer({
  open,
  onClose,
  summary,
  loading,
}: AdminUserDetailDrawerProps) {
  const router = useRouter();

  if (!open) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/50"
        aria-hidden
        onClick={onClose}
      />
      <div
        className="fixed right-0 top-0 z-50 h-full w-full max-w-md overflow-y-auto border-l bg-background shadow-lg sm:max-w-lg"
        role="dialog"
        aria-label="User detail"
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b bg-background px-4 py-3">
          <h2 className="text-lg font-semibold">User detail</h2>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
        <div className="p-4 space-y-6">
          {loading && (
            <>
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-32 w-full" />
            </>
          )}
          {!loading && summary && (
            <>
              <section>
                <h3 className="text-sm font-medium text-muted-foreground mb-1">Profile</h3>
                <p className="font-medium">
                  {summary.first_name} {summary.last_name}
                </p>
                <p className="text-sm text-muted-foreground">{summary.email}</p>
                {summary.is_admin && (
                  <span className="inline-block mt-1 text-xs font-medium text-amber-600 dark:text-amber-400">
                    Admin
                  </span>
                )}
              </section>
              <section>
                <h3 className="text-sm font-medium text-muted-foreground mb-1">Quota</h3>
                <p className="text-sm">
                  Daily used: {summary.quota.daily_quota_used} · Active jobs: {summary.quota.active_jobs_count}
                </p>
              </section>
              <section>
                <h3 className="text-sm font-medium text-muted-foreground mb-1">Job summary</h3>
                <p className="text-sm">
                  Completed: {summary.job_summary.completed_count} · Failed: {summary.job_summary.failed_count}
                </p>
                {summary.job_summary.last_job_at && (
                  <p className="text-sm text-muted-foreground">
                    Last job: {formatLocalDateSafe(summary.job_summary.last_job_at)}
                  </p>
                )}
              </section>
              <section>
                <h3 className="text-sm font-medium text-muted-foreground mb-1">Cost</h3>
                <p className="text-sm">
                  Month: {formatUsdCompact(summary.cost_summary.month_cost_usd)} · Lifetime:{' '}
                  {formatUsdCompact(summary.cost_summary.total_cost_usd)}
                </p>
              </section>
              {summary.recent_jobs.length > 0 && (
                <section>
                  <h3 className="text-sm font-medium text-muted-foreground mb-2">Recent jobs</h3>
                  <ul className="space-y-1 text-sm">
                    {summary.recent_jobs.map((j) => (
                      <li
                        key={j.job_id}
                        className="flex justify-between items-center py-1 border-b border-border/50"
                      >
                        <span className="truncate">{j.company_name || j.job_id}</span>
                        <span className="text-muted-foreground shrink-0 ml-2">{j.status}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              {summary.has_resume && (
                <div className="pt-2">
                  <Button
                    variant="default"
                    size="sm"
                    onClick={() => {
                      onClose();
                      router.push(`/admin/resume/${summary.user_id}`);
                    }}
                  >
                    View Resume
                  </Button>
                </div>
              )}
            </>
          )}
          {!loading && !summary && (
            <p className="text-sm text-muted-foreground">Could not load user summary.</p>
          )}
        </div>
      </div>
    </>
  );
}
