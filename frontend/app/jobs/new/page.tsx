'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { JobForm } from '@/components/jobs/job-form';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { createOptimizationJob } from '@/lib/api';
import { requestNotificationPermission } from '@/lib/notifications';
import { toast } from 'sonner';
import { DailyLimitBadge } from '@/components/jobs/daily-limit-badge';
import { AlertCircle } from 'lucide-react';
import { RequireAuth } from '@/components/layout/require-auth';
import { useAuth } from '@/contexts/auth-context';
import { parseTargetPages } from '@/lib/constants';

function NewJobContent() {
  const router = useRouter();
  const { user, refreshUser } = useAuth();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dailyLimitRemaining = user?.daily_limit_remaining ?? 0;
  const canCreateByDailyLimit = dailyLimitRemaining > 0;
  const canCreate = canCreateByDailyLimit;
  const dailyLimitReason =
    !canCreateByDailyLimit && user
      ? `Daily limit reached. You have ${user.daily_completions_today} completed and ${user.active_jobs_count} pending/processing jobs (limit: ${user.daily_job_limit}). The limit resets at midnight UTC.`
      : null;

  const handleSubmit = async (companyName: string, jobDescription: string) => {
    setIsLoading(true);
    setError(null);

    try {
      if (!user) {
        setError('Not authenticated');
        setIsLoading(false);
        return;
      }

      const resumeLatex = user.resume_latex;
      if (!resumeLatex) {
        const errorMessage = 'Please set up your resume LaTeX template in Settings first.';
        setError(errorMessage);
        toast.error(errorMessage);
        setIsLoading(false);
        return;
      }

      if (!canCreate) {
        setError(dailyLimitReason || 'Cannot create new job');
        setIsLoading(false);
        return;
      }

      await requestNotificationPermission();

      const targetPages = parseTargetPages(user.target_pages);

      await createOptimizationJob({
        resume_latex: resumeLatex,
        job_description: jobDescription,
        target_pages: targetPages,
        max_iterations: user.max_iterations,
        max_bullet_lines: user.max_bullet_lines,
        first_name: user.first_name || '',
        last_name: user.last_name || '',
        company_name: companyName,
      });

      await refreshUser();
      toast.success('Optimization job created successfully!');
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
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">New Optimization Job</h1>
            <p className="text-muted-foreground mt-2">
              Paste a job description to optimize your resume for ATS compatibility
            </p>
          </div>
          <DailyLimitBadge />
        </div>

        {!canCreateByDailyLimit && user && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Daily Limit Reached</AlertTitle>
            <AlertDescription>
              {dailyLimitReason}
            </AlertDescription>
          </Alert>
        )}

        <Card>
          <CardHeader>
            <CardTitle>Job Description</CardTitle>
            <CardDescription>
              Paste the full job description. The more context you provide, the better the optimization.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <JobForm
              onSubmit={handleSubmit}
              isLoading={isLoading}
              error={error}
              disabled={!canCreate}
            />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default function NewJobPage() {
  return (
    <RequireAuth>
      <NewJobContent />
    </RequireAuth>
  );
}
