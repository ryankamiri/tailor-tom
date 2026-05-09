'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { AlertTriangle, ArrowLeft, Clipboard } from 'lucide-react';
import { toast } from 'sonner';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { RequireAuth } from '@/components/layout/require-auth';
import { getAdminConversionDebug, type AdminConversionDebugResponse } from '@/lib/api';

function formatDate(value: string | null): string {
  if (!value) return 'Unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function DetailRow({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="space-y-1">
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="break-words font-mono text-sm">{value || 'Not available'}</dd>
    </div>
  );
}

function userDisplayName(debug: AdminConversionDebugResponse): string | null {
  const name = [debug.user_first_name, debug.user_last_name].filter(Boolean).join(' ').trim();
  if (name && debug.user_email) return `${name} (${debug.user_email})`;
  return name || debug.user_email || null;
}

function AdminConversionDebugContent() {
  const params = useParams();
  const conversionId = typeof params.conversionId === 'string' ? params.conversionId : '';
  const [debug, setDebug] = useState<AdminConversionDebugResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDebugDetails = useCallback(async () => {
    if (!conversionId) return;
    try {
      setError(null);
      const data = await getAdminConversionDebug(conversionId);
      setDebug(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load conversion debug details');
      setDebug(null);
    } finally {
      setLoading(false);
    }
  }, [conversionId]);

  useEffect(() => {
    loadDebugDetails();
  }, [loadDebugDetails]);

  const copyTraceback = async () => {
    if (!debug?.traceback) return;
    await navigator.clipboard.writeText(debug.traceback);
    toast.success('Stack trace copied');
  };

  const copyError = async () => {
    if (!debug?.error_message) return;
    await navigator.clipboard.writeText(debug.error_message);
    toast.success('Error copied');
  };

  const copyDebugContext = async () => {
    if (!debug?.debug_context) return;
    await navigator.clipboard.writeText(JSON.stringify(debug.debug_context, null, 2));
    toast.success('Debug context copied');
  };

  if (loading) {
    return (
      <div className="container mx-auto max-w-6xl space-y-6 py-8">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (error || !debug) {
    return (
      <div className="container mx-auto max-w-6xl space-y-4 py-8">
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertTitle>Conversion debug details unavailable</AlertTitle>
          <AlertDescription>{error || 'Conversion not found'}</AlertDescription>
        </Alert>
        <Button variant="outline" asChild>
          <Link href="/admin">
            <ArrowLeft className="h-4 w-4" />
            Back to admin
          </Link>
        </Button>
      </div>
    );
  }

  const userLabel = userDisplayName(debug);

  return (
    <div className="container mx-auto max-w-6xl space-y-6 py-8">
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <Link href="/admin" className="hover:underline">
          Admin
        </Link>
        <span>/</span>
        <span>DOCX conversions</span>
        <span>/</span>
        <span className="font-medium text-foreground">{debug.conversion_id}</span>
      </div>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">DOCX Conversion Trace</h1>
          <p className="mt-2 text-muted-foreground">
            Admin-only failure details for conversion {debug.conversion_id}.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={debug.status === 'failed' ? 'destructive' : 'secondary'}>{debug.status}</Badge>
          <Button variant="outline" asChild>
            <Link href="/admin">
              <ArrowLeft className="h-4 w-4" />
              Back to admin
            </Link>
          </Button>
        </div>
      </div>

      {!debug.detail_available && (
        <Alert>
          <AlertTriangle />
          <AlertTitle>Full stack trace unavailable</AlertTitle>
          <AlertDescription>
            The debug record may have expired or the failure happened before stack traces were stored.
            Public conversion status is still shown below when available.
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Failure Summary</CardTitle>
          <CardDescription>Stored metadata from the worker failure path.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <DetailRow label="Conversion ID" value={debug.conversion_id} />
            <DetailRow label="Task" value={debug.task_name} />
            <DetailRow label="Queue" value={debug.queue} />
            <DetailRow label="Status source" value={debug.status_source} />
            <DetailRow label="Failed at" value={formatDate(debug.failed_at)} />
            <DetailRow label="User" value={userLabel || 'Unknown or unauthenticated'} />
            <DetailRow label="User ID" value={debug.user_id} />
          </dl>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-medium text-muted-foreground">Error message</h2>
              {debug.error_message && (
                <Button variant="outline" size="sm" onClick={copyError}>
                  <Clipboard className="h-4 w-4" />
                  Copy
                </Button>
              )}
            </div>
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md border bg-muted px-4 py-3 text-sm">
              {debug.error_message || 'No error message stored.'}
            </pre>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div className="space-y-2">
            <CardTitle>LLM Attempt Diagnostics</CardTitle>
            <CardDescription>
              Per-attempt model, token budget, finish reason, raw output preview, and parse/render errors.
            </CardDescription>
          </div>
          {debug.debug_context && (
            <Button variant="outline" size="sm" onClick={copyDebugContext}>
              <Clipboard className="h-4 w-4" />
              Copy
            </Button>
          )}
        </CardHeader>
        <CardContent>
          <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap break-words rounded-md border bg-muted px-4 py-3 font-mono text-xs leading-relaxed">
            {debug.debug_context
              ? JSON.stringify(debug.debug_context, null, 2)
              : 'No LLM attempt diagnostics stored for this conversion.'}
          </pre>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div className="space-y-2">
            <CardTitle>Full Stack Trace</CardTitle>
            <CardDescription>Captured from the Celery worker exception handler.</CardDescription>
          </div>
          {debug.traceback && (
            <Button variant="outline" size="sm" onClick={copyTraceback}>
              <Clipboard className="h-4 w-4" />
              Copy
            </Button>
          )}
        </CardHeader>
        <CardContent>
          <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap break-words rounded-md border bg-muted px-4 py-3 font-mono text-xs leading-relaxed">
            {debug.traceback || 'No stack trace stored for this conversion.'}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}

export default function AdminConversionDebugPage() {
  return (
    <RequireAuth requireAdmin>
      <AdminConversionDebugContent />
    </RequireAuth>
  );
}
