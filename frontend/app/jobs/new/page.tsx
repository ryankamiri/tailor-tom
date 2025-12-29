'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { JobForm } from '@/components/jobs/job-form';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { createOptimizationJob } from '@/lib/api';
import { getSettings, getResumeLatex, saveJob, canCreateNewJob, StoredJob } from '@/lib/storage';
import { requestNotificationPermission } from '@/lib/notifications';
import { toast } from 'sonner';

export default function NewJobPage() {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (companyName: string, jobDescription: string) => {
    setIsLoading(true);
    setError(null);

    try {
      // Validate prerequisites
      const settings = getSettings();
      const resumeLatex = getResumeLatex();

      if (!resumeLatex) {
        const errorMessage = 'Please set up your resume LaTeX template in Settings first.';
        setError(errorMessage);
        toast.error(errorMessage);
        setIsLoading(false);
        return;
      }

      if (!settings.first_name || !settings.last_name) {
        const errorMessage = 'Please set your first and last name in Settings first.';
        setError(errorMessage);
        toast.error(errorMessage);
        setIsLoading(false);
        return;
      }

      // Check if we can create a new job
      const { canCreate, reason } = canCreateNewJob();
      if (!canCreate) {
        setError(reason || 'Cannot create new job');
        setIsLoading(false);
        return;
      }

      // Request notification permission
      await requestNotificationPermission();

      // Create optimization job
      const response = await createOptimizationJob({
        resume_latex: resumeLatex,
        job_description: jobDescription,
        target_pages: settings.target_pages,
        max_iterations: settings.max_iterations,
        max_bullet_lines: settings.max_bullet_lines,
        first_name: settings.first_name,
        last_name: settings.last_name,
        company_name: companyName,
      });

      // Save job to localStorage
      const newJob: StoredJob = {
        jobId: response.job_id,
        status: 'pending',
        createdAt: response.created_at,
        companyName: companyName,
        targetPages: settings.target_pages,
        originalLatex: resumeLatex,
      };
      saveJob(newJob);

      toast.success('Optimization job created successfully!');
      
      // Redirect to jobs page
      router.push('/jobs');
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to create optimization job';
      setError(errorMessage);
      toast.error(errorMessage);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="container mx-auto py-8 max-w-4xl">
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold">New Optimization Job</h1>
          <p className="text-muted-foreground mt-2">
            Paste a job description to optimize your resume for ATS compatibility
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Job Description</CardTitle>
            <CardDescription>
              Paste the full job description. The more context you provide, the better the optimization.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <JobForm onSubmit={handleSubmit} isLoading={isLoading} error={error} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

