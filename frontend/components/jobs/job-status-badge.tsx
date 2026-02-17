'use client';

import { Badge } from '@/components/ui/badge';
import { STATUS_COLORS, STATUS_LABELS } from '@/lib/constants';

export interface JobStatusBadgeProps {
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';
}

export function JobStatusBadge({ status }: JobStatusBadgeProps) {
  const label = STATUS_LABELS[status] ?? status.charAt(0).toUpperCase() + status.slice(1);
  return (
    <Badge className={STATUS_COLORS[status]}>
      {label}
    </Badge>
  );
}

