import * as vscode from 'vscode';
import { Citation } from './types';

export class HighlightService {
  private readonly _decorationType: vscode.TextEditorDecorationType;
  private _clearTimer: ReturnType<typeof setTimeout> | undefined;

  constructor() {
    // HIGH-02: create exactly ONE TextEditorDecorationType — never create per query (memory leak)
    this._decorationType = vscode.window.createTextEditorDecorationType({
      backgroundColor: new vscode.ThemeColor('editor.findMatchHighlightBackground'),
      isWholeLine: true,
    });
  }

  async highlightCitations(citations: Citation[]): Promise<void> {
    // HIGH-02: clear existing highlights and cancel pending timer before applying new ones
    this.clearHighlights();

    // Group citations by file_path
    const byFile = new Map<string, Citation[]>();
    for (const c of citations) {
      const existing = byFile.get(c.file_path);
      if (existing) {
        existing.push(c);
      } else {
        byFile.set(c.file_path, [c]);
      }
    }

    for (const [filePath, fileCitations] of byFile) {
      try {
        const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
        const editor = await vscode.window.showTextDocument(doc, {
          preserveFocus: true,
          preview: false,
        });

        // line_start/line_end are 1-indexed; VS Code Position is 0-indexed
        const ranges = fileCitations.map(
          (c) =>
            new vscode.Range(
              new vscode.Position(Math.max(0, c.line_start - 1), 0),
              new vscode.Position(Math.max(0, c.line_end - 1), Number.MAX_SAFE_INTEGER)
            )
        );

        editor.setDecorations(this._decorationType, ranges);
      } catch {
        // File may not exist on disk — skip silently
      }
    }

    // HIGH-02: auto-clear after 10 seconds
    this._clearTimer = setTimeout(() => this.clearHighlights(), 10_000);
  }

  clearHighlights(): void {
    if (this._clearTimer !== undefined) {
      clearTimeout(this._clearTimer);
      this._clearTimer = undefined;
    }

    // Guard with if (editor.document) to prevent "setDecorations on invisible editor"
    // warning — race condition documented in microsoft/vscode#18797
    for (const editor of vscode.window.visibleTextEditors) {
      if (editor.document) {
        editor.setDecorations(this._decorationType, []);
      }
    }
  }

  dispose(): void {
    this.clearHighlights();
    // Frees extension host resources on deactivation
    this._decorationType.dispose();
  }
}
