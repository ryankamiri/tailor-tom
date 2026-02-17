'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { LatexEditor } from '@/components/editor/latex-editor';
import { PdfDiffView } from '@/components/diff/pdf-diff-view';
import { DiffResponse, validateLatex, compileLatexToPdf, computeLatexDiff } from '@/lib/api';
import { toast } from 'sonner';

export interface JobResultsViewProps {
  originalLatex: string;
  optimizedLatex: string;
  filename?: string | null;
  isFailed?: boolean; // If true, this is a failed job but LaTeX is still available
}

export function JobResultsView({
  originalLatex,
  optimizedLatex,
  filename,
  isFailed = false,
}: JobResultsViewProps) {
  const [editedLatex, setEditedLatex] = useState<string>(optimizedLatex);
  const [isEdited, setIsEdited] = useState(false);
  const [isCompiling, setIsCompiling] = useState(false);
  const [diffSummary, setDiffSummary] = useState<DiffResponse['summary'] | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [pdfDiffTrigger, setPdfDiffTrigger] = useState(0); // Trigger for PDF diff regeneration

  // Load initial summary when component mounts
  useEffect(() => {
    const loadSummary = async () => {
      try {
        const diffData = await computeLatexDiff(originalLatex, optimizedLatex);
        setDiffSummary(diffData.summary);
      } catch (error) {
        console.error('Failed to load summary:', error);
        // Don't show error to user - summary is optional
      }
    };

    loadSummary();
  }, [originalLatex, optimizedLatex]);

  // Validate LaTeX and regenerate diff summary + PDF view (no server persistence)
  const handleSave = useCallback(async () => {
    try {
      setIsSaving(true);

      // First, validate the LaTeX by attempting to compile it
      try {
        await validateLatex(editedLatex);
      } catch (validateError) {
        const errorMessage = validateError instanceof Error ? validateError.message : 'Invalid LaTeX syntax';
        toast.error(`Invalid LaTeX: ${errorMessage}`);
        setIsSaving(false);
        return; // Don't save if LaTeX is invalid
      }

      // LaTeX is valid; regenerate summary and PDF diff (no server persistence for edited LaTeX)
      try {
        const diffData = await computeLatexDiff(originalLatex, editedLatex);
        setDiffSummary(diffData.summary);
      } catch (diffError) {
        console.error('Failed to regenerate summary:', diffError);
        // Continue even if summary fails - it's not critical
      }

      // Trigger PDF diff regeneration
      setPdfDiffTrigger((prev) => prev + 1);

      toast.success('Changes saved successfully!');
      setIsSaving(false);
    } catch (error) {
      console.error('Failed to save:', error);
      const errorMessage = error instanceof Error ? error.message : 'Failed to save changes';
      toast.error(errorMessage);
      setIsSaving(false);
    }
  }, [editedLatex, originalLatex]);

  // Keyboard shortcut: Command+S (Mac) or Ctrl+S (Windows/Linux)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        handleSave();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [handleSave]);

  const handleDownload = async () => {
    setIsCompiling(true);
    try {
      const latexToCompile = isEdited ? editedLatex : optimizedLatex;
      const downloadFilename = filename || 'resume.pdf';
      const pdfBlob = await compileLatexToPdf(latexToCompile, downloadFilename);

      // Create download link
      const url = URL.createObjectURL(pdfBlob);
      const a = document.createElement('a');
      a.href = url;
      a.download = downloadFilename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      toast.success('PDF downloaded successfully!');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to compile PDF';
      toast.error(errorMessage);
    } finally {
      setIsCompiling(false);
    }
  };

  return (
    <div className="space-y-6">
      {isFailed && (
        <Card className="border-amber-500 bg-amber-50 dark:bg-amber-950">
          <CardContent className="pt-6">
            <p className="text-sm text-amber-800 dark:text-amber-200">
              <strong>Note:</strong> This job failed, but the LaTeX output is still available. 
              You can review and download it, but it may have errors or incomplete optimizations.
            </p>
          </CardContent>
        </Card>
      )}
      
      {/* PDF Diff View - Side-by-side PDFs with highlights */}
      <PdfDiffView 
        originalLatex={originalLatex} 
        optimizedLatex={editedLatex} 
        trigger={pdfDiffTrigger}
        showErrorOnFail={!isFailed} // Don't show errors if this is a failed job (expected)
      />

      {/* Summary */}
      {diffSummary && (
        <Card>
          <CardHeader>
            <CardTitle>Change Summary</CardTitle>
            <CardDescription>
              Overview of changes made to your resume
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <div>
                <div className="text-2xl font-bold">{diffSummary.total_items}</div>
                <div className="text-sm text-muted-foreground">Total Items</div>
              </div>
              <div>
                <div className="text-2xl font-bold text-blue-600 dark:text-blue-400">{diffSummary.changed_items}</div>
                <div className="text-sm text-muted-foreground">Changed</div>
              </div>
              <div>
                <div className="text-2xl font-bold">{diffSummary.original_word_count}</div>
                <div className="text-sm text-muted-foreground">Original Words</div>
              </div>
              <div>
                <div className="text-2xl font-bold">{diffSummary.optimized_word_count}</div>
                <div className="text-sm text-muted-foreground">Optimized Words</div>
              </div>
              <div>
                <div
                  className={`text-2xl font-bold ${
                    diffSummary.word_change_percent >= 0 
                      ? 'text-green-600 dark:text-green-400' 
                      : 'text-blue-600 dark:text-blue-400'
                  }`}
                >
                  {diffSummary.word_change_percent >= 0 ? '+' : ''}
                  {diffSummary.word_change_percent.toFixed(1)}%
                </div>
                <div className="text-sm text-muted-foreground">Change</div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* LaTeX Editor */}
      <Card>
        <CardHeader>
          <CardTitle>Optimized Resume LaTeX</CardTitle>
          <CardDescription>
            Review and edit the optimized LaTeX. Click Download to generate the PDF.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <LatexEditor
            value={editedLatex}
            onChange={(value) => {
              setEditedLatex(value);
              setIsEdited(value !== optimizedLatex);
            }}
            height="600px"
          />
          <div className="flex gap-2">
            <Button onClick={handleSave} disabled={!isEdited || isSaving}>
              {isSaving ? 'Saving...' : 'Save Changes'}
            </Button>
            <Button onClick={handleDownload} disabled={isCompiling} variant="outline">
              {isCompiling ? 'Compiling...' : 'Download PDF'}
            </Button>
            {isEdited && (
              <Button
                variant="outline"
                onClick={() => {
                  setEditedLatex(optimizedLatex);
                  setIsEdited(false);
                }}
              >
                Reset Changes
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

