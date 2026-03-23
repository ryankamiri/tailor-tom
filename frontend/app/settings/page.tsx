'use client';

import { SettingsForm } from '@/components/settings/settings-form';
import { RequireAuth } from '@/components/layout/require-auth';
import { useOnboarding } from '@/contexts/onboarding-context';
import { X } from 'lucide-react';

export default function SettingsPage() {
  const { state: onboarding, dismiss } = useOnboarding();
  const showWelcome = !onboarding.completed && !onboarding.resumeSaved;

  return (
    <RequireAuth>
      <div className="container mx-auto py-8 max-w-6xl">
        <div className="space-y-6">
          {showWelcome && (
            <div className="relative rounded-lg border border-primary/30 bg-primary/10 px-5 py-4">
              <button
                type="button"
                onClick={dismiss}
                aria-label="Dismiss"
                className="absolute top-3 right-3 inline-flex h-6 w-6 items-center justify-center rounded-md hover:bg-primary/20"
              >
                <X className="h-4 w-4" />
              </button>
              <p className="font-semibold">Welcome to TailorTom!</p>
              <p className="mt-1 text-sm text-muted-foreground">
                To get started, paste your resume LaTeX below (or upload a .docx file) and hit <strong>Save</strong>. Once saved, you can start optimizing your resume for any job description.
              </p>
            </div>
          )}
          <div>
            <h1 className="text-3xl font-bold">Settings</h1>
            <p className="text-muted-foreground mt-2">
              Configure your resume template and optimization preferences
            </p>
          </div>
          <SettingsForm />
        </div>
      </div>
    </RequireAuth>
  );
}
