'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import {
  listAdminAllJobs,
  type AdminAllJobsItem,
} from '@/lib/api';
import { formatLocalDateSafe } from '@/lib/formatting';
import { JobStatusBadge } from '@/components/jobs/job-status-badge';
import { toast } from 'sonner';

const STATUS_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'pending', label: 'Pending' },
  { value: 'processing', label: 'Processing' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'cancelled', label: 'Cancelled' },
] as const;

export function AdminAllJobsPanel() {
  const router = useRouter();

  const [items, setItems] = useState<AdminAllJobsItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');

  const fetchList = useCallback(
    async (cursor?: string | null, append = false) => {
      try {
        if (append) setLoadingMore(true);
        else setLoading(true);
        setError(null);
        const res = await listAdminAllJobs({
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
    [statusFilter, search]
  );

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setSearch(searchInput);
  }

  function handleCopyJobId(jobId: string) {
    navigator.clipboard.writeText(jobId);
    toast.success('Job ID copied');
  }

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
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
        <form onSubmit={handleSearch} className="flex gap-2">
          <Input
            placeholder="Search job ID, company, user…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="h-8 w-64 text-sm"
          />
          <Button type="submit" size="sm" variant="outline">
            Search
          </Button>
          {search && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => { setSearch(''); setSearchInput(''); }}
            >
              Clear
            </Button>
          )}
        </form>
      </div>

      {/* Table */}
      {loading ? (
        <Skeleton className="h-64 w-full" />
      ) : error ? (
        <p className="text-sm text-destructive">{error}</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No jobs found.</p>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-2 py-2 text-left font-medium">Job ID</th>
                <th className="px-2 py-2 text-left font-medium">User</th>
                <th className="px-2 py-2 text-left font-medium">Company</th>
                <th className="px-2 py-2 text-left font-medium">Status</th>
                <th className="px-2 py-2 text-left font-medium">Created</th>
                <th className="px-2 py-2 text-left font-medium">Completed</th>
                <th className="px-2 py-2 font-medium w-[110px]">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((j) => (
                <tr key={j.job_id} className="border-b border-border/50 hover:bg-muted/30">
                  <td className="px-2 py-2">
                    <button
                      type="button"
                      onClick={() => handleCopyJobId(j.job_id)}
                      className="font-mono text-xs truncate max-w-[130px] block hover:underline"
                      title="Click to copy"
                    >
                      {j.job_id}
                    </button>
                  </td>
                  <td className="px-2 py-2">
                    <span className="text-xs text-muted-foreground truncate max-w-[160px] block">
                      {j.user_first_name} {j.user_last_name}
                      <br />
                      <span className="text-[11px]">{j.user_email}</span>
                    </span>
                  </td>
                  <td className="px-2 py-2 truncate max-w-[140px]">{j.company_name || '—'}</td>
                  <td className="px-2 py-2">
                    <JobStatusBadge status={j.status} />
                  </td>
                  <td className="px-2 py-2 text-muted-foreground text-xs">
                    {formatLocalDateSafe(j.created_at, '—')}
                  </td>
                  <td className="px-2 py-2 text-muted-foreground text-xs">
                    {j.completed_at ? formatLocalDateSafe(j.completed_at, '—') : '—'}
                  </td>
                  <td className="px-2 py-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        router.push(`/admin/users/${j.user_id}/jobs/${j.job_id}`)
                      }
                    >
                      Open
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

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
    </div>
  );
}
