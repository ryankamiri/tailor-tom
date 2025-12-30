'use client';

import { SettingsForm } from '@/components/settings/settings-form';

export default function SettingsPage() {
  return (
    <div className="container mx-auto py-8 max-w-6xl">
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold">Settings</h1>
          <p className="text-muted-foreground mt-2">
            Configure your resume template and optimization preferences
          </p>
        </div>
        <SettingsForm />
      </div>
    </div>
  );
}

