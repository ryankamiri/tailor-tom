'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { LatexEditor } from '@/components/editor/latex-editor';
import { getSettings, saveSettings, getResumeLatex, saveResumeLatex, getUserId, UserSettings } from '@/lib/storage';
import { validateLatex, saveResumeToBackend, compileLatexToPdf } from '@/lib/api';
import { MIN_BULLET_LINES, MAX_BULLET_LINES, DEFAULT_TARGET_PAGES, TARGET_PAGES_OPTIONS, parseTargetPages } from '@/lib/constants';
import { toast } from 'sonner';
import { Loader2, FileUp } from 'lucide-react';
import { DocxUploadDialog } from '@/components/settings/docx-upload-dialog';

export function SettingsForm() {
  const [settings, setSettings] = useState<UserSettings>({
    first_name: '',
    last_name: '',
    target_pages: DEFAULT_TARGET_PAGES,
    max_iterations: 3,
    max_bullet_lines: 2,
  });
  const [latex, setLatex] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [isInitialLoad, setIsInitialLoad] = useState(true);
  const [pdfBlobUrl, setPdfBlobUrl] = useState<string | null>(null);
  const [isCompiling, setIsCompiling] = useState(false);
  const [docxDialogOpen, setDocxDialogOpen] = useState(false);
  const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const initialCompileDoneRef = useRef(false);

  useEffect(() => {
    // Load settings and LaTeX from localStorage
    const savedSettings = getSettings();
    const savedLatex = getResumeLatex() || '';
    
    setSettings(savedSettings);
    setLatex(savedLatex);
    setIsInitialLoad(false);
  }, []);

  // Clean up blob URL on unmount
  useEffect(() => {
    return () => {
      if (pdfBlobUrl) {
        URL.revokeObjectURL(pdfBlobUrl);
      }
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

  // Compile and show PDF on load when there is saved LaTeX (once)
  useEffect(() => {
    if (isInitialLoad || !latex.trim() || initialCompileDoneRef.current) return;
    initialCompileDoneRef.current = true;
    compileAndSetPdf(latex);
  }, [isInitialLoad, latex, compileAndSetPdf]);

  // Auto-save settings when they change (debounced)
  useEffect(() => {
    // Don't save on initial load
    if (isInitialLoad) return;

    // Clear existing timeout
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }

    // Set new timeout to save after 500ms of no changes
    saveTimeoutRef.current = setTimeout(() => {
      try {
        saveSettings(settings);
      } catch (error) {
        console.error('Auto-save settings error:', error);
      }
    }, 500);

    // Cleanup timeout on unmount
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
    };
  }, [settings, isInitialLoad]);

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
          const errorMessage = validateError instanceof Error 
            ? validateError.message 
            : 'Invalid LaTeX syntax';
          console.error('LaTeX validation failed:', validateError);
          toast.error(`Cannot save: ${errorMessage}`);
          setIsSaving(false);
          return; // Don't save if LaTeX is invalid
        }
      }

      // LaTeX is valid (or empty), proceed with saving
      saveSettings(settings);
      saveResumeLatex(latex);
      
      if (latex.trim() && settings.first_name.trim() && settings.last_name.trim()) {
        try {
          // Get or generate user UUID
          const userId = getUserId();
          await saveResumeToBackend(settings.first_name, settings.last_name, userId, latex);
        } catch (error) {
          // Log but don't block user - localStorage save already succeeded
          console.error('Failed to save resume to backend:', error);
        }
      }
      
      toast.success('LaTeX template saved successfully!');

      // Compile and show PDF preview after successful save
      if (latex.trim()) {
        await compileAndSetPdf(latex);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to save template';
      console.error('Save settings error:', error);
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
          <CardTitle>Personal Information</CardTitle>
          <CardDescription>Used for generating output filenames</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="first-name">First Name</Label>
              <Input
                id="first-name"
                value={settings.first_name}
                onChange={(e) =>
                  setSettings({ ...settings, first_name: e.target.value })
                }
                placeholder="John"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="last-name">Last Name</Label>
              <Input
                id="last-name"
                value={settings.last_name}
                onChange={(e) =>
                  setSettings({ ...settings, last_name: e.target.value })
                }
                placeholder="Doe"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Optimization Settings</CardTitle>
          <CardDescription>Configure default optimization parameters</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="target-pages">Target Pages</Label>
              <Select
                value={settings.target_pages.toString()}
                onValueChange={(value) =>
                  setSettings({ ...settings, target_pages: parseTargetPages(value) })
                }
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
              <Label htmlFor="max-iterations">Max Iterations</Label>
              <Select
                value={settings.max_iterations.toString()}
                onValueChange={(value) =>
                  setSettings({ ...settings, max_iterations: parseInt(value) })
                }
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
              <Label htmlFor="max-bullet-lines">Max Bullet Lines</Label>
              <Select
                value={settings.max_bullet_lines.toString()}
                onValueChange={(value) =>
                  setSettings({ ...settings, max_bullet_lines: parseInt(value) })
                }
              >
                <SelectTrigger id="max-bullet-lines">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Array.from({ length: MAX_BULLET_LINES - MIN_BULLET_LINES + 1 }, (_, i) => i + MIN_BULLET_LINES).map((n) => (
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
                  {isValidating ? 'Validating LaTeX...' : isSaving ? 'Saving...' : 'Save LaTeX Template'}
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => setDocxDialogOpen(true)}
                >
                  <FileUp className="mr-2 h-4 w-4" />
                  Upload .docx
                </Button>
              </div>
            </div>
            <div className="border rounded-lg overflow-hidden bg-muted/30 flex items-center justify-center" style={{ minHeight: '600px' }}>
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
                  PDF preview appears here when you have LaTeX saved or when you open Settings with a saved template
                </p>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <DocxUploadDialog
        open={docxDialogOpen}
        onOpenChange={setDocxDialogOpen}
        onAccept={(generatedLatex) => {
          setLatex(generatedLatex);
          saveResumeLatex(generatedLatex);
          compileAndSetPdf(generatedLatex);
          if (settings.first_name.trim() && settings.last_name.trim()) {
            const userId = getUserId();
            saveResumeToBackend(settings.first_name, settings.last_name, userId, generatedLatex).catch((err) => {
              console.error('Failed to save resume to backend:', err);
            });
          }
          toast.success('Resume loaded and saved.');
        }}
      />
    </div>
  );
}

