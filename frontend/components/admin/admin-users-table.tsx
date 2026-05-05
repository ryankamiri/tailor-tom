'use client';

import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import type { AdminUserRow, AdminPagination } from '@/lib/api';
import { formatLocalDateSafe, formatUsdCompact } from '@/lib/formatting';
import { PaginationControls } from './pagination-controls';

interface SortableThProps {
  label: string;
  field: string;
  align?: 'left' | 'right' | 'center';
  sort: string;
  order: 'asc' | 'desc';
  onSort?: (field: string) => void;
}

function SortableTh({ label, field, align = 'left', sort, order, onSort }: SortableThProps) {
  return (
    <th
      className={`px-2 py-2 font-medium border-b ${align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'}`}
    >
      {onSort ? (
        <button
          type="button"
          onClick={() => onSort(field)}
          className="hover:underline"
        >
          {label} {sort === field ? (order === 'asc' ? '↑' : '↓') : ''}
        </button>
      ) : (
        label
      )}
    </th>
  );
}

export interface AdminUsersTableProps {
  users: AdminUserRow[];
  pagination: AdminPagination | null;
  onPagePrev: () => void;
  onPageNext: () => void;
  onOpenDetail: (user: AdminUserRow) => void;
  sort?: string;
  order?: 'asc' | 'desc';
  onSort?: (field: string) => void;
}

export function AdminUsersTable({
  users,
  pagination,
  onPagePrev,
  onPageNext,
  onOpenDetail,
  sort = 'email',
  order = 'asc',
  onSort,
}: AdminUsersTableProps) {
  const router = useRouter();
  const thProps = { sort, order, onSort };

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b bg-muted/50">
              <SortableTh {...thProps} label="Identity" field="email" />
              <th className="px-2 py-2 text-center font-medium border-b">Role</th>
              <th className="px-2 py-2 text-center font-medium border-b">Resume</th>
              <th className="px-2 py-2 text-center font-medium border-b">Active</th>
              <th className="px-2 py-2 text-center font-medium border-b">Quota used</th>
              <SortableTh {...thProps} label="Joined" field="created_at" />
              <SortableTh {...thProps} label="Month cost" field="month_cost_usd" align="right" />
              <SortableTh {...thProps} label="Lifetime cost" field="total_cost_usd" align="right" />
              <th className="px-2 py-2 text-right font-medium border-b">Completed</th>
              <th className="px-2 py-2 text-right font-medium border-b">Failed</th>
              <SortableTh {...thProps} label="Last job" field="last_job_at" />
              <th className="px-2 py-2 w-[180px] font-medium border-b">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.length === 0 ? (
              <tr>
                <td colSpan={12} className="text-center text-muted-foreground py-8 px-2">
                  No users match the current filters.
                </td>
              </tr>
            ) : (
              users.map((row) => (
                <tr key={row.user_id} className="border-b border-border/50 hover:bg-muted/30">
                  <td className="px-2 py-2">
                    <div>
                      <span className="font-medium">
                        {row.first_name} {row.last_name}
                      </span>
                      <span className="block text-xs text-muted-foreground truncate max-w-[180px]">
                        {row.email}
                      </span>
                    </div>
                  </td>
                  <td className="px-2 py-2 text-center">
                    {row.is_admin ? (
                      <span className="text-xs font-medium text-amber-600 dark:text-amber-400">Admin</span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="px-2 py-2 text-center">
                    {row.has_resume ? (
                      <span className="text-emerald-600 dark:text-emerald-400">Yes</span>
                    ) : (
                      <span className="text-muted-foreground">No</span>
                    )}
                  </td>
                  <td className="px-2 py-2 text-center">{row.active_jobs_count}</td>
                  <td className="px-2 py-2 text-center">{row.daily_quota_used}</td>
                  <td className="px-2 py-2 text-muted-foreground">
                    {row.created_at ? formatLocalDateSafe(row.created_at, '—') : '—'}
                  </td>
                  <td className="px-2 py-2 text-right">{formatUsdCompact(row.month_cost_usd)}</td>
                  <td className="px-2 py-2 text-right">{formatUsdCompact(row.total_cost_usd)}</td>
                  <td className="px-2 py-2 text-right">{row.completed_count}</td>
                  <td className="px-2 py-2 text-right">{row.failed_count}</td>
                  <td className="px-2 py-2 text-muted-foreground">
                    {row.last_job_at ? formatLocalDateSafe(row.last_job_at, '—') : '—'}
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex flex-wrap gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => router.push(`/admin/users/${row.user_id}/jobs`)}
                      >
                        View Jobs
                      </Button>
                      {row.has_resume && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => router.push(`/admin/resume/${row.user_id}`)}
                        >
                          View Resume
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onOpenDetail(row)}
                      >
                        Open Detail
                      </Button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <PaginationControls
        pagination={pagination}
        onPrev={onPagePrev}
        onNext={onPageNext}
        itemLabel="users"
      />
    </div>
  );
}
