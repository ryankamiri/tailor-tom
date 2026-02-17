'use client';

import { formatUsdCompact } from '@/lib/formatting';

export interface AdminOverviewStripProps {
  processed: number;
  completed: number;
  failed: number;
  cancelled: number;
  passRatePct: number;
  monthlyCostUsd: number;
  v3FailRatePct?: number;
  avgPasses?: number;
}

export function AdminOverviewStrip({
  processed,
  completed,
  failed,
  cancelled,
  passRatePct,
  monthlyCostUsd,
  v3FailRatePct,
  avgPasses,
}: AdminOverviewStripProps) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 text-sm">
      <div className="rounded-md border bg-card px-3 py-2">
        <p className="text-muted-foreground">Processed</p>
        <p className="font-semibold">{processed}</p>
      </div>
      <div className="rounded-md border bg-card px-3 py-2">
        <p className="text-muted-foreground">Completed</p>
        <p className="font-semibold text-emerald-600 dark:text-emerald-400">{completed}</p>
      </div>
      <div className="rounded-md border bg-card px-3 py-2">
        <p className="text-muted-foreground">Failed</p>
        <p className="font-semibold text-red-600 dark:text-red-400">{failed}</p>
      </div>
      <div className="rounded-md border bg-card px-3 py-2">
        <p className="text-muted-foreground">Cancelled</p>
        <p className="font-semibold">{cancelled}</p>
      </div>
      <div className="rounded-md border bg-card px-3 py-2">
        <p className="text-muted-foreground">Pass rate</p>
        <p className="font-semibold">{processed > 0 ? `${passRatePct.toFixed(1)}%` : '—'}</p>
      </div>
      <div className="rounded-md border bg-card px-3 py-2">
        <p className="text-muted-foreground">Month cost</p>
        <p className="font-semibold">{formatUsdCompact(monthlyCostUsd)}</p>
      </div>
      {v3FailRatePct != null && (
        <div className="rounded-md border bg-card px-3 py-2">
          <p className="text-muted-foreground">V3 fail rate</p>
          <p className="font-semibold">{v3FailRatePct.toFixed(1)}%</p>
        </div>
      )}
      {avgPasses != null && (
        <div className="rounded-md border bg-card px-3 py-2">
          <p className="text-muted-foreground">Avg passes</p>
          <p className="font-semibold">{avgPasses}</p>
        </div>
      )}
    </div>
  );
}
