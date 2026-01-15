'use client';

import { useState, useEffect } from 'react';
import { Badge } from '@/components/ui/badge';
import { canCreateJobWithinDailyLimit } from '@/lib/storage';
import { JOB_STORAGE_KEY } from '@/lib/constants';
import { AlertCircle, CheckCircle2 } from 'lucide-react';

export function DailyLimitBadge() {
  // State to force re-render when localStorage changes
  const [updateTrigger, setUpdateTrigger] = useState(0);
  
  // Listen for storage changes (including from other tabs/windows)
  useEffect(() => {
    const handleStorageChange = (e: StorageEvent) => {
      // Only react to changes in the jobs storage key
      if (e.key === JOB_STORAGE_KEY) {
        setUpdateTrigger(prev => prev + 1);
      }
    };
    
    // Listen for storage events from other tabs/windows
    window.addEventListener('storage', handleStorageChange);
    
    // Also listen for custom events (for same-tab updates)
    const handleCustomStorageChange = () => {
      setUpdateTrigger(prev => prev + 1);
    };
    
    // Custom event for same-tab updates
    window.addEventListener('localStorageChange', handleCustomStorageChange);
    
    return () => {
      window.removeEventListener('storage', handleStorageChange);
      window.removeEventListener('localStorageChange', handleCustomStorageChange);
    };
  }, []);
  
  // Re-read from localStorage on every render (will update when updateTrigger changes)
  // updateTrigger is used to force re-renders when localStorage changes
  const { completedToday, pendingAndProcessing, limit, remaining, canCreate } = canCreateJobWithinDailyLimit();
  
  // Use updateTrigger to satisfy linter (it's used to trigger re-renders via state updates)
  void updateTrigger;
  
  if (canCreate) {
    return (
      <Badge variant="outline" className="gap-1">
        <CheckCircle2 className="h-3 w-3" />
        {remaining} of {limit} jobs remaining today
        {pendingAndProcessing > 0 && ` (${pendingAndProcessing} pending)`}
      </Badge>
    );
  }
  
  // Show more detailed info when limit reached
  const totalUsed = completedToday + pendingAndProcessing;
  return (
    <Badge variant="destructive" className="gap-1">
      <AlertCircle className="h-3 w-3" />
      Daily limit reached ({totalUsed}/{limit})
      {pendingAndProcessing > 0 && ` (${pendingAndProcessing} pending)`}
    </Badge>
  );
}
