'use client';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

const MONTHS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] as const;

export interface AdminTopBarProps {
  search: string;
  onSearchChange: (v: string) => void;
  year: number;
  month: number;
  onMonthChange: (month: number) => void;
  onYearChange: (year: number) => void;
  onRefresh: () => void;
  hasResume: boolean | null;
  onHasResumeChange: (v: boolean | null) => void;
  activeOnly: boolean;
  onActiveOnlyChange: (v: boolean) => void;
  failedOnly: boolean;
  onFailedOnlyChange: (v: boolean) => void;
  isRefreshing?: boolean;
}

export function AdminTopBar({
  search,
  onSearchChange,
  year,
  month,
  onMonthChange,
  onYearChange,
  onRefresh,
  hasResume,
  onHasResumeChange,
  activeOnly,
  onActiveOnlyChange,
  failedOnly,
  onFailedOnlyChange,
  isRefreshing = false,
}: AdminTopBarProps) {
  const years = Array.from({ length: 5 }, (_, i) => year - i);

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
      <div className="flex flex-1 flex-wrap items-center gap-2">
        <Input
          placeholder="Search by name or email..."
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className="max-w-xs"
        />
        <Select
          value={`${year}-${month}`}
          onValueChange={(v) => {
            const [y, m] = v.split('-').map(Number);
            onYearChange(y);
            onMonthChange(m);
          }}
        >
          <SelectTrigger className="w-[200px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {years.flatMap((y) =>
              MONTHS.map((m) => (
                <SelectItem key={`${y}-${m}`} value={`${y}-${m}`}>
                  {new Date(Date.UTC(y, m - 1, 1)).toLocaleString('default', { month: 'long' })} {y}
                </SelectItem>
              ))
            )}
          </SelectContent>
        </Select>
        <div className="flex flex-wrap gap-1">
          <Button
            variant={hasResume === true ? 'default' : 'outline'}
            size="sm"
            onClick={() => onHasResumeChange(hasResume === true ? null : true)}
          >
            Has resume
          </Button>
          <Button
            variant={activeOnly ? 'default' : 'outline'}
            size="sm"
            onClick={() => onActiveOnlyChange(!activeOnly)}
          >
            Active jobs &gt; 0
          </Button>
          <Button
            variant={failedOnly ? 'default' : 'outline'}
            size="sm"
            onClick={() => onFailedOnlyChange(!failedOnly)}
          >
            Failed jobs &gt; 0
          </Button>
        </div>
      </div>
      <Button variant="outline" size="sm" onClick={onRefresh} disabled={isRefreshing}>
        {isRefreshing ? 'Refreshing…' : 'Refresh'}
      </Button>
    </div>
  );
}
