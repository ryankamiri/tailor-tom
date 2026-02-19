'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  listAdminUserJobs,
  getAdminUserSummary,
  type AdminUserJobListItem,
  type AdminUserSummaryResponse,
} from '@/lib/api';
import { formatLocalDateSafe } from '@/lib/formatting';
import { JobStatusBadge } from '@/components/jobs/job-status-badge';
import { RequireAuth } from '@/components/layout/require-auth';

const STATUS_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'pending', label: 'Pending' },
  { value: 'processing', label: 'Processing' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'cancelled', label: 'Cancelled' },
] as const;

function AdminUserJobsContent() {
  const params = useParams();
  const router = useRouter();
  const userId = typeof params.userId === 'string' ? params.userId : '';
  const [summary, setSummary] = useState<AdminUserSummaryResponse | null>(null);
  const [items, setItems] = useState<AdminUserJobListItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchList = useCallback(
    async (cursor?: string | null, append = false) => {
      if (!userId) return;
      try {
        if (append) setLoadingMore(true);
        else setLoading(true);
        setError(null);
        const res = await listAdminUserJobs(userId, {
          limit: 20,
          cursor: cursor ?? undefined,
          status: statusFilter === 'all' ? undefined : [statusFilter],
          search: search || undefined,
        });
        if (append) {
          setItems((prev) => [...prev, ...res.items]);
        } else {
          setItems(res.items);
        }
        setNextCursor(res.next_cursor);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load jobs');
        if (!append) setItems([]);
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [userId, statusFilter, search]
  );

  useEffect(() => {
    if (!userId) {
      setError('Invalid user');
      setLoading(false);
      return;
    }
    getAdminUserSummary(userId)
      .then(setSummary)
      .catch(() => setSummary(null));
  }, [userId]);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setSearch(searchInput.trim());
  };

  const handleCopyJobId = (jobId: string) => {
    navigator.clipboard.writeText(jobId);
  };

  return (
    <RequireAuth requireAdmin>
      <div className="container max-w-4xl py-6 space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Link href="/admin" className="text-muted-foreground hover:underline text-sm">
            Admin
          </Link>
          <span className="text-muted-foreground">/</span>
          <Link href="/admin" className="text-muted-foreground hover:underline text-sm">
            Users
          </Link>
          <span className="text-muted-foreground">/</span>
          <span className="text-sm font-medium">Jobs</span>
        </div>

        {summary && (
          <div className="rounded-lg border bg-card p-4">
            <p className="font-medium">
              {summary.first_name} {summary.last_name}
            </p>
            <p className="text-sm text-muted-foreground">{summary.email}</p>
            <p className="text-xs text-muted-foreground mt-1">User ID: {summary.user_id}</p>
          </div>
        )}

        <div className="flex flex-wrap gap-4 items-center">
          <form onSubmit={handleSearchSubmit} className="flex gap-2">
            <Input
              placeholder="Search job ID or company..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="w-48"
            />
            <Button type="submit" variant="secondary" size="sm">
              Search
            </Button>
          </form>
          <div className="flex gap-1 flex-wrap">
            {STATUS_OPTIONS.map((opt) => (
              <Button
                key={opt.value}
                variant={statusFilter === opt.value ? 'default' : 'outline'}
                size="sm"
                onClick={() => setStatusFilter(opt.value)}
              >
                {opt.label}
              </Button>
            ))}
          </div>
        </div>

        {error && (
          <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        {loading && items.length === 0 ? (
          <div className="text-muted-foreground py-8">Loading jobs…</div>
        ) : items.length === 0 ? (
          <div className="text-muted-foreground py-8">No jobs found.</div>
        ) : (
          <>
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="px-2 py-2 text-left font-medium">Job ID</th>
                    <th className="px-2 py-2 text-left font-medium">Company</th>
                    <th className="px-2 py-2 text-left font-medium">Status</th>
                    <th className="px-2 py-2 text-left font-medium">Created</th>
                    <th className="px-2 py-2 text-left font-medium">Completed</th>
                    <th className="px-2 py-2 font-medium w-[120px]">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((j) => (
                    <tr key={j.job_id} className="border-b border-border/50 hover:bg-muted/30">
                      <td className="px-2 py-2">
                        <button
                          type="button"
                          onClick={() => handleCopyJobId(j.job_id)}
                          className="font-mono text-xs truncate max-w-[140px] block hover:underline"
                          title="Copy"
                        >
                          {j.job_id}
                        </button>
                      </td>
                      <td className="px-2 py-2 truncate max-w-[160px]">{j.company_name || '—'}</td>
                      <td className="px-2 py-2">
                        <JobStatusBadge status={j.status} />
                      </td>
                      <td className="px-2 py-2 text-muted-foreground">
                        {formatLocalDateSafe(j.created_at, '—')}
                      </td>
                      <td className="px-2 py-2 text-muted-foreground">
                        {j.completed_at ? formatLocalDateSafe(j.completed_at, '—') : '—'}
                      </td>
                      <td className="px-2 py-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => router.push(`/admin/users/${userId}/jobs/${j.job_id}`)}
                        >
                          Open Detail
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {nextCursor && (
              <Button
                variant="outline"
                size="sm"
                disabled={loadingMore}
                onClick={() => fetchList(nextCursor, true)}
              >
                {loadingMore ? 'Loading…' : 'Load more'}
              </Button>
            )}
          </>
        )}
      </div>
    </RequireAuth>
  );
}

export default function AdminUserJobsPage() {
  return <AdminUserJobsContent />;
}
