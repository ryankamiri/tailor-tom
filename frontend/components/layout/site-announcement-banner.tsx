'use client';

import Link from 'next/link';
import { useSyncExternalStore, useState } from 'react';
import { X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { getActiveSiteAnnouncement } from '@/lib/site-announcements';

function getDismissKey(announcementId: string): string {
  return `tailortom:announcement:dismissed:${announcementId}`;
}

// Hydration-safe: server and first client snapshot must match (false). After hydration, flip to true.
const clientReadyStore = {
  value: false,
  listeners: new Set<() => void>(),
  subscribe(cb: () => void) {
    clientReadyStore.listeners.add(cb);
    return () => clientReadyStore.listeners.delete(cb);
  },
  setReady() {
    if (clientReadyStore.value) return;
    clientReadyStore.value = true;
    clientReadyStore.listeners.forEach((f) => f());
  },
};

function getServerSnapshot(): boolean {
  return false;
}

function getClientSnapshot(): boolean {
  if (!clientReadyStore.value) {
    queueMicrotask(() => clientReadyStore.setReady());
  }
  return clientReadyStore.value;
}

/**
 * Do not read localStorage during render until isClientReady; gate via useSyncExternalStore to avoid hydration mismatch.
 */
export function SiteAnnouncementBanner() {
  const announcement = getActiveSiteAnnouncement();
  const [dismissedInSession, setDismissedInSession] = useState(false);
  const isClientReady = useSyncExternalStore(
    (cb) => clientReadyStore.subscribe(cb),
    getServerSnapshot,
    getClientSnapshot
  );

  let hidden = true;
  if (announcement && isClientReady && !dismissedInSession) {
    try {
      hidden = localStorage.getItem(getDismissKey(announcement.id)) === '1';
    } catch {
      hidden = false;
    }
  }

  const dismiss = () => {
    if (!announcement) return;
    try {
      localStorage.setItem(getDismissKey(announcement.id), '1');
    } catch {
      // Best effort write.
    }
    setDismissedInSession(true);
  };

  if (hidden || !announcement) {
    return null;
  }

  return (
    <div className="border-b border-primary/35 bg-primary/20 text-foreground shadow-sm">
      <div className="container mx-auto flex items-start justify-between gap-3 px-4 py-2">
        <div className="text-sm">
          <span className="font-semibold">{announcement.title}</span>{' '}
          <span>{announcement.message}</span>
          {announcement.ctaHref && announcement.ctaLabel && (
            <>
              {' '}
              <Link
                href={announcement.ctaHref}
                className="font-semibold text-foreground underline decoration-primary underline-offset-2 hover:opacity-80"
              >
                {announcement.ctaLabel}
              </Link>
            </>
          )}
        </div>

        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={dismiss}
          aria-label="Dismiss announcement"
          className="h-7 w-7 shrink-0 text-current hover:bg-primary/20"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
