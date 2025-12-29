'use client';

import { Badge } from '../ui/badge';
import { STATUS_COLORS } from '../../lib/constants';

export interface JobStatusBadgeProps {
  status: 'pending' | 'processing' | 'completed' | 'failed';
}

export function JobStatusBadge({ status }: JobStatusBadgeProps) {
  const label = status.charAt(0).toUpperCase() + status.slice(1);
  
  return (
    <Badge className={STATUS_COLORS[status]}>
      {label}
    </Badge>
  );
}

