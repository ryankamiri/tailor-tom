/** Notification helpers for TailorTom. */

import { toast } from 'sonner';

/**
 * Request notification permission from the user.
 */
export async function requestNotificationPermission(): Promise<boolean> {
  if (typeof window === 'undefined' || !('Notification' in window)) {
    return false;
  }
  
  if (Notification.permission === 'granted') {
    return true;
  }
  
  if (Notification.permission !== 'denied') {
    const permission = await Notification.requestPermission();
    return permission === 'granted';
  }
  
  return false;
}

/**
 * Show a job completion notification.
 * Always shows both a toast and a desktop notification (if permission granted).
 * Uses stable IDs/tags to prevent duplicate notifications.
 */
export function showJobCompleteNotification(
  companyName: string,
  jobId: string,
): void {
  const message = `${companyName || 'Your'} ATS Resume is done processing`;
  
  // Always show toast notification (use stable ID to prevent duplicates)
  toast.success(message, {
    id: `job-complete-${jobId}`,
    action: {
      label: 'View Results',
      onClick: () => {
        window.location.href = `/jobs/${jobId}`;
      },
    },
    duration: 10000,
  });
  
  // Always try desktop notification (tag prevents duplicates across calls)
  if (typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'granted') {
    try {
      const notification = new Notification('Resume Optimization Complete', {
        body: `${message}. Click to view results.`,
        icon: '/favicon.ico',
        badge: '/favicon.ico',
        tag: `job-${jobId}`, // Prevents duplicate desktop notifications for same job
        requireInteraction: false,
      });
      
      notification.onclick = () => {
        window.focus();
        window.location.href = `/jobs/${jobId}`;
        notification.close();
      };
      
      // Auto-close notification after 10 seconds
      setTimeout(() => {
        notification.close();
      }, 10000);
    } catch {
      // Silently fail - toast is already shown
    }
  }
}

/**
 * Show a job failure notification.
 * Always shows both a toast and a desktop notification (if permission granted).
 * Uses stable IDs/tags to prevent duplicate notifications.
 */
export function showJobFailedNotification(
  companyName: string,
  jobId: string,
  errorMessage: string | null,
): void {
  const message = `${companyName || 'Your'} ATS Resume optimization failed`;
  const errorText = errorMessage ? `: ${errorMessage}` : '';
  
  // Always show toast notification (use stable ID to prevent duplicates)
  toast.error(message + errorText, {
    id: `job-failed-${jobId}`,
    action: {
      label: 'View Details',
      onClick: () => {
        window.location.href = `/jobs/${jobId}`;
      },
    },
    duration: 10000,
  });
  
  // Always try desktop notification (tag prevents duplicates across calls)
  if (typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'granted') {
    try {
      const notification = new Notification('Resume Optimization Failed', {
        body: `${message}${errorText}. Click to view details.`,
        icon: '/favicon.ico',
        badge: '/favicon.ico',
        tag: `job-${jobId}-failed`, // Prevents duplicate desktop notifications for same job
        requireInteraction: false,
      });
      
      notification.onclick = () => {
        window.focus();
        window.location.href = `/jobs/${jobId}`;
        notification.close();
      };
      
        // Auto-close notification after 15 seconds (longer for errors)
        setTimeout(() => {
          notification.close();
        }, 15000);
    } catch {
      // Silently fail - toast is already shown
    }
  }
}

/**
 * Check if the browser tab is currently focused.
 * @deprecated Not used by notification functions (they always show both toast and desktop).
 * Kept for backwards compatibility with any code that still imports it.
 */
export function isTabFocused(): boolean {
  if (typeof window === 'undefined') return false;
  return document.hasFocus();
}
