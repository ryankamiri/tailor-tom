'use client';

import { Badge } from '@/components/ui/badge';
import { canCreateJobWithinDailyLimit } from '@/lib/storage';
import { AlertCircle, CheckCircle2 } from 'lucide-react';

export function DailyLimitBadge() {
  const { completedToday, pendingAndProcessing, limit, remaining, canCreate } = canCreateJobWithinDailyLimit();
  
  if (canCreate) {
    return (
      <Badge variant="outline" className="gap-1">
        <CheckCircle2 className="h-3 w-3" />
        {remaining} of {limit} jobs remaining today
      </Badge>
    );
  }
  
  // Show more detailed info when limit reached
  const totalUsed = completedToday + pendingAndProcessing;
  return (
    <Badge variant="destructive" className="gap-1">
      <AlertCircle className="h-3 w-3" />
      Daily limit reached ({totalUsed}/{limit})
    </Badge>
  );
}
