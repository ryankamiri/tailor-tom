'use client';

import { createContext, useCallback, useContext, useMemo, useSyncExternalStore } from 'react';

const STORAGE_KEY = 'tailortom:onboarding';

export interface OnboardingState {
  completed: boolean;
  resumeSaved: boolean;
  firstJobCreated: boolean;
}

const DEFAULT_STATE: OnboardingState = {
  completed: false,
  resumeSaved: false,
  firstJobCreated: false,
};

interface OnboardingContextValue {
  state: OnboardingState;
  markStep: (key: 'resumeSaved' | 'firstJobCreated') => void;
  dismiss: () => void;
}

const OnboardingContext = createContext<OnboardingContextValue>({
  state: DEFAULT_STATE,
  markStep: () => {},
  dismiss: () => {},
});

// ---------------------------------------------------------------------------
// External store wired to localStorage so all consumers re-render on change.
// ---------------------------------------------------------------------------

let listeners = new Set<() => void>();

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

function readState(): OnboardingState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_STATE;
    return { ...DEFAULT_STATE, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_STATE;
  }
}

function writeState(next: OnboardingState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // best effort
  }
  listeners.forEach((cb) => cb());
}

// Hydration-safe: always return DEFAULT on the server so SSR matches initial client render.
function getServerSnapshot(): OnboardingState {
  return DEFAULT_STATE;
}

// After hydration the real localStorage value is used.
// useSyncExternalStore guarantees no tearing.
let cachedClient: OnboardingState | null = null;

function getClientSnapshot(): OnboardingState {
  // Re-read from localStorage on every call (cheap — JSON.parse of ~80 bytes).
  // Cache reference identity so React can skip re-renders when nothing changed.
  const next = readState();
  if (
    cachedClient &&
    cachedClient.completed === next.completed &&
    cachedClient.resumeSaved === next.resumeSaved &&
    cachedClient.firstJobCreated === next.firstJobCreated
  ) {
    return cachedClient;
  }
  cachedClient = next;
  return next;
}

export function OnboardingProvider({ children }: { children: React.ReactNode }) {
  const state = useSyncExternalStore(subscribe, getClientSnapshot, getServerSnapshot);

  const markStep = useCallback((key: 'resumeSaved' | 'firstJobCreated') => {
    const current = readState();
    const next = { ...current, [key]: true };
    if (key === 'firstJobCreated') {
      next.completed = true;
    }
    writeState(next);
  }, []);

  const dismiss = useCallback(() => {
    const current = readState();
    writeState({ ...current, completed: true });
  }, []);

  const value = useMemo<OnboardingContextValue>(
    () => ({ state, markStep, dismiss }),
    [state, markStep, dismiss]
  );

  return (
    <OnboardingContext.Provider value={value}>
      {children}
    </OnboardingContext.Provider>
  );
}

export function useOnboarding() {
  return useContext(OnboardingContext);
}
