'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';

export interface JobFormProps {
  onSubmit: (companyName: string, jobDescription: string) => void;
  isLoading?: boolean;
  error?: string | null;
}

export function JobForm({ onSubmit, isLoading = false, error }: JobFormProps) {
  const [companyName, setCompanyName] = useState('');
  const [jobDescription, setJobDescription] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (companyName.trim() && jobDescription.trim().length >= 50) {
      onSubmit(companyName.trim(), jobDescription.trim());
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="company-name">Company Name</Label>
        <Input
          id="company-name"
          placeholder="e.g., Google, Microsoft, Amazon"
          value={companyName}
          onChange={(e) => setCompanyName(e.target.value)}
          required
        />
        <p className="text-sm text-muted-foreground">
          Enter the company name for this job application
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="job-description">Job Description</Label>
        <Textarea
          id="job-description"
          placeholder="Paste the job description here..."
          value={jobDescription}
          onChange={(e) => setJobDescription(e.target.value)}
          rows={15}
          className="font-mono text-sm resize-none overflow-y-auto"
          style={{ maxHeight: '500px' }}
        />
        <p className="text-sm text-muted-foreground">
          Minimum 50 characters required. Paste the full job description for best results.
        </p>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Button
        type="submit"
        disabled={isLoading || !companyName.trim() || jobDescription.trim().length < 50}
        className="w-full"
      >
        {isLoading ? 'Processing...' : 'Optimize Resume'}
      </Button>
    </form>
  );
}

