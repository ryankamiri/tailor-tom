'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { listAdminResumes, downloadResume, deleteResume } from '@/lib/api';
import { getCachedAdminResumes, saveCachedAdminResumes, CachedResume } from '@/lib/storage';
import { ADMIN_SESSION_TIMEOUT_MS } from '@/lib/constants';
import { toast } from 'sonner';

interface Resume {
  resume_id: string;
  first_name: string;
  last_name: string;
  created_at: string;
  filename: string;
}

export default function AdminPage() {
  const router = useRouter();
  // Initialize password from sessionStorage synchronously to prevent flash
  const [password, setPassword] = useState(() => {
    if (typeof window !== 'undefined') {
      const storedPassword = sessionStorage.getItem('admin_password');
      if (storedPassword) {
        // Check if session is still valid synchronously
        const timestamp = sessionStorage.getItem('admin_session_timestamp');
        if (timestamp) {
          const sessionAge = Date.now() - parseInt(timestamp, 10);
          if (sessionAge <= ADMIN_SESSION_TIMEOUT_MS) {
            return storedPassword;
          } else {
            // Session expired, clear it
            sessionStorage.removeItem('admin_password');
            sessionStorage.removeItem('admin_session_timestamp');
          }
        }
      }
    }
    return '';
  });
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true); // Start with loading=true to prevent flash
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const updateAdminSessionTimestamp = useCallback(() => {
    sessionStorage.setItem('admin_session_timestamp', Date.now().toString());
  }, []);

  const checkAdminSessionTimeout = useCallback((): boolean => {
    const timestamp = sessionStorage.getItem('admin_session_timestamp');
    if (!timestamp) {
      return false; // No timestamp means not logged in
    }
    
    const sessionAge = Date.now() - parseInt(timestamp, 10);
    if (sessionAge > ADMIN_SESSION_TIMEOUT_MS) {
      // Session expired
      sessionStorage.removeItem('admin_password');
      sessionStorage.removeItem('admin_session_timestamp');
      setIsAuthenticated(false);
      setPassword('');
      toast.error('Admin session expired. Please log in again.');
      return false;
    }
    
    return true; // Session is valid
  }, []);

  const handleAutoLogin = useCallback(async (storedPassword: string) => {
    // Check if session has expired
    if (!checkAdminSessionTimeout()) {
      return; // Session expired, don't auto-login
    }

    setIsLoading(true);
    try {
      const data = await listAdminResumes(storedPassword);
      const redisResumes = data.resumes;
      
      // Get cached resumes from local storage
      const cachedResumes = getCachedAdminResumes();
      
      // Merge: combine Redis + cached, remove duplicates by resume_id
      // Use CachedResume internally to preserve LaTeX/user_id
      const resumeMap = new Map<string, CachedResume>();
      
      // Add cached resumes first
      cachedResumes.forEach((resume: CachedResume) => {
        resumeMap.set(resume.resume_id, resume);
      });
      
      // Add Redis resumes (override cached if same ID)
      // But preserve LaTeX/user_id from cache if they exist
      redisResumes.forEach((resume: Resume) => {
        const existingCached = resumeMap.get(resume.resume_id);
        if (existingCached) {
          // Preserve LaTeX and user_id from cache
          resumeMap.set(resume.resume_id, {
            ...resume,
            ...(existingCached.latex && { latex: existingCached.latex }),
            ...(existingCached.user_id && { user_id: existingCached.user_id }),
          });
        } else {
          resumeMap.set(resume.resume_id, resume);
        }
      });
      
      // Convert to array and sort chronologically (newest first)
      const mergedResumes = Array.from(resumeMap.values()).sort((a, b) => {
        const dateA = new Date(a.created_at).getTime();
        const dateB = new Date(b.created_at).getTime();
        return dateB - dateA; // Newest first
      });
      
      // Update state with merged resumes (cast to Resume[] for display)
      setResumes(mergedResumes as Resume[]);
      
      // Update cache with merged data - save as CachedResume[]
      saveCachedAdminResumes(mergedResumes);
      
      setIsAuthenticated(true);
      updateAdminSessionTimestamp(); // Update timestamp on successful login
    } catch {
      // Password might be invalid, clear it
      sessionStorage.removeItem('admin_password');
      sessionStorage.removeItem('admin_session_timestamp');
      setPassword('');
      setIsAuthenticated(false);
    } finally {
      setIsLoading(false);
    }
  }, [checkAdminSessionTimeout, updateAdminSessionTimestamp]);

  // Restore authentication from sessionStorage on mount
  useEffect(() => {
    // If password was initialized from sessionStorage, try to auto-login
    if (password) {
      handleAutoLogin(password);
    } else {
      // No valid session, stop loading
      setIsLoading(false);
    }

    // Set up periodic session timeout check (every minute)
    const timeoutCheckInterval = setInterval(() => {
      if (isAuthenticated) {
        if (!checkAdminSessionTimeout()) {
          // Session expired, state already updated by checkAdminSessionTimeout
        }
      }
    }, 60000); // Check every minute

    return () => {
      clearInterval(timeoutCheckInterval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Only run once on mount - password is initialized synchronously

  const handleLogin = async () => {
    if (!password.trim()) {
      toast.error('Please enter a password');
      return;
    }

    setIsLoading(true);
    try {
      const data = await listAdminResumes(password);
      const redisResumes = data.resumes;
      
      // Get cached resumes from local storage
      const cachedResumes = getCachedAdminResumes();
      
      // Merge: combine Redis + cached, remove duplicates by resume_id
      // Use CachedResume internally to preserve LaTeX/user_id
      const resumeMap = new Map<string, CachedResume>();
      
      // Add cached resumes first
      cachedResumes.forEach((resume: CachedResume) => {
        resumeMap.set(resume.resume_id, resume);
      });
      
      // Add Redis resumes (override cached if same ID)
      // But preserve LaTeX/user_id from cache if they exist
      redisResumes.forEach((resume: Resume) => {
        const existingCached = resumeMap.get(resume.resume_id);
        if (existingCached) {
          // Preserve LaTeX and user_id from cache
          resumeMap.set(resume.resume_id, {
            ...resume,
            ...(existingCached.latex && { latex: existingCached.latex }),
            ...(existingCached.user_id && { user_id: existingCached.user_id }),
          });
        } else {
          resumeMap.set(resume.resume_id, resume);
        }
      });
      
      // Convert to array and sort chronologically (newest first)
      const mergedResumes = Array.from(resumeMap.values()).sort((a, b) => {
        const dateA = new Date(a.created_at).getTime();
        const dateB = new Date(b.created_at).getTime();
        return dateB - dateA; // Newest first
      });
      
      // Update state with merged resumes (cast to Resume[] for display)
      setResumes(mergedResumes as Resume[]);
      
      // Update cache with merged data - save as CachedResume[]
      saveCachedAdminResumes(mergedResumes);
      
      setIsAuthenticated(true);
      // Store password in sessionStorage for use in detail pages
      sessionStorage.setItem('admin_password', password);
      updateAdminSessionTimestamp(); // Set session timestamp
      toast.success('Admin access granted');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to authenticate';
      toast.error(errorMessage);
      setIsAuthenticated(false);
      sessionStorage.removeItem('admin_password');
    } finally {
      setIsLoading(false);
    }
  };

  const handleRefresh = async (showToast: boolean = true) => {
    if (!password.trim()) return;
    
    // Check session timeout before action
    if (!checkAdminSessionTimeout()) {
      return;
    }
    
    setIsLoading(true);
    try {
      // Fetch from Redis
      const data = await listAdminResumes(password);
      const redisResumes = data.resumes;
      
      // Get cached resumes from local storage
      const cachedResumes = getCachedAdminResumes();
      
      // Merge: combine Redis + cached, remove duplicates by resume_id
      // Use CachedResume internally to preserve LaTeX/user_id
      const resumeMap = new Map<string, CachedResume>();
      
      // Add cached resumes first (they might be older but still valid)
      cachedResumes.forEach((resume: CachedResume) => {
        resumeMap.set(resume.resume_id, resume);
      });
      
      // Add Redis resumes (they override cached if same ID, ensuring latest data)
      // But preserve LaTeX/user_id from cache if they exist
      redisResumes.forEach((resume: Resume) => {
        const existingCached = resumeMap.get(resume.resume_id);
        if (existingCached) {
          // Preserve LaTeX and user_id from cache
          resumeMap.set(resume.resume_id, {
            ...resume,
            ...(existingCached.latex && { latex: existingCached.latex }),
            ...(existingCached.user_id && { user_id: existingCached.user_id }),
          });
        } else {
          resumeMap.set(resume.resume_id, resume);
        }
      });
      
      // Convert to array and sort chronologically (newest first)
      const mergedResumes = Array.from(resumeMap.values()).sort((a, b) => {
        const dateA = new Date(a.created_at).getTime();
        const dateB = new Date(b.created_at).getTime();
        return dateB - dateA; // Newest first
      });
      
      // Update state with merged resumes (cast to Resume[] for display)
      setResumes(mergedResumes as Resume[]);
      
      // Update cache with merged data (for next refresh) - save as CachedResume[]
      saveCachedAdminResumes(mergedResumes);
      
      updateAdminSessionTimestamp(); // Update timestamp on action
      if (showToast) {
        toast.success('Resume list refreshed');
      }
    } catch (error) {
      // On error, still show cached resumes if available
      const cachedResumes = getCachedAdminResumes();
      if (cachedResumes.length > 0) {
        setResumes(cachedResumes);
      }
      
      const errorMessage = error instanceof Error ? error.message : 'Failed to refresh';
      toast.error(errorMessage);
      if (errorMessage.includes('Invalid admin password')) {
        setIsAuthenticated(false);
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleDownload = async (resume: Resume, format: 'pdf' | 'latex') => {
    if (!password.trim()) return;

    // Check session timeout before action
    if (!checkAdminSessionTimeout()) {
      return;
    }

    try {
      const blob = await downloadResume(resume.resume_id, format, password);
      updateAdminSessionTimestamp(); // Update timestamp on action
      
      // Extract filename from Content-Disposition header or use resume filename
      let downloadFilename = format === 'pdf' 
        ? resume.filename 
        : resume.filename.replace('.pdf', '.tex');
      
      // Fallback: if filename is missing or just "resume", generate from resume data
      if (!downloadFilename || downloadFilename === 'resume.pdf' || downloadFilename === 'resume.tex') {
        const safeFirst = resume.first_name?.replace(/[^\w]/g, '').replace(/\b\w/g, l => l.toUpperCase()) || 'Unknown';
        const safeLast = resume.last_name?.replace(/[^\w]/g, '').replace(/\b\w/g, l => l.toUpperCase()) || 'Unknown';
        downloadFilename = format === 'pdf'
          ? `${safeFirst}_${safeLast}_resume.pdf`
          : `${safeFirst}_${safeLast}_resume.tex`;
      }
      
      // Create download link
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = downloadFilename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      
      toast.success(`Downloaded ${format.toUpperCase()} successfully`);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to download';
      toast.error(errorMessage);
      if (errorMessage.includes('Invalid admin password')) {
        setIsAuthenticated(false);
      }
    }
  };

  const handleDeleteFromRedis = async (resume: Resume) => {
    if (!password.trim()) return;
    
    // Check session timeout before action
    if (!checkAdminSessionTimeout()) {
      return;
    }
    
    if (!confirm(`Are you sure you want to delete the resume for ${resume.first_name} ${resume.last_name} from Redis? This action cannot be undone.`)) {
      return;
    }

    setDeletingId(resume.resume_id);
    try {
      await deleteResume(resume.resume_id, password);
      updateAdminSessionTimestamp(); // Update timestamp on action
      
      // DO NOT remove from local cache - local storage should remain independent
      // The cache will be preserved and can be merged back on refresh
      
      // Update state immediately (optimistic update) - remove from display
      setResumes(prevResumes => prevResumes.filter((r: Resume) => r.resume_id !== resume.resume_id));
      
      toast.success('Resume deleted from Redis successfully');
      // Refresh list silently (no toast) to sync with Redis
      // This will merge Redis (empty) + cached (still has the resume) = cached resume will show again
      await handleRefresh(false);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to delete';
      toast.error(errorMessage);
      if (errorMessage.includes('Invalid admin password')) {
        setIsAuthenticated(false);
      }
      // Refresh on error to restore state
      await handleRefresh(false);
    } finally {
      setDeletingId(null);
    }
  };

  const handleDeleteFromLocalStorage = (resume: Resume) => {
    if (!confirm(`Delete from Local Storage?\n\nThis will delete the resume for ${resume.first_name} ${resume.last_name} from your browser's local storage. This only affects your local browser, not the Redis database.\n\nThis action cannot be undone.`)) {
      return;
    }
    
    try {
      // Remove the specific resume from admin cache ONLY
      // This does NOT affect the user's settings resume (stored separately at 'tailortom:resume_latex')
      const cachedResumes = getCachedAdminResumes();
      const updatedCache = cachedResumes.filter((r: CachedResume) => r.resume_id !== resume.resume_id);
      saveCachedAdminResumes(updatedCache);
      
      // Update state to remove from display
      setResumes(prevResumes => prevResumes.filter((r: Resume) => r.resume_id !== resume.resume_id));
      
      toast.success('Resume deleted from admin cache successfully');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to delete from local storage';
      toast.error(errorMessage);
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

  // Show loading state while checking authentication
  if (isLoading) {
    return (
      <div className="container mx-auto py-8 max-w-md">
        <Card>
          <CardHeader>
            <Skeleton className="h-6 w-32" />
            <Skeleton className="h-4 w-48 mt-2" />
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Skeleton className="h-4 w-16" />
              <Skeleton className="h-10 w-full" />
            </div>
            <Skeleton className="h-10 w-full" />
          </CardContent>
        </Card>
      </div>
    );
  }
  
  if (!isAuthenticated) {
    return (
      <div className="container mx-auto py-8 max-w-md">
        <Card>
          <CardHeader>
            <CardTitle>Admin Panel</CardTitle>
            <CardDescription>Enter password to access saved resumes</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    handleLogin();
                  }
                }}
                placeholder="Enter admin password"
              />
            </div>
            <Button onClick={handleLogin} disabled={isLoading} className="w-full">
              {isLoading ? 'Authenticating...' : 'Access Admin Panel'}
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-8 max-w-6xl">
      <div className="space-y-6">
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold">Admin Panel</h1>
            <p className="text-muted-foreground mt-2">
              View and manage saved resumes
            </p>
          </div>
          <div className="flex gap-2">
            <Button onClick={() => handleRefresh(true)} disabled={isLoading} variant="outline">
              {isLoading ? 'Loading...' : 'Refresh'}
            </Button>
            <Button 
              onClick={() => {
                setIsAuthenticated(false);
                sessionStorage.removeItem('admin_password');
                sessionStorage.removeItem('admin_session_timestamp');
              }} 
              variant="outline"
            >
              Logout
            </Button>
          </div>
        </div>

        {resumes.length === 0 ? (
          <Card>
            <CardContent className="py-8 text-center text-muted-foreground">
              No resumes found
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-4">
            {resumes.map((resume) => (
              <Card key={resume.resume_id}>
                <CardContent className="pt-6">
                  <div className="flex justify-between items-start">
                    <div className="space-y-1">
                      <h3 className="font-semibold text-lg">
                        {resume.first_name} {resume.last_name}
                      </h3>
                      <p className="text-sm text-muted-foreground">
                        Saved: {formatDate(resume.created_at)}
                      </p>
                      <p className="text-sm text-muted-foreground">
                        ID: {resume.resume_id}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        onClick={() => router.push(`/admin/resume/${resume.resume_id}`)}
                        variant="default"
                        size="sm"
                      >
                        View
                      </Button>
                      <Button
                        onClick={() => handleDownload(resume, 'pdf')}
                        variant="outline"
                        size="sm"
                      >
                        Download PDF
                      </Button>
                      <Button
                        onClick={() => handleDownload(resume, 'latex')}
                        variant="outline"
                        size="sm"
                      >
                        Download LaTeX
                      </Button>
                      <Button
                        onClick={() => handleDeleteFromLocalStorage(resume)}
                        variant="destructive"
                        size="sm"
                        title="Delete from admin's local storage"
                      >
                        Delete from Local Storage
                      </Button>
                      <Button
                        onClick={() => handleDeleteFromRedis(resume)}
                        variant="destructive"
                        size="sm"
                        disabled={deletingId === resume.resume_id}
                        title="Delete from Redis (backend database)"
                      >
                        {deletingId === resume.resume_id ? 'Deleting...' : 'Delete from Redis'}
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        <div className="text-sm text-muted-foreground text-center">
          Total: {resumes.length} resume{resumes.length !== 1 ? 's' : ''}
        </div>
      </div>
    </div>
  );
}

