'use client';

import { useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/auth-context';
import { Loader2 } from 'lucide-react';

/**
 * OAuth callback page.
 *
 * The backend redirects here with tokens in the URL fragment:
 *   /auth/callback#access_token=...&refresh_token=...
 *
 * We extract them, call `login()` from AuthContext, and redirect to
 * the home page (or wherever the user came from).
 */
export default function AuthCallbackPage() {
  const router = useRouter();
  const { login } = useAuth();
  const handled = useRef(false);

  useEffect(() => {
    // Prevent double-execution in React strict mode
    if (handled.current) return;
    handled.current = true;

    const hash = window.location.hash.substring(1); // strip leading '#'
    const params = new URLSearchParams(hash);
    const accessToken = params.get('access_token');
    const refreshToken = params.get('refresh_token');

    if (!accessToken || !refreshToken) {
      // No tokens — something went wrong; send to login.
      router.replace('/login');
      return;
    }

    // Clear tokens from the URL to prevent leaking them in browser history
    window.history.replaceState(null, '', '/auth/callback');

    login(accessToken, refreshToken).then(() => {
      router.replace('/');
    });
  }, [login, router]);

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="flex flex-col items-center gap-3 text-muted-foreground">
        <Loader2 className="h-8 w-8 animate-spin" />
        <p className="text-sm">Signing you in...</p>
      </div>
    </div>
  );
}
