'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { DiffResponse } from '@/lib/api';
import { Badge } from '@/components/ui/badge';

export interface DiffViewProps {
  diff: DiffResponse;
}

export function DiffView({ diff }: DiffViewProps) {
  const { items, summary } = diff;

  const changedItems = items.filter((item) => item.changes !== null);

  return (
    <div className="space-y-6">
      {/* Summary */}
      <Card>
        <CardHeader>
          <CardTitle>Change Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div>
              <div className="text-2xl font-bold">{summary.total_items}</div>
              <div className="text-sm text-muted-foreground">Total Items</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-blue-600 dark:text-blue-400">{summary.changed_items}</div>
              <div className="text-sm text-muted-foreground">Changed</div>
            </div>
            <div>
              <div className="text-2xl font-bold">{summary.original_word_count}</div>
              <div className="text-sm text-muted-foreground">Original Words</div>
            </div>
            <div>
              <div className="text-2xl font-bold">{summary.optimized_word_count}</div>
              <div className="text-sm text-muted-foreground">Optimized Words</div>
            </div>
            <div>
              <div
                className={`text-2xl font-bold ${
                  summary.word_change_percent >= 0 ? 'text-green-600 dark:text-green-400' : 'text-blue-600 dark:text-blue-400'
                }`}
              >
                {summary.word_change_percent >= 0 ? '+' : ''}
                {summary.word_change_percent.toFixed(1)}%
              </div>
              <div className="text-sm text-muted-foreground">Change</div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Changed Items */}
      {changedItems.length > 0 && (
        <div className="space-y-4">
          <h3 className="text-xl font-semibold">Changes</h3>
          {changedItems.map((item) => (
            <Card key={item.index}>
              <CardHeader>
                <CardTitle className="text-base">Item #{item.index + 1}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Original */}
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <Badge variant="destructive">Original</Badge>
                  </div>
                  <div className="p-3 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-md">
                    <p className="text-sm">{item.original.text}</p>
                  </div>
                </div>

                {/* Optimized */}
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <Badge className="bg-emerald-100 dark:bg-emerald-900/40 text-emerald-800 dark:text-emerald-200 border-emerald-200 dark:border-emerald-700">
                      Optimized
                    </Badge>
                  </div>
                  <div className="p-3 bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800 rounded-md">
                    <p className="text-sm">{item.optimized.text}</p>
                  </div>
                </div>

                {/* Word Changes */}
                {item.changes && item.changes.word_changes.length > 0 && (
                  <div>
                    <div className="text-sm font-medium mb-2">Word-level Changes:</div>
                    <div className="flex flex-wrap gap-2">
                      {item.changes.word_changes.map((change, idx) => (
                        <Badge
                          key={idx}
                          className={
                            change.type === 'removed'
                              ? 'bg-red-100 dark:bg-red-900/40 text-red-800 dark:text-red-200 border-red-200 dark:border-red-700'
                              : change.type === 'added'
                              ? 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-800 dark:text-emerald-200 border-emerald-200 dark:border-emerald-700'
                              : 'bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200 border-gray-200 dark:border-gray-700'
                          }
                        >
                          {change.type === 'removed' && '− '}
                          {change.type === 'added' && '+ '}
                          {change.text}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

