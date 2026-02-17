'use client';

import { Badge } from '@/components/ui/badge';
import { useAuth } from '@/contexts/auth-context';
import { AlertCircle, CheckCircle2 } from 'lucide-react';

export function DailyLimitBadge() {
  const { user } = useAuth();

  if (!user) {
    return null;
  }

  const limit = user.daily_job_limit;
  const completedToday = user.daily_completions_today;
  const pendingAndProcessing = user.active_jobs_count;
  const remaining = user.daily_limit_remaining;
  const canCreate = remaining > 0;

  if (canCreate) {
    return (
      <Badge variant="outline" className="gap-1">
        <CheckCircle2 className="h-3 w-3" />
        {remaining} of {limit} jobs remaining today
        {pendingAndProcessing > 0 && ` (${pendingAndProcessing} pending)`}
      </Badge>
    );
  }

  const totalUsed = completedToday + pendingAndProcessing;
  return (
    <Badge variant="destructive" className="gap-1">
      <AlertCircle className="h-3 w-3" />
      Daily limit reached ({totalUsed}/{limit})
      {pendingAndProcessing > 0 && ` (${pendingAndProcessing} pending)`}
    </Badge>
  );
}
