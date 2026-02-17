'use client';

import { Button } from '@/components/ui/button';
import type { AdminPagination } from '@/lib/api';

export interface PaginationControlsProps {
  pagination: AdminPagination | null;
  onPrev: () => void;
  onNext: () => void;
  /** Optional label for the count, e.g. "users" or "resumes". */
  itemLabel?: string;
}

export function PaginationControls({
  pagination,
  onPrev,
  onNext,
  itemLabel = 'items',
}: PaginationControlsProps) {
  if (!pagination || pagination.total_pages <= 0) return null;

  const label =
    itemLabel === 'items'
      ? `${pagination.total_items} ${pagination.total_items !== 1 ? 'items' : 'item'}`
      : `${pagination.total_items} ${itemLabel}`;

  return (
    <div className="flex items-center justify-between gap-4 pt-2">
      <p className="text-sm text-muted-foreground">
        Page {pagination.page} of {pagination.total_pages} ({label})
      </p>
      <div className="flex gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={!pagination.has_prev}
          onClick={onPrev}
        >
          Previous
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={!pagination.has_next}
          onClick={onNext}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
