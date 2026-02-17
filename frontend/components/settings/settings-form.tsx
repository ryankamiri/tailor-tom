'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { LatexEditor } from '@/components/editor/latex-editor';
import { validateLatex, compileLatexToPdf, updateMe } from '@/lib/api';
import { MIN_BULLET_LINES, MAX_BULLET_LINES, TARGET_PAGES_OPTIONS, parseTargetPages } from '@/lib/constants';
import { toast } from 'sonner';
import { Loader2, FileUp, HelpCircle } from 'lucide-react';
import { DocxUploadDialog } from '@/components/settings/docx-upload-dialog';
import { useAuth } from '@/contexts/auth-context';

export function SettingsForm() {
  const { user, setUserFromProfile } = useAuth();

  // Local form state — initialised from user profile once loaded
  const [targetPages, setTargetPages] = useState(user?.target_pages ?? 1);
  const [maxIterations, setMaxIterations] = useState(user?.max_iterations ?? 3);
  const [maxBulletLines, setMaxBulletLines] = useState(user?.max_bullet_lines ?? 2);
  const [latex, setLatex] = useState(user?.resume_latex ?? '');

  const [isSaving, setIsSaving] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [isInitialLoad, setIsInitialLoad] = useState(true);
  const [pdfBlobUrl, setPdfBlobUrl] = useState<string | null>(null);
  const [isCompiling, setIsCompiling] = useState(false);
  const [docxDialogOpen, setDocxDialogOpen] = useState(false);
  const initialCompileDoneRef = useRef(false);
  const autoSaveRef = useRef<NodeJS.Timeout | null>(null);

  // Sync form state when user profile loads / changes
  useEffect(() => {
    if (!user) return;
    setTargetPages(user.target_pages);
    setMaxIterations(user.max_iterations);
    setMaxBulletLines(user.max_bullet_lines);
    setLatex(user.resume_latex ?? '');
    setIsInitialLoad(false);
  }, [user]);

  // Clean up blob URL on unmount
  useEffect(() => {
    return () => {
      if (pdfBlobUrl) URL.revokeObjectURL(pdfBlobUrl);
    };
  }, [pdfBlobUrl]);

  const compileAndSetPdf = useCallback(async (latexSource: string) => {
    if (!latexSource.trim()) return;
    setIsCompiling(true);
    try {
      const blob = await compileLatexToPdf(latexSource);
      setPdfBlobUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return URL.createObjectURL(blob);
      });
    } catch {
      // Silent fail; user can save to retry
    } finally {
      setIsCompiling(false);
    }
  }, []);

  // Compile PDF once on initial load when there is saved LaTeX
  useEffect(() => {
    if (isInitialLoad || !latex.trim() || initialCompileDoneRef.current) return;
    initialCompileDoneRef.current = true;
    compileAndSetPdf(latex);
  }, [isInitialLoad, latex, compileAndSetPdf]);

  // Auto-save optimization settings (debounced 800ms).
  // We ONLY auto-save the lightweight numeric settings — not the LaTeX template
  // which goes through the explicit Save button with validation.
  useEffect(() => {
    if (isInitialLoad) return;

    if (autoSaveRef.current) clearTimeout(autoSaveRef.current);

    autoSaveRef.current = setTimeout(async () => {
      try {
        const updated = await updateMe({
          target_pages: targetPages,
          max_iterations: maxIterations,
          max_bullet_lines: maxBulletLines,
        });
        setUserFromProfile(updated);
      } catch (err) {
        console.error('Auto-save settings error:', err);
      }
    }, 800);

    return () => {
      if (autoSaveRef.current) clearTimeout(autoSaveRef.current);
    };
  }, [targetPages, maxIterations, maxBulletLines, isInitialLoad, setUserFromProfile]);

  // -----------------------------------------------------------------------
  // Explicit save — validates + persists LaTeX template
  // -----------------------------------------------------------------------
  const handleSave = async () => {
    setIsSaving(true);
    setIsValidating(false);

    try {
      // Validate LaTeX before saving
      if (latex.trim()) {
        setIsValidating(true);
        try {
          await validateLatex(latex);
          setIsValidating(false);
        } catch (validateError) {
          setIsValidating(false);
          const errorMessage =
            validateError instanceof Error
              ? validateError.message
              : 'Invalid LaTeX syntax';
          toast.error(`Cannot save: ${errorMessage}`);
          setIsSaving(false);
          return;
        }
      }

      // Persist to backend; use returned profile so we don't need a second GET
      const updated = await updateMe({ resume_latex: latex });
      setUserFromProfile(updated);

      toast.success('LaTeX template saved successfully!');

      // Compile and show PDF preview after successful save
      if (latex.trim()) {
        await compileAndSetPdf(latex);
      }
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : 'Failed to save template';
      toast.error(errorMessage);
    } finally {
      setIsSaving(false);
      setIsValidating(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Optimization Settings</CardTitle>
          <CardDescription>Configure default optimization parameters</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <div className="flex items-center gap-1.5">
                <Label htmlFor="target-pages">Target Pages</Label>
                <span
                  className="inline-flex text-muted-foreground hover:text-foreground cursor-help"
                  title="Desired number of pages for the optimized resume (1-3)."
                >
                  <HelpCircle className="h-3.5 w-3.5" />
                </span>
              </div>
              <Select
                value={targetPages.toString()}
                onValueChange={(v) => setTargetPages(parseTargetPages(v))}
              >
                <SelectTrigger id="target-pages">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TARGET_PAGES_OPTIONS.map((n) => (
                    <SelectItem key={n} value={n.toString()}>
                      {n} page{n !== 1 ? 's' : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <div className="flex items-center gap-1.5">
                <Label htmlFor="max-iterations">Optimization search depth</Label>
                <span
                  className="inline-flex text-muted-foreground hover:text-foreground cursor-help"
                  title="Search budget for bundle selection. Higher values allow more candidate bundles to be evaluated (may improve quality, longer run)."
                >
                  <HelpCircle className="h-3.5 w-3.5" />
                </span>
              </div>
              <Select
                value={maxIterations.toString()}
                onValueChange={(v) => setMaxIterations(parseInt(v))}
              >
                <SelectTrigger id="max-iterations">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {[2, 3, 4, 5].map((n) => (
                    <SelectItem key={n} value={n.toString()}>
                      {n}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <div className="flex items-center gap-1.5">
                <Label htmlFor="max-bullet-lines">Max Bullet Lines</Label>
                <span
                  className="inline-flex text-muted-foreground hover:text-foreground cursor-help"
                  title="Maximum lines allowed per bullet in the optimized resume."
                >
                  <HelpCircle className="h-3.5 w-3.5" />
                </span>
              </div>
              <Select
                value={maxBulletLines.toString()}
                onValueChange={(v) => setMaxBulletLines(parseInt(v))}
              >
                <SelectTrigger id="max-bullet-lines">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Array.from(
                    { length: MAX_BULLET_LINES - MIN_BULLET_LINES + 1 },
                    (_, i) => i + MIN_BULLET_LINES,
                  ).map((n) => (
                    <SelectItem key={n} value={n.toString()}>
                      {n}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Resume LaTeX Template</CardTitle>
          <CardDescription>Your resume LaTeX source code</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <div className="space-y-4">
              <LatexEditor value={latex} onChange={setLatex} height="600px" />
              <div className="flex gap-2 flex-wrap">
                <Button onClick={handleSave} disabled={isSaving || isValidating}>
                  {isValidating
                    ? 'Validating LaTeX...'
                    : isSaving
                      ? 'Saving...'
                      : 'Save LaTeX Template'}
                </Button>
                <Button variant="secondary" onClick={() => setDocxDialogOpen(true)}>
                  <FileUp className="mr-2 h-4 w-4" />
                  Upload .docx
                </Button>
              </div>
            </div>
            <div
              className="border rounded-lg overflow-hidden bg-muted/30 flex items-center justify-center"
              style={{ minHeight: '600px' }}
            >
              {isCompiling ? (
                <div className="flex flex-col items-center gap-2 text-muted-foreground">
                  <Loader2 className="h-8 w-8 animate-spin" />
                  <p className="text-sm">Compiling PDF...</p>
                </div>
              ) : pdfBlobUrl ? (
                <iframe
                  src={`${pdfBlobUrl}#toolbar=0&navpanes=0`}
                  className="w-full h-full"
                  style={{ minHeight: '600px' }}
                  title="Resume PDF Preview"
                />
              ) : (
                <p className="text-sm text-muted-foreground px-4 text-center">
                  PDF preview appears here when you have LaTeX saved or when you
                  open Settings with a saved template
                </p>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <DocxUploadDialog
        open={docxDialogOpen}
        onOpenChange={setDocxDialogOpen}
        onAccept={async (generatedLatex) => {
          setLatex(generatedLatex);
          try {
            const updated = await updateMe({ resume_latex: generatedLatex });
            setUserFromProfile(updated);
          } catch (err) {
            console.error('Failed to save resume to backend:', err);
          }
          compileAndSetPdf(generatedLatex);
          toast.success('Resume loaded and saved.');
        }}
      />
    </div>
  );
}
