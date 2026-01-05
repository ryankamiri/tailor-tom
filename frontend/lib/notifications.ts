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
 * Show a job completion notification (toast if tab focused, desktop notification if not).
 */
export function showJobCompleteNotification(
  companyName: string,
  jobId: string,
  isTabFocused: boolean
): void {
  const message = `${companyName || 'Your'} ATS Resume is done processing`;
  
  // Always show toast notification so user sees it when they return to the tab
  toast.success(message, {
    action: {
      label: 'View Results',
      onClick: () => {
        window.location.href = `/jobs/${jobId}`;
      },
    },
    duration: 5000,
  });
  
  // Also show desktop notification if tab is not focused and permission is granted
  if (!isTabFocused) {
    if (typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'granted') {
      try {
        const notification = new Notification('✅ Resume Optimization Complete', {
          body: `${message}. Click to view results.`,
          icon: '/favicon.ico',
          badge: '/favicon.ico',
          tag: `job-${jobId}`, // Prevent duplicate notifications for the same job
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
}

/**
 * Show a job failure notification (toast if tab focused, desktop notification if not).
 */
export function showJobFailedNotification(
  companyName: string,
  jobId: string,
  errorMessage: string | null,
  isTabFocused: boolean
): void {
  const message = `${companyName || 'Your'} ATS Resume optimization failed`;
  const errorText = errorMessage ? `: ${errorMessage}` : '';
  
  // Always show toast notification so user sees it when they return to the tab
  toast.error(message + errorText, {
    action: {
      label: 'View Details',
      onClick: () => {
        window.location.href = `/jobs/${jobId}`;
      },
    },
    duration: 8000, // Longer duration for errors
  });
  
  // Also show desktop notification if tab is not focused and permission is granted
  if (!isTabFocused) {
    if (typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'granted') {
      try {
        const notification = new Notification('❌ Resume Optimization Failed', {
          body: `${message}${errorText}. Click to view details.`,
          icon: '/favicon.ico',
          badge: '/favicon.ico',
          tag: `job-${jobId}-failed`, // Prevent duplicate notifications for the same job
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
}

/**
 * Check if the browser tab is currently focused.
 */
export function isTabFocused(): boolean {
  if (typeof window === 'undefined') return false;
  return document.hasFocus();
}

