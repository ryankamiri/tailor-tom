'use client';

import { useState, useEffect, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { getAnnotatedDiffPdfs } from '@/lib/api';
import { Skeleton } from '@/components/ui/skeleton';
import { Loader2 } from 'lucide-react';

export interface PdfDiffViewProps {
  originalLatex: string;
  optimizedLatex: string;
  trigger?: number; // Force reload when this value changes
  showErrorOnFail?: boolean; // If false, don't show errors (for failed jobs where errors are expected)
}

export function PdfDiffView({ originalLatex, optimizedLatex, trigger, showErrorOnFail = true }: PdfDiffViewProps) {
  const [originalPdfUrl, setOriginalPdfUrl] = useState<string | null>(null);
  const [optimizedPdfUrl, setOptimizedPdfUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const urlsRef = useRef<{ original: string | null; optimized: string | null }>({ original: null, optimized: null });

  // Load PDFs when trigger changes (only reload explicitly, not on every edit)
  useEffect(() => {
    const loadPdfs = async () => {
      try {
        setIsLoading(true);
        setError(null);

        // Cleanup old URLs before creating new ones
        if (urlsRef.current.original) {
          URL.revokeObjectURL(urlsRef.current.original);
        }
        if (urlsRef.current.optimized) {
          URL.revokeObjectURL(urlsRef.current.optimized);
        }

        const result = await getAnnotatedDiffPdfs(originalLatex, optimizedLatex);

        // Create blob URLs from base64
        const originalPdfBytes = Uint8Array.from(atob(result.original_pdf), (c) => c.charCodeAt(0));
        const optimizedPdfBytes = Uint8Array.from(atob(result.optimized_pdf), (c) => c.charCodeAt(0));
        
        const originalBlob = new Blob([originalPdfBytes], { type: 'application/pdf' });
        const optimizedBlob = new Blob([optimizedPdfBytes], { type: 'application/pdf' });
        
        const newOriginalUrl = URL.createObjectURL(originalBlob);
        const newOptimizedUrl = URL.createObjectURL(optimizedBlob);
        
        urlsRef.current.original = newOriginalUrl;
        urlsRef.current.optimized = newOptimizedUrl;
        setOriginalPdfUrl(newOriginalUrl);
        setOptimizedPdfUrl(newOptimizedUrl);
        setIsLoading(false);
      } catch (err) {
        // Log full error to console
        console.error('Failed to load PDF diffs:', err);
        
        // Only show error if showErrorOnFail is true (default behavior)
        if (showErrorOnFail) {
          let errorMessage = 'Failed to load PDF diffs';
          if (err instanceof Error) {
            errorMessage = err.message;
            // Extract LaTeX compilation errors for better UX
            if (errorMessage.includes('Failed to compile')) {
              // The error message from backend should already be descriptive
              errorMessage = errorMessage.replace('Failed to generate PDF diffs: ', '');
            }
          }
          setError(errorMessage);
        } else {
          // For failed jobs, silently fail - don't show error
          setError(null);
        }
        setIsLoading(false);
      }
    };

    loadPdfs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trigger]); // Only reload when trigger changes, use current originalLatex/optimizedLatex from closure

  // Cleanup blob URLs on unmount
  useEffect(() => {
    const currentUrls = urlsRef.current;
    return () => {
      if (currentUrls.original) URL.revokeObjectURL(currentUrls.original);
      if (currentUrls.optimized) URL.revokeObjectURL(currentUrls.optimized);
    };
  }, []);

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>PDF Comparison</CardTitle>
          <CardDescription>Generating annotated PDFs with highlighted differences...</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="relative h-[800px] w-full">
              <Skeleton className="h-full w-full" />
              <div className="absolute inset-0 flex items-center justify-center">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            </div>
            <div className="relative h-[800px] w-full">
              <Skeleton className="h-full w-full" />
              <div className="absolute inset-0 flex items-center justify-center">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    const isCompilationError = error.includes('Failed to compile') || error.includes('Paragraph ended') || error.includes('Fatal error');
    
    return (
      <Card>
        <CardHeader>
          <CardTitle>PDF Comparison</CardTitle>
          <CardDescription>
            {isCompilationError ? 'LaTeX compilation error' : 'Error loading PDFs'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <p className="text-destructive font-medium">{error}</p>
            {isCompilationError && (
              <p className="text-sm text-muted-foreground">
                Please fix the LaTeX syntax errors before saving. The PDF comparison cannot be generated until the LaTeX is valid.
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>PDF Comparison</CardTitle>
        <CardDescription>
          {`Side-by-side view with highlighted changes. Red highlights indicate removed text, green highlights indicate added text. To download a clean PDF without highlights, use the "Download Optimized Resume" button above.`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Original PDF */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-red-600 dark:text-red-400">Original Resume</h3>
              <span className="text-xs text-muted-foreground">Red = Removed</span>
            </div>
            <div className="border rounded-lg overflow-hidden bg-gray-50 dark:bg-gray-900">
              {originalPdfUrl && (
                <iframe
                  src={`${originalPdfUrl}#toolbar=0&navpanes=0`}
                  className="w-full h-[800px] border-0"
                  title="Original Resume PDF"
                />
              )}
            </div>
          </div>

          {/* Optimized PDF */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-emerald-600 dark:text-emerald-400">Optimized Resume</h3>
              <span className="text-xs text-muted-foreground">Green = Added</span>
            </div>
            <div className="border rounded-lg overflow-hidden bg-gray-50 dark:bg-gray-900">
              {optimizedPdfUrl && (
                <iframe
                  src={`${optimizedPdfUrl}#toolbar=0&navpanes=0`}
                  className="w-full h-[800px] border-0"
                  title="Optimized Resume PDF"
                />
              )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

