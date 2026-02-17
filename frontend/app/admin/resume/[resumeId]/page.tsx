'use client';

import { useState, useEffect, useRef } from 'react';
import Image from 'next/image';
import { useParams, useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { LatexEditor } from '@/components/editor/latex-editor';
import { getAdminResume, compileLatexToPdf } from '@/lib/api';
import { resumePdfFilename } from '@/lib/utils';
import { formatLocalDateSafe } from '@/lib/formatting';
import { RequireAuth } from '@/components/layout/require-auth';
import { toast } from 'sonner';

interface ResumeData {
  user_id: string;
  email: string;
  first_name: string;
  last_name: string;
  avatar_url: string | null;
  latex: string;
  created_at: string;
  filename: string;
}

function ResumeDetailContent() {
  const params = useParams();
  const router = useRouter();
  // The route param is still called resumeId but now contains the user_id
  const userId = params.resumeId as string;

  const [resume, setResume] = useState<ResumeData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const pdfUrlRef = useRef<string | null>(null);

  useEffect(() => {
    const load = async () => {
      setIsLoading(true);
      try {
        const data = await getAdminResume(userId);
        setResume(data);

        // Compile PDF preview
        try {
          const pdfBlob = await compileLatexToPdf(data.latex, data.filename);
          const url = URL.createObjectURL(pdfBlob);
          if (pdfUrlRef.current) URL.revokeObjectURL(pdfUrlRef.current);
          pdfUrlRef.current = url;
          setPdfUrl(url);
        } catch {
          toast.error('Failed to generate PDF preview');
        }
      } catch (error) {
        toast.error(error instanceof Error ? error.message : 'Failed to load resume');
        router.push('/admin');
      } finally {
        setIsLoading(false);
      }
    };

    load();
  }, [userId, router]);

  // Cleanup PDF URL on unmount
  useEffect(() => {
    return () => {
      if (pdfUrlRef.current) URL.revokeObjectURL(pdfUrlRef.current);
    };
  }, []);

  const handleDownloadPdf = async () => {
    if (!resume) return;
    try {
      const filename = resumePdfFilename(resume.first_name, resume.last_name);
      const blob = await compileLatexToPdf(resume.latex, filename);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      toast.success('Downloaded PDF');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to download');
    }
  };

  if (isLoading) {
    return (
      <div className="container mx-auto py-8 max-w-6xl space-y-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (!resume) {
    return (
      <div className="container mx-auto py-8 max-w-6xl">
        <Card>
          <CardContent className="pt-6">
            <p>Resume not found</p>
            <Button onClick={() => router.push('/admin')} variant="outline" className="mt-4">
              Back to Admin Panel
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-8 max-w-6xl space-y-6">
      {/* Header */}
      <div className="flex justify-between items-start gap-4">
        <div className="flex items-start gap-4 min-w-0">
          {resume.avatar_url ? (
            <Image
              src={resume.avatar_url}
              alt={resume.first_name && resume.last_name ? `${resume.first_name} ${resume.last_name}` : resume.email}
              width={64}
              height={64}
              className="rounded-full shrink-0"
              referrerPolicy="no-referrer"
            />
          ) : (
            <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground text-2xl font-medium">
              {(resume.first_name?.[0] || resume.email[0] || '?').toUpperCase()}
            </div>
          )}
          <div>
            <h1 className="text-3xl font-bold">
              {resume.first_name} {resume.last_name}
            </h1>
            <p className="text-sm text-muted-foreground mt-1">{resume.email}</p>
            <p className="text-sm text-muted-foreground">Saved: {formatLocalDateSafe(resume.created_at)}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button onClick={handleDownloadPdf} variant="outline">Download PDF</Button>
          <Button onClick={() => router.push('/admin')} variant="outline">Back to List</Button>
        </div>
      </div>

      {/* PDF Preview */}
      <Card>
        <CardHeader>
          <CardTitle>PDF Preview</CardTitle>
          <CardDescription>Rendered resume PDF</CardDescription>
        </CardHeader>
        <CardContent>
          {pdfUrl ? (
            <div className="border rounded-lg overflow-hidden bg-gray-50 dark:bg-gray-900">
              <iframe
                src={pdfUrl}
                className="w-full h-[800px] border-0"
                title="Resume PDF Preview"
              />
            </div>
          ) : (
            <div className="border rounded-lg p-8 text-center text-muted-foreground">
              PDF preview unavailable
            </div>
          )}
        </CardContent>
      </Card>

      {/* LaTeX Source */}
      <Card>
        <CardHeader>
          <CardTitle>LaTeX Source</CardTitle>
          <CardDescription>Resume LaTeX source code</CardDescription>
        </CardHeader>
        <CardContent>
          <LatexEditor value={resume.latex} onChange={() => {}} readOnly height="600px" />
        </CardContent>
      </Card>
    </div>
  );
}

export default function ResumeDetailPage() {
  return (
    <RequireAuth requireAdmin>
      <ResumeDetailContent />
    </RequireAuth>
  );
}
