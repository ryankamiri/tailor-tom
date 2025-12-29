'use client';

import Editor from '@monaco-editor/react';
import type { OnMount } from '@monaco-editor/react';

export interface LatexEditorProps {
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
  height?: string;
}

export function LatexEditor({
  value,
  onChange,
  readOnly = false,
  height = '500px',
}: LatexEditorProps) {
  const handleEditorDidMount: OnMount = (editor, monacoEditor) => {
    // Register LaTeX as a custom language if not already registered
    if (!monacoEditor.languages.getLanguages().find((lang: { id: string }) => lang.id === 'latex')) {
      monacoEditor.languages.register({ id: 'latex' });
    }

    // Configure LaTeX syntax highlighting
    monacoEditor.languages.setLanguageConfiguration('latex', {
      comments: {
        lineComment: '%',
      },
      brackets: [
        ['{', '}'],
        ['[', ']'],
        ['(', ')'],
      ],
      autoClosingPairs: [
        { open: '{', close: '}' },
        { open: '[', close: ']' },
        { open: '(', close: ')' },
        { open: '"', close: '"' },
        { open: "'", close: "'" },
      ],
    });
  };

  return (
    <div className="border rounded-lg overflow-hidden">
      <Editor
        height={height}
        defaultLanguage="latex"
        value={value}
        onChange={(val) => onChange(val ?? '')}
        onMount={handleEditorDidMount}
        theme="vs-light"
        options={{
          readOnly,
          minimap: { enabled: false },
          fontSize: 14,
          lineNumbers: 'on',
          wordWrap: 'on',
          automaticLayout: true,
          scrollBeyondLastLine: false,
          tabSize: 2,
        }}
      />
    </div>
  );
}

