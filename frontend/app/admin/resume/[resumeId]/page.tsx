'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { LatexEditor } from '@/components/editor/latex-editor';
import { getAdminResume, downloadResume, deleteResume, compileLatexToPdf } from '@/lib/api';
import { getCachedAdminResumes, saveCachedAdminResumes } from '@/lib/storage';
import { ADMIN_SESSION_TIMEOUT_MS } from '@/lib/constants';
import { toast } from 'sonner';

interface ResumeData {
  resume_id: string;
  user_id: string;
  first_name: string;
  last_name: string;
  latex: string;
  created_at: string;
  filename: string;
}

export default function ResumeDetailPage() {
  const params = useParams();
  const router = useRouter();
  const resumeId = params.resumeId as string;
  
  const [password, setPassword] = useState('');
  const [resume, setResume] = useState<ResumeData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const pdfUrlRef = useRef<string | null>(null);

  const updateAdminSessionTimestamp = useCallback(() => {
    sessionStorage.setItem('admin_session_timestamp', Date.now().toString());
  }, []);

  const checkAdminSessionTimeout = useCallback((): boolean => {
    const timestamp = sessionStorage.getItem('admin_session_timestamp');
    if (!timestamp) {
      // No timestamp means session expired or never existed
      sessionStorage.removeItem('admin_password');
      router.push('/admin');
      return false;
    }
    
    const sessionAge = Date.now() - parseInt(timestamp, 10);
    if (sessionAge > ADMIN_SESSION_TIMEOUT_MS) {
      // Session expired
      sessionStorage.removeItem('admin_password');
      sessionStorage.removeItem('admin_session_timestamp');
      toast.error('Admin session expired. Please log in again.');
      router.push('/admin');
      return false;
    }
    
    return true; // Session is valid
  }, [router]);

  // Get password from sessionStorage (set during admin login)
  useEffect(() => {
    const storedPassword = sessionStorage.getItem('admin_password');
    if (storedPassword) {
      // Check if session has expired
      if (checkAdminSessionTimeout()) {
        setPassword(storedPassword);
        updateAdminSessionTimestamp(); // Update timestamp on page load
      }
    } else {
      // No password in session, redirect to admin login
      router.push('/admin');
    }

    // Set up periodic session timeout check (every minute)
    const timeoutCheckInterval = setInterval(() => {
      if (password) {
        if (!checkAdminSessionTimeout()) {
          // Session expired, redirect already handled by checkAdminSessionTimeout
        }
      }
    }, 60000); // Check every minute

    return () => {
      clearInterval(timeoutCheckInterval);
    };
  }, [router, password, checkAdminSessionTimeout, updateAdminSessionTimestamp]);

  // Load resume data
  useEffect(() => {
    const loadResume = async () => {
      if (!password) return;
      
      setIsLoading(true);
      try {
        // Check session timeout before loading
        if (!checkAdminSessionTimeout()) {
          setIsLoading(false);
          return;
        }

        // First, check local cache for the resume
        const cachedResumes = getCachedAdminResumes();
        const cachedResume = cachedResumes.find(r => r.resume_id === resumeId);
        
        let data: ResumeData;
        
        if (cachedResume && cachedResume.latex) {
          // Use cached resume if it has LaTeX content
          data = {
            resume_id: cachedResume.resume_id,
            user_id: cachedResume.user_id || '',
            first_name: cachedResume.first_name,
            last_name: cachedResume.last_name,
            latex: cachedResume.latex,
            created_at: cachedResume.created_at,
            filename: cachedResume.filename,
          };
        } else {
          // Try to fetch from Redis (backend)
          try {
            data = await getAdminResume(resumeId, password);
            // Update cache with full data (including LaTeX) for future use
            const updatedCache = cachedResumes.map(r => 
              r.resume_id === resumeId 
                ? { ...r, latex: data.latex, user_id: data.user_id }
                : r
            );
            // If not in cache, add it
            if (!cachedResume) {
              updatedCache.push({
                resume_id: data.resume_id,
                user_id: data.user_id,
                first_name: data.first_name,
                last_name: data.last_name,
                created_at: data.created_at,
                filename: data.filename,
                latex: data.latex,
              });
            }
            // Save updated cache with LaTeX content
            saveCachedAdminResumes(updatedCache);
          } catch (error) {
            // If fetch fails and we have cached resume (but no LaTeX), show error
            if (cachedResume) {
              throw new Error('Resume found in cache but LaTeX content is not available. It may have been deleted from Redis.');
            }
            throw error;
          }
        }
        
        setResume(data);
        updateAdminSessionTimestamp(); // Update timestamp on action
        
        // Compile LaTeX to PDF for preview
        try {
          const pdfBlob = await compileLatexToPdf(data.latex, data.filename);
          const url = URL.createObjectURL(pdfBlob);
          
          // Cleanup old URL
          if (pdfUrlRef.current) {
            URL.revokeObjectURL(pdfUrlRef.current);
          }
          
          pdfUrlRef.current = url;
          setPdfUrl(url);
        } catch (error) {
          console.error('Failed to compile PDF for preview:', error);
          toast.error('Failed to generate PDF preview');
        }
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : 'Failed to load resume';
        toast.error(errorMessage);
        if (errorMessage.includes('Invalid admin password') || errorMessage.includes('not found')) {
          router.push('/admin');
        }
      } finally {
        setIsLoading(false);
      }
    };

    if (password) {
      loadResume();
    }
  }, [resumeId, password, router, checkAdminSessionTimeout, updateAdminSessionTimestamp]);

  // Cleanup PDF URL on unmount
  useEffect(() => {
    return () => {
      if (pdfUrlRef.current) {
        URL.revokeObjectURL(pdfUrlRef.current);
      }
    };
  }, []);

  const handleDownload = async (format: 'pdf' | 'latex') => {
    if (!password || !resume) return;

    // Check session timeout before action
    if (!checkAdminSessionTimeout()) {
      return;
    }

    try {
      const blob = await downloadResume(resume.resume_id, format, password);
      updateAdminSessionTimestamp(); // Update timestamp on action
      
      // Create download link
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = format === 'pdf' 
        ? resume.filename 
        : resume.filename.replace('.pdf', '.tex');
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      
      toast.success(`Downloaded ${format.toUpperCase()} successfully`);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to download';
      toast.error(errorMessage);
      if (errorMessage.includes('Invalid admin password')) {
        router.push('/admin');
      }
    }
  };

  const handleDelete = async () => {
    if (!password || !resume) return;
    
    // Check session timeout before action
    if (!checkAdminSessionTimeout()) {
      return;
    }
    
    if (!confirm(`Are you sure you want to delete the resume for ${resume.first_name} ${resume.last_name}? This action cannot be undone.`)) {
      return;
    }

    setIsDeleting(true);
    try {
      await deleteResume(resume.resume_id, password);
      updateAdminSessionTimestamp(); // Update timestamp on action
      toast.success('Resume deleted successfully');
      router.push('/admin');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to delete';
      toast.error(errorMessage);
      if (errorMessage.includes('Invalid admin password')) {
        router.push('/admin');
      }
    } finally {
      setIsDeleting(false);
    }
  };

  const formatDate = (dateString: string) => {
    try {
      const date = new Date(dateString);
      return date.toLocaleString();
    } catch {
      return dateString;
    }
  };

  if (!password) {
    return (
      <div className="container mx-auto py-8 max-w-6xl">
        <Card>
          <CardContent className="pt-6">
            <p className="text-muted-foreground">Redirecting to admin login...</p>
          </CardContent>
        </Card>
      </div>
    );
  }

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
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-3xl font-bold">
            {resume.first_name} {resume.last_name}
          </h1>
          <p className="text-muted-foreground mt-2">
            Saved: {formatDate(resume.created_at)}
          </p>
          <p className="text-sm text-muted-foreground mt-1">
            ID: {resume.resume_id}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={() => handleDownload('pdf')}
            variant="outline"
          >
            Download PDF
          </Button>
          <Button
            onClick={() => handleDownload('latex')}
            variant="outline"
          >
            Download LaTeX
          </Button>
          <Button
            onClick={handleDelete}
            variant="destructive"
            disabled={isDeleting}
            title="Delete from Redis (backend database)"
          >
            {isDeleting ? 'Deleting...' : 'Delete from Redis'}
          </Button>
          <Button
            onClick={() => router.push('/admin')}
            variant="outline"
          >
            Back to List
          </Button>
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
          <LatexEditor
            value={resume.latex}
            onChange={() => {}} // Read-only
            readOnly={true}
            height="600px"
          />
        </CardContent>
      </Card>
    </div>
  );
}

