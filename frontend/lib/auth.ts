/**
 * Token storage helpers and authenticated fetch wrapper.
 *
 * Access tokens are stored in memory (module-level variable) for XSS
 * resilience.  Refresh tokens live in localStorage so they survive
 * page reloads.
 *
 * `authFetch` transparently adds the Bearer header and retries once
 * with a fresh access token when the backend returns 401.  If the
 * refresh itself fails the user is logged out.
 */

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/+$/, '');

const REFRESH_TOKEN_KEY = 'tailortom:refresh_token';

// ---------------------------------------------------------------------------
// In-memory access token
// ---------------------------------------------------------------------------

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

// ---------------------------------------------------------------------------
// Refresh token (localStorage)
// ---------------------------------------------------------------------------

export function getRefreshToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setRefreshToken(token: string | null): void {
  if (typeof window === 'undefined') return;
  if (token) {
    localStorage.setItem(REFRESH_TOKEN_KEY, token);
  } else {
    localStorage.removeItem(REFRESH_TOKEN_KEY);
  }
}

// ---------------------------------------------------------------------------
// Login / Logout helpers
// ---------------------------------------------------------------------------

/**
 * Persist both tokens after a successful login (OAuth callback).
 */
export function storeTokens(access: string, refresh: string): void {
  setAccessToken(access);
  setRefreshToken(refresh);
}

/**
 * Clear all auth state.  Called when the user explicitly logs out or
 * when a token refresh fails (session expired).
 */
export function clearTokens(): void {
  setAccessToken(null);
  setRefreshToken(null);
}

export function isLoggedIn(): boolean {
  // We consider the user "logged in" if we have a refresh token.
  // The access token may be null (expired); authFetch will refresh it.
  return getRefreshToken() !== null;
}

// ---------------------------------------------------------------------------
// Refresh access token
// ---------------------------------------------------------------------------

/** In-flight refresh promise — deduplicated so concurrent 401s share one call. */
let refreshPromise: Promise<string | null> | null = null;

/**
 * Exchange the stored refresh token for a new access token.
 * Returns the new access token, or null if refresh failed.
 */
async function refreshAccessToken(): Promise<string | null> {
  const refresh = getRefreshToken();
  if (!refresh) return null;

  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    });

    if (!res.ok) {
      // Refresh token is invalid or expired — force logout.
      clearTokens();
      return null;
    }

    const data = await res.json();
    const newAccess: string = data.access_token;
    setAccessToken(newAccess);
    return newAccess;
  } catch {
    // Network error during refresh — force logout.
    clearTokens();
    return null;
  }
}

/**
 * Deduplicated refresh: if a refresh is already in-flight, piggyback
 * on its result instead of firing a second request.
 */
function deduplicatedRefresh(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = refreshAccessToken().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

// ---------------------------------------------------------------------------
// authFetch — drop-in replacement for fetch() with automatic auth
// ---------------------------------------------------------------------------

/**
 * Authenticated fetch wrapper.
 *
 * 1. Attaches `Authorization: Bearer <access_token>` to every request.
 * 2. On 401, attempts a single token refresh and retries the request.
 * 3. If refresh fails, clears tokens and redirects to `/login`.
 *
 * Signature mirrors `window.fetch` so callers can swap trivially.
 */
export async function authFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  let token = getAccessToken();
  // After a full page reload, access token is in-memory so it's null. Refresh proactively
  // so the first request (e.g. GET /auth/me) is sent with a token instead of getting 401.
  if (!token && getRefreshToken()) {
    token = await deduplicatedRefresh();
    if (!token) {
      if (typeof window !== 'undefined') {
        window.location.href = '/login';
      }
      return new Response(JSON.stringify({ detail: 'Session expired' }), { status: 401 });
    }
  }

  const doFetch = (t: string | null) => {
    const headers = new Headers(init?.headers);
    if (t) {
      headers.set('Authorization', `Bearer ${t}`);
    }
    return fetch(input, { ...init, headers });
  };

  let res = await doFetch(token);

  if (res.status === 401) {
    const newToken = await deduplicatedRefresh();
    if (!newToken) {
      // Refresh failed — redirect to login.
      if (typeof window !== 'undefined') {
        window.location.href = '/login';
      }
      return res; // Return original 401 in SSR/edge cases
    }
    // Retry with the fresh token
    res = await doFetch(newToken);
  }

  return res;
}
