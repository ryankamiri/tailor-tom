'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { AdminV3HealthResponse } from '@/lib/api';
import { formatUsdCompact } from '@/lib/formatting';

export interface AdminHealthPanelProps {
  health: AdminV3HealthResponse | null;
}

/** Renders pass1 reasons in error / warning / neutral buckets. apply_no_effect is neutral. */
export function AdminHealthPanel({ health }: AdminHealthPanelProps) {
  if (!health) return null;

  const errorReasons = health.pass1_error_reasons ?? {};
  const warningReasons = health.pass1_warning_reasons ?? {};
  const neutralReasons = health.pass1_neutral_reasons ?? {};
  const applyNoEffectCount = health.apply_no_effect_count ?? 0;
  const applyNoEffectRate = health.apply_no_effect_rate ?? 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>V3 Optimizer Health</CardTitle>
        <CardDescription>From recent jobs with analysis (sample up to 500).</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <p className="text-muted-foreground">V3 completed</p>
            <p className="font-semibold">{health.v3_jobs_completed}</p>
          </div>
          <div>
            <p className="text-muted-foreground">V3 failed</p>
            <p className="font-semibold">{health.v3_jobs_failed}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Avg passes</p>
            <p className="font-semibold">{health.avg_passes_done}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Cost total</p>
            <p className="font-semibold">{formatUsdCompact(health.cost_usd_total)}</p>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
          {Object.keys(errorReasons).length > 0 && (
            <div>
              <p className="font-medium text-red-600 dark:text-red-400 mb-1">Pass1 error reasons</p>
              <ul className="list-disc list-inside text-muted-foreground">
                {Object.entries(errorReasons).map(([k, v]) => (
                  <li key={k}>
                    {k}: {v}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {Object.keys(warningReasons).length > 0 && (
            <div>
              <p className="font-medium text-amber-600 dark:text-amber-400 mb-1">Pass1 warning reasons</p>
              <ul className="list-disc list-inside text-muted-foreground">
                {Object.entries(warningReasons).map(([k, v]) => (
                  <li key={k}>
                    {k}: {v}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {(Object.keys(neutralReasons).length > 0 || applyNoEffectCount > 0) && (
            <div>
              <p className="font-medium text-muted-foreground mb-1">No-op candidates (neutral)</p>
              <ul className="list-disc list-inside text-muted-foreground">
                {Object.entries(neutralReasons).map(([k, v]) => (
                  <li key={k}>
                    {k}: {v}
                  </li>
                ))}
                {applyNoEffectCount > 0 && (
                  <li>rate: {((applyNoEffectRate ?? 0) * 100).toFixed(2)}%</li>
                )}
              </ul>
            </div>
          )}
        </div>

        {Object.keys(health.top_pass2_reasons).length > 0 && (
          <div>
            <p className="font-medium text-muted-foreground mb-1">Top pass2 reasons</p>
            <ul className="list-disc list-inside text-sm text-muted-foreground">
              {Object.entries(health.top_pass2_reasons).map(([k, v]) => (
                <li key={k}>
                  {k}: {v}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
