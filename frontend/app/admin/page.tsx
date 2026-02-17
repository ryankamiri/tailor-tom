'use client';

import { useState, useEffect, useCallback } from 'react';
import Image from 'next/image';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  getAdminUsers,
  getAdminUserSummary,
  listAdminResumes,
  getAdminResume,
  getAdminJobStats,
  getAdminUserCosts,
  getAdminV3Health,
  compileLatexToPdf,
  resetMyDailyCount,
  type AdminUserRow,
  type AdminUsersResponse,
  type AdminUserSummaryResponse,
  type AdminUserCostsResponse,
  type AdminPagination,
  type AdminV3HealthResponse,
} from '@/lib/api';
import { resumePdfFilename } from '@/lib/utils';
import { formatLocalDateSafe, formatUsdCompact } from '@/lib/formatting';
import { PaginationControls } from '@/components/admin/pagination-controls';
import { AdminTopBar } from '@/components/admin/admin-top-bar';
import { AdminOverviewStrip } from '@/components/admin/admin-overview-strip';
import { AdminUsersTable } from '@/components/admin/admin-users-table';
import { AdminUserDetailDrawer } from '@/components/admin/admin-user-detail-drawer';
import { AdminHealthPanel } from '@/components/admin/admin-health-panel';
import { RequireAuth } from '@/components/layout/require-auth';
import { useAuth } from '@/contexts/auth-context';
import { toast } from 'sonner';

interface Resume {
  user_id: string;
  email: string;
  first_name: string;
  last_name: string;
  avatar_url: string | null;
  created_at: string;
  filename: string;
}

const DEFAULT_LIMIT = 20;

