/**
 * Shared formatting utilities for dates and currency.
 */

/**
 * Format an ISO date string for local display. Returns fallback on invalid input.
 */
export function formatLocalDateSafe(iso: string, fallback = ''): string {
  try {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return fallback;
    return date.toLocaleString();
  } catch {
    return fallback;
  }
}

/**
 * Format USD for display: 2 decimals when >= 1, 4 decimals otherwise.
 */
export function formatUsdCompact(usd: number): string {
  if (usd >= 1) return `$${usd.toFixed(2)}`;
  return `$${usd.toFixed(4)}`;
}
