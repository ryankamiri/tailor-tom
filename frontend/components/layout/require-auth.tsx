'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/auth-context';
import { Loader2 } from 'lucide-react';

interface RequireAuthProps {
  children: React.ReactNode;
  /** If true, additionally checks that the user is an admin. */
  requireAdmin?: boolean;
}

/**
 * Wrapper component that redirects unauthenticated users to /login.
 * Renders a loading spinner while the auth state is being resolved.
 */
export function RequireAuth({ children, requireAdmin = false }: RequireAuthProps) {
  const { user, isAuthenticated, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!isAuthenticated) {
      router.replace('/login');
      return;
    }
    if (requireAdmin && user && !user.is_admin) {
      router.replace('/');
    }
  }, [loading, isAuthenticated, requireAdmin, user, router]);

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!isAuthenticated) return null;
  if (requireAdmin && user && !user.is_admin) return null;

  return <>{children}</>;
}
