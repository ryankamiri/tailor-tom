'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { JobStatus } from '@/lib/api';

export interface JobStatusViewProps {
  status: JobStatus['status'];
  errorMessage?: string | null;
}

export function JobStatusView({ status, errorMessage }: JobStatusViewProps) {
  if (status === 'failed') {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Error</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-destructive">{errorMessage || 'Optimization failed'}</p>
        </CardContent>
      </Card>
    );
  }

  if (status === 'cancelled') {
    return (
      <Card>
        <CardContent className="pt-6">
          <p className="text-muted-foreground">Job was cancelled by user.</p>
        </CardContent>
      </Card>
    );
  }

  if (status === 'processing') {
    return (
      <Card>
        <CardContent className="pt-6">
          <div className="text-center py-8">
            <p className="text-lg mb-2">Processing optimization...</p>
            <p className="text-sm text-muted-foreground">
              This may take a few minutes. You can close this page and check back later.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return null;
}

