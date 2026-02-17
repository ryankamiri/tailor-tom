'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import type { UserProfile } from '@/lib/api';
import { fetchMe } from '@/lib/api';
import {
  clearTokens,
  isLoggedIn as tokenIsPresent,
  storeTokens,
} from '@/lib/auth';

// ---------------------------------------------------------------------------
// Context shape
// ---------------------------------------------------------------------------

interface AuthContextValue {
  /** The authenticated user, or null when logged-out / loading. */
  user: UserProfile | null;
  /** True while the initial profile fetch is in-flight. */
  loading: boolean;
  /** Whether the user is authenticated. */
  isAuthenticated: boolean;
  /** Call after receiving tokens from the OAuth callback. */
  login: (accessToken: string, refreshToken: string) => Promise<void>;
  /** Clear tokens and redirect to /login. */
  logout: () => void;
  /** Re-fetch the user profile from the server. */
  refreshUser: () => Promise<void>;
  /** Set user from an already-fetched profile (e.g. PATCH /auth/me response). Avoids extra GET. */
  setUserFromProfile: (profile: UserProfile) => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  // -----------------------------------------------------------------------
  // Bootstrap: if a refresh token exists, try to load the user profile.
  // -----------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      if (!tokenIsPresent()) {
        setLoading(false);
        return;
      }

      try {
        const profile = await fetchMe();
        if (!cancelled) setUser(profile);
      } catch {
        // Token expired / invalid — clean up silently.
        clearTokens();
        if (!cancelled) setUser(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  // -----------------------------------------------------------------------
  // login — store tokens then fetch the profile
  // -----------------------------------------------------------------------
  const login = useCallback(async (access: string, refresh: string) => {
    storeTokens(access, refresh);
    try {
      const profile = await fetchMe();
      setUser(profile);
    } catch {
      clearTokens();
      setUser(null);
    }
  }, []);

  // -----------------------------------------------------------------------
  // logout
  // -----------------------------------------------------------------------
  const logout = useCallback(() => {
    clearTokens();
    setUser(null);
    if (typeof window !== 'undefined') {
      window.location.href = '/login';
    }
  }, []);

  // -----------------------------------------------------------------------
  // refreshUser — re-fetch profile from server
  // -----------------------------------------------------------------------
  const refreshUser = useCallback(async () => {
    try {
      const profile = await fetchMe();
      setUser(profile);
    } catch {
      // If fetching fails with auth error, authFetch already handles redirect
    }
  }, []);

  // -----------------------------------------------------------------------
  // setUserFromProfile — set user from mutation response (avoids extra GET)
  // -----------------------------------------------------------------------
  const setUserFromProfile = useCallback((profile: UserProfile) => {
    setUser(profile);
  }, []);

  // -----------------------------------------------------------------------
  // Memoised value
  // -----------------------------------------------------------------------
  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      isAuthenticated: user !== null,
      login,
      logout,
      refreshUser,
      setUserFromProfile,
    }),
    [user, loading, login, logout, refreshUser, setUserFromProfile],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === undefined) {
    throw new Error('useAuth must be used within an <AuthProvider>');
  }
  return ctx;
}