function AdminContent() {
  const router = useRouter();
  const { user, setUserFromProfile } = useAuth();
  const now = new Date();
  const [search, setSearch] = useState('');
  const [year, setYear] = useState(now.getUTCFullYear());
  const [month, setMonth] = useState(now.getUTCMonth() + 1);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState('email');
  const [order, setOrder] = useState<'asc' | 'desc'>('asc');
  const [hasResume, setHasResume] = useState<boolean | null>(null);
  const [activeOnly, setActiveOnly] = useState(false);
  const [failedOnly, setFailedOnly] = useState(false);

  const [usersData, setUsersData] = useState<AdminUsersResponse | null>(null);
  const [usersLoading, setUsersLoading] = useState(true);
  const [jobStats, setJobStats] = useState<{ processed: number; completed: number; failed: number; cancelled: number } | null>(null);
  const [v3Health, setV3Health] = useState<AdminV3HealthResponse | null>(null);
  const [costData, setCostData] = useState<AdminUserCostsResponse | null>(null);
  const [costError, setCostError] = useState<string | null>(null);
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [resumePagination, setResumePagination] = useState<AdminPagination | null>(null);
  const [resumePage, setResumePage] = useState(1);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [costPage, setCostPage] = useState(1);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [userSummary, setUserSummary] = useState<AdminUserSummaryResponse | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isResettingDaily, setIsResettingDaily] = useState(false);

  const loadOverview = useCallback(async () => {
    setOverviewLoading(true);
    try {
      const [stats, health] = await Promise.all([
        getAdminJobStats(),
        getAdminV3Health().catch(() => null),
      ]);
      setJobStats(stats);
      setV3Health(health ?? null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to load overview');
    } finally {
      setOverviewLoading(false);
    }
  }, []);

  const loadUsers = useCallback(async () => {
    setUsersLoading(true);
    try {
      const data = await getAdminUsers({
        page,
        limit: DEFAULT_LIMIT,
        search: search.trim() || undefined,
        year,
        month,
        sort,
        order,
        has_resume: hasResume ?? undefined,
        active_only: activeOnly,
        failed_only: failedOnly,
      });
      setUsersData(data);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to load users');
      setUsersData(null);
    } finally {
      setUsersLoading(false);
    }
  }, [page, search, year, month, sort, order, hasResume, activeOnly, failedOnly]);

  const loadCostData = useCallback(async () => {
    setCostError(null);
    try {
      const data = await getAdminUserCosts({ year, month, page: costPage, limit: 20 });
      setCostData(data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to load costs';
      setCostError(msg);
      toast.error(msg);
      setCostData(null);
    }
  }, [year, month, costPage]);

  const loadResumes = useCallback(async () => {
    try {
      const data = await listAdminResumes({ page: resumePage, limit: 20 });
      setResumes(data.resumes);
      setResumePagination(data.pagination);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to load resumes');
    }
  }, [resumePage]);

  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    await Promise.all([loadOverview(), loadUsers()]);
    setIsRefreshing(false);
    toast.success('Refreshed');
  }, [loadOverview, loadUsers]);

  useEffect(() => {
    loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  useEffect(() => {
    setPage(1);
  }, [search, hasResume, activeOnly, failedOnly]);

  const handleOpenDetail = useCallback(async (row: AdminUserRow) => {
    setDrawerOpen(true);
    setUserSummary(null);
    setSummaryLoading(true);
    try {
      const summary = await getAdminUserSummary(row.user_id);
      setUserSummary(summary);
    } catch {
      setUserSummary(null);
    } finally {
      setSummaryLoading(false);
    }
  }, []);

  const handleSort = useCallback((field: string) => {
    setOrder((prev) => (sort === field && prev === 'asc' ? 'desc' : 'asc'));
    setSort(field);
    setPage(1);
  }, [sort]);

  useEffect(() => {
    loadCostData();
  }, [loadCostData]);

  useEffect(() => {
    loadResumes();
  }, [loadResumes]);

  const passRatePct = jobStats && jobStats.processed > 0
    ? (jobStats.completed / jobStats.processed) * 100
    : 0;
  const monthlyCostUsd = costData?.summary?.month_total_cost_usd ?? 0;
  const v3FailRatePct = v3Health && (v3Health.v3_jobs_completed + v3Health.v3_jobs_failed) > 0
    ? (v3Health.v3_jobs_failed / (v3Health.v3_jobs_completed + v3Health.v3_jobs_failed)) * 100
    : undefined;

  return (
    <div className="container mx-auto py-6 max-w-7xl space-y-6">
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-3xl font-bold">Admin</h1>
          <p className="text-muted-foreground mt-1">User-centric operations workspace</p>
        </div>
      </div>

      <AdminTopBar
        search={search}
        onSearchChange={setSearch}
        year={year}
        month={month}
        onMonthChange={(m) => { setMonth(m); setPage(1); }}
        onYearChange={(y) => { setYear(y); setPage(1); }}
        onRefresh={handleRefresh}
        hasResume={hasResume}
        onHasResumeChange={(v) => { setHasResume(v); setPage(1); }}
        activeOnly={activeOnly}
        onActiveOnlyChange={(v) => { setActiveOnly(v); setPage(1); }}
        failedOnly={failedOnly}
        onFailedOnlyChange={(v) => { setFailedOnly(v); setPage(1); }}
        isRefreshing={isRefreshing}
      />

      {overviewLoading ? (
        <Skeleton className="h-20 w-full" />
      ) : (
        <AdminOverviewStrip
          processed={jobStats?.processed ?? 0}
          completed={jobStats?.completed ?? 0}
          failed={jobStats?.failed ?? 0}
          cancelled={jobStats?.cancelled ?? 0}
          passRatePct={passRatePct}
          monthlyCostUsd={monthlyCostUsd}
          v3FailRatePct={v3FailRatePct}
          avgPasses={v3Health?.avg_passes_done}
        />
      )}

      <Tabs defaultValue="users" className="space-y-4">
        <TabsList>
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="health">Optimizer Health</TabsTrigger>
          <TabsTrigger value="costs">Costs</TabsTrigger>
          <TabsTrigger value="resumes">Resumes</TabsTrigger>
        </TabsList>

        <TabsContent value="users" className="space-y-4">
          {usersLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : usersData ? (
            <AdminUsersTable
              users={usersData.users}
              pagination={usersData.pagination}
              onPagePrev={() => setPage((p) => Math.max(1, p - 1))}
              onPageNext={() => setPage((p) => p + 1)}
              onOpenDetail={handleOpenDetail}
              sort={sort}
              order={order}
              onSort={handleSort}
            />
          ) : (
            <p className="text-muted-foreground">No user data.</p>
          )}
        </TabsContent>

        <TabsContent value="health">
          <AdminHealthPanel health={v3Health} />
        </TabsContent>

        <TabsContent value="costs" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Per-User Cost Analytics</CardTitle>
              <CardDescription>LLM cost by user. Month is UTC.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap gap-4">
                <select
                  className="rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={month}
                  onChange={(e) => { setMonth(Number(e.target.value)); setCostPage(1); }}
                >
                  {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((m) => (
                    <option key={m} value={m}>
                      {new Date(Date.UTC(year, m - 1, 1)).toLocaleString('default', { month: 'long' })} {year}
                    </option>
                  ))}
                </select>
                <select
                  className="rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={year}
                  onChange={(e) => { setYear(Number(e.target.value)); setCostPage(1); }}
                >
                  {Array.from({ length: 5 }, (_, i) => year - i).map((y) => (
                    <option key={y} value={y}>{y}</option>
                  ))}
                </select>
              </div>
              {costError && <p className="text-sm text-destructive">{costError}</p>}
              {costData && (
                <>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                      <p className="text-sm text-muted-foreground">Month total (UTC)</p>
                      <p className="text-2xl font-semibold">{formatUsdCompact(costData.summary.month_total_cost_usd)}</p>
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">Lifetime total</p>
                      <p className="text-2xl font-semibold">{formatUsdCompact(costData.summary.lifetime_total_cost_usd)}</p>
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">Users with cost</p>
                      <p className="text-2xl font-semibold">{costData.summary.users_with_cost_count}</p>
                    </div>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm border-collapse">
                      <thead>
                        <tr className="border-b">
                          <th className="text-left py-2 pr-4 font-medium">User</th>
                          <th className="text-right py-2 px-2 font-medium">Month cost</th>
                          <th className="text-right py-2 px-2 font-medium">Lifetime cost</th>
                          <th className="text-left py-2 pl-2 font-medium">Last cost job</th>
                        </tr>
                      </thead>
                      <tbody>
                        {costData.users.map((row) => (
                          <tr key={row.user_id} className="border-b border-border/50">
                            <td className="py-2 pr-4">
                              <span className="font-medium">{row.first_name} {row.last_name}</span>
                              <span className="text-muted-foreground block text-xs">{row.email}</span>
                            </td>
                            <td className="text-right py-2 px-2">{formatUsdCompact(row.month_cost_usd)}</td>
                            <td className="text-right py-2 px-2">{formatUsdCompact(row.total_cost_usd)}</td>
                            <td className="py-2 pl-2 text-muted-foreground">
                              {row.last_cost_job_at ? formatLocalDateSafe(row.last_cost_job_at, '—') : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <PaginationControls
                    pagination={costData.pagination}
                    onPrev={() => setCostPage((p) => Math.max(1, p - 1))}
                    onNext={() => setCostPage((p) => p + 1)}
                    itemLabel="users"
                  />
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="resumes" className="space-y-4">
          {resumes.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-center text-muted-foreground">No resumes found</CardContent>
            </Card>
          ) : (
            <div className="space-y-4">
              {resumes.map((resume) => (
                <Card key={resume.user_id}>
                  <CardContent className="pt-6">
                    <div className="flex justify-between items-start gap-4">
                      <div className="flex items-start gap-4 min-w-0">
                        {resume.avatar_url ? (
                          <Image
                            src={resume.avatar_url}
                            alt={`${resume.first_name} ${resume.last_name}`}
                            width={48}
                            height={48}
                            className="rounded-full shrink-0"
                            referrerPolicy="no-referrer"
                          />
                        ) : (
                          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground text-lg font-medium">
                            {(resume.first_name?.[0] || resume.email[0] || '?').toUpperCase()}
                          </div>
                        )}
                        <div className="space-y-1 min-w-0">
                          <h3 className="font-semibold text-lg">{resume.first_name} {resume.last_name}</h3>
                          <p className="text-sm text-muted-foreground truncate">{resume.email}</p>
                          <p className="text-sm text-muted-foreground">Saved: {formatLocalDateSafe(resume.created_at)}</p>
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <Button onClick={() => router.push(`/admin/resume/${resume.user_id}`)} variant="default" size="sm">
                          View
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={async () => {
                            try {
                              const data = await getAdminResume(resume.user_id);
                              const filename = resumePdfFilename(resume.first_name, resume.last_name);
                              const blob = await compileLatexToPdf(data.latex, filename);
                              const url = window.URL.createObjectURL(blob);
                              const a = document.createElement('a');
                              a.href = url;
                              a.download = filename;
                              document.body.appendChild(a);
                              a.click();
                              document.body.removeChild(a);
                              window.URL.revokeObjectURL(url);
                              toast.success('Downloaded PDF');
                            } catch (e) {
                              toast.error(e instanceof Error ? e.message : 'Download failed');
                            }
                          }}
                        >
                          Download PDF
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
              <PaginationControls
                pagination={resumePagination}
                onPrev={() => setResumePage((p) => Math.max(1, p - 1))}
                onNext={() => setResumePage((p) => p + 1)}
                itemLabel="resumes"
              />
            </div>
          )}
        </TabsContent>
      </Tabs>

      {user && (
        <Card>
          <CardHeader>
            <CardTitle>Daily Job Limit (Your Account)</CardTitle>
            <CardDescription>Stored in the database; limit resets at midnight UTC.</CardDescription>
          </CardHeader>
          <CardContent className="flex items-center justify-between">
            <div className="text-sm text-muted-foreground space-y-1">
              <p>Completed today: {user.daily_completions_today} / {user.daily_job_limit}</p>
              <p>Pending/Processing: {user.active_jobs_count}</p>
              <p>Remaining: {user.daily_limit_remaining}</p>
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={isResettingDaily}
              onClick={async () => {
                if (!confirm('Reset your daily job count?')) return;
                setIsResettingDaily(true);
                try {
                  const updated = await resetMyDailyCount(user);
                  setUserFromProfile(updated);
                  toast.success('Daily count reset');
                } catch (e) {
                  toast.error(e instanceof Error ? e.message : 'Reset failed');
                } finally {
                  setIsResettingDaily(false);
                }
              }}
            >
              {isResettingDaily ? 'Resetting…' : 'Reset Daily Count'}
            </Button>
          </CardContent>
        </Card>
      )}

      <AdminUserDetailDrawer
        open={drawerOpen}
        onClose={() => { setDrawerOpen(false); setUserSummary(null); }}
        summary={userSummary}
        loading={summaryLoading}
      />
    </div>
  );
}

export default function AdminPage() {
  return (
    <RequireAuth requireAdmin>
      <AdminContent />
    </RequireAuth>
  );
}
