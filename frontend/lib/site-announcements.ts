export interface SiteAnnouncement {
  id: string;
  title: string;
  message: string;
  ctaLabel?: string;
  ctaHref?: string;
  enabled?: boolean;
}

// Rotate announcements by adding a new entry and changing ACTIVE_SITE_ANNOUNCEMENT_ID.
export const SITE_ANNOUNCEMENTS: SiteAnnouncement[] = [
  {
    id: 'v2-launch-2026-02',
    title: 'TailorTom V2 is here!',
    message:
      'Create an account with Google and try our improved optimizer with DOCX compatibility.',
    ctaLabel: 'Try V2',
    ctaHref: '/login',
    enabled: true,
  },
];

export const ACTIVE_SITE_ANNOUNCEMENT_ID = 'v2-launch-2026-02';

export function getActiveSiteAnnouncement(): SiteAnnouncement | null {
  const announcement = SITE_ANNOUNCEMENTS.find(
    (item) => item.id === ACTIVE_SITE_ANNOUNCEMENT_ID && item.enabled !== false
  );
  return announcement ?? null;
}
