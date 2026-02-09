'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { startDocxConversion, getDocxConversionStatus } from '@/lib/api';
import { MAX_DOCX_FILE_SIZE, type TargetPages, DEFAULT_TARGET_PAGES, TARGET_PAGES_OPTIONS, parseTargetPages } from '@/lib/constants';
import { toast } from 'sonner';
import { Loader2, Upload, FileText, CheckCircle2, AlertCircle } from 'lucide-react';

type Step = 'upload' | 'converting' | 'review';

interface DocxUploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAccept: (latex: string) => void;
}

export function DocxUploadDialog({ open, onOpenChange, onAccept }: DocxUploadDialogProps) {
  const [step, setStep] = useState<Step>('upload');
  const [file, setFile] = useState<File | null>(null);
  const [targetPages, setTargetPages] = useState<TargetPages>(DEFAULT_TARGET_PAGES);
  const [isDragging, setIsDragging] = useState(false);
  const [generatedLatex, setGeneratedLatex] = useState('');
  const [compiledPdfUrl, setCompiledPdfUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Clear any active polling interval
  const clearPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // Clean up polling on unmount
  useEffect(() => clearPoll, [clearPoll]);

  const resetState = useCallback(() => {
    clearPoll();
    setStep('upload');
    setFile(null);
    setTargetPages(DEFAULT_TARGET_PAGES);
    setIsDragging(false);
    setGeneratedLatex('');
    if (compiledPdfUrl) {
      URL.revokeObjectURL(compiledPdfUrl);
    }
    setCompiledPdfUrl(null);
    setError(null);
  }, [compiledPdfUrl, clearPoll]);

  const handleOpenChange = useCallback((isOpen: boolean) => {
    if (!isOpen) {
      resetState();
    }
    onOpenChange(isOpen);
  }, [onOpenChange, resetState]);

  const validateFile = (f: File): string | null => {
    if (!f.name.toLowerCase().endsWith('.docx')) {
      return 'Please select a .docx file';
    }
    if (f.size > MAX_DOCX_FILE_SIZE) {
      return `File size exceeds ${MAX_DOCX_FILE_SIZE / (1024 * 1024)}MB limit`;
    }
    if (f.size === 0) {
      return 'File is empty';
    }
    return null;
  };

  const handleFileSelect = (f: File) => {
    const validationError = validateFile(f);
    if (validationError) {
      toast.error(validationError);
      return;
    }
    setFile(f);
    setError(null);
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) {
      handleFileSelect(f);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) {
      handleFileSelect(f);
    }
  };

  const handleConvert = async () => {
    if (!file) return;

    setStep('converting');
    setError(null);
    clearPoll();

    try {
      // Start conversion -- returns immediately with a conversion_id
      const { conversion_id } = await startDocxConversion(file, targetPages);

      // Poll every 15 seconds until completed or failed
      pollRef.current = setInterval(async () => {
        try {
          const status = await getDocxConversionStatus(conversion_id);

          if (status.status === 'completed') {
            clearPoll();
            setGeneratedLatex(status.latex);

            // Convert base64 PDF to blob URL for iframe display
            const pdfBytes = Uint8Array.from(atob(status.compiled_pdf), c => c.charCodeAt(0));
            const pdfBlob = new Blob([pdfBytes], { type: 'application/pdf' });
            if (compiledPdfUrl) {
              URL.revokeObjectURL(compiledPdfUrl);
            }
            setCompiledPdfUrl(URL.createObjectURL(pdfBlob));
            setStep('review');
          } else if (status.status === 'failed') {
            clearPoll();
            const errorMessage = status.error_message || 'Conversion failed';
            setError(errorMessage);
            setStep('upload');
            toast.error(`Conversion failed: ${errorMessage}`);
          }
          // pending / processing -- keep polling
        } catch (pollErr) {
          clearPoll();
          const errorMessage = pollErr instanceof Error ? pollErr.message : 'Conversion failed';
          setError(errorMessage);
          setStep('upload');
          toast.error(`Conversion failed: ${errorMessage}`);
        }
      }, 15000);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Conversion failed';
      setError(errorMessage);
      setStep('upload');
      toast.error(`Conversion failed: ${errorMessage}`);
    }
  };

  const handleAccept = () => {
    onAccept(generatedLatex);
    handleOpenChange(false);
  };

  const handleRetry = () => {
    setError(null);
    setStep('converting');
    handleConvert();
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className={step === 'review' ? 'sm:max-w-4xl' : 'sm:max-w-lg'}>
        <DialogHeader>
          <DialogTitle>
            {step === 'upload' && 'Upload .docx Resume'}
            {step === 'converting' && 'Converting Resume...'}
            {step === 'review' && 'Review Converted Resume'}
          </DialogTitle>
          <DialogDescription>
            {step === 'upload' && 'Upload your Word document and we\'ll convert it to LaTeX automatically.'}
            {step === 'converting' && 'Your resume is being converted to LaTeX. This may take a moment.'}
            {step === 'review' && 'Review the generated PDF below. You can accept it or retry the conversion.'}
          </DialogDescription>
        </DialogHeader>

        {/* Step 1: Upload */}
        {step === 'upload' && (
          <div className="space-y-4">
            <div
              className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
                isDragging
                  ? 'border-primary bg-primary/5'
                  : file
                    ? 'border-green-500 bg-green-500/5'
                    : 'border-muted-foreground/25 hover:border-muted-foreground/50'
              }`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".docx"
                onChange={handleInputChange}
                className="hidden"
              />
              {file ? (
                <div className="flex flex-col items-center gap-2">
                  <FileText className="h-10 w-10 text-green-500" />
                  <p className="font-medium">{file.name}</p>
                  <p className="text-sm text-muted-foreground">
                    {(file.size / 1024).toFixed(1)} KB
                  </p>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-2">
                  <Upload className="h-10 w-10 text-muted-foreground" />
                  <p className="font-medium">Drop your .docx file here</p>
                  <p className="text-sm text-muted-foreground">or click to browse</p>
                </div>
              )}
            </div>

            <div className="space-y-2">
              <Label>Target pages for converted resume</Label>
              <Select
                value={targetPages.toString()}
                onValueChange={(v) => setTargetPages(parseTargetPages(v))}
              >
                <SelectTrigger className="w-36">
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
              <p className="text-xs text-muted-foreground">
                How many pages your resume should fit on (we&apos;ll adjust spacing to match).
              </p>
            </div>

            {error && (
              <div className="flex items-center gap-2 text-sm text-destructive">
                <AlertCircle className="h-4 w-4" />
                {error}
              </div>
            )}
          </div>
        )}

        {/* Step 2: Converting */}
        {step === 'converting' && (
          <div className="flex flex-col items-center gap-4 py-8">
            <Loader2 className="h-12 w-12 animate-spin text-primary" />
            <div className="text-center">
              <p className="font-medium">Converting your resume to LaTeX...</p>
              <p className="text-sm text-muted-foreground mt-1">
                This typically takes 30-60 seconds
              </p>
            </div>
          </div>
        )}

        {/* Step 3: Review */}
        {step === 'review' && compiledPdfUrl && (
          <div className="space-y-4">
            <div className="border rounded-lg overflow-hidden bg-muted/30" style={{ height: '500px' }}>
              <iframe
                src={`${compiledPdfUrl}#toolbar=0&navpanes=0`}
                className="w-full h-full"
                title="Converted Resume Preview"
              />
            </div>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <CheckCircle2 className="h-4 w-4 text-green-500" />
              LaTeX generated and compiled successfully
            </div>
          </div>
        )}

        <DialogFooter>
          {step === 'upload' && (
            <>
              <Button variant="outline" onClick={() => handleOpenChange(false)}>
                Cancel
              </Button>
              <Button onClick={handleConvert} disabled={!file}>
                Convert to LaTeX
              </Button>
            </>
          )}
          {step === 'converting' && (
            <Button variant="outline" onClick={() => { clearPoll(); setStep('upload'); }}>
              Cancel
            </Button>
          )}
          {step === 'review' && (
            <>
              <Button variant="outline" onClick={() => handleOpenChange(false)}>
                Cancel
              </Button>
              <Button variant="outline" onClick={handleRetry}>
                Retry Conversion
              </Button>
              <Button onClick={handleAccept}>
                Accept and Load into Editor
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
