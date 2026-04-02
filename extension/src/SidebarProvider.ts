import * as path from 'path';
import * as vscode from 'vscode';
import { BackendClient } from './BackendClient';
import { HighlightService } from './HighlightService';
import { streamQuery } from './SseStream';
import { WebviewToHostMessage, IndexStatus } from './types';

function getNonce(): string {
  let text = '';
  const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}

export class SidebarProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = 'nexus.sidebar';

  private _view?: vscode.WebviewView;
  private readonly _client: BackendClient;
  private readonly _highlight: HighlightService;
  private _repoPath: string | undefined;
  private _reindexRequired = false;
  private _neverIndexed = true;
  private _missingProviders: string[] = [];

  private get _dbPath(): string {
    return path.join(this._repoPath ?? '', '.nexus', 'graph.db');
  }

  constructor(
    private readonly _extensionUri: vscode.Uri,
    client: BackendClient
  ) {
    this._client = client;
    this._highlight = new HighlightService();
    // Use the first workspace folder as the repo path
    this._repoPath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  }

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    this._view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri],
    };

    webviewView.webview.html = this._getHtmlForWebview(webviewView.webview);

    // On load, restore any already-complete index from the backend so the user
    // doesn't see "not indexed" for a repo they already indexed previously.
    // The backend restores _status from SQLite on startup, so this round-trip
    // is all that's needed to recover the UI state after a restart.
    if (this._repoPath) {
      this._client.getStatus(this._repoPath).then((status) => {
        if (status.status !== 'not_indexed') {
          void this._postStatus(status);
        }
        if (status.status === 'complete') {
          this._neverIndexed = false;
        }
      }).catch(() => { /* backend not yet up — UI stays at not_indexed */ });
    }

    // Send initial reindex state, config status, and key status to webview
    this._broadcastReindexState();
    this.broadcastConfigStatus();
    this.broadcastKeyStatus(this._missingProviders);

    // SSE-03: handle messages from webview
    webviewView.webview.onDidReceiveMessage(async (msg: WebviewToHostMessage) => {
      switch (msg.type) {
        case 'query':
          if (this._repoPath) {
            // Gate on missing API key before hitting the backend
            if (this._missingProviders.length > 0) {
              void webviewView.webview.postMessage({
                type: 'error',
                message: `API key not set for: ${this._missingProviders.join(', ')}. Use "Nexus: Setup — Configure API Key" to add it.`,
              });
              void vscode.window.showWarningMessage(
                `Nexus: Missing API key for ${this._missingProviders.join(', ')}.`,
                'Set API Key'
              ).then(action => {
                if (action === 'Set API Key') {
                  void vscode.commands.executeCommand('nexus.setup');
                }
              });
              break;
            }
            this._highlight.clearHighlights();   // HIGH-02: clear on new query
            // Capture active editor context for review/test intents
            const editor = vscode.window.activeTextEditor;
            const selectedFile = editor?.document.uri.fsPath;
            const sel = editor?.selection;
            const selectedRange: [number, number] | undefined =
              sel && !sel.isEmpty
                ? [sel.start.line + 1, sel.end.line + 1]  // 0-indexed → 1-indexed
                : undefined;
            await streamQuery(
              msg.question,
              this._repoPath,
              webviewView.webview,
              this._client.backendUrl,
              (citations) => { void this._highlight.highlightCitations(citations); },
              msg.intent_hint,
              msg.target_node_id,   // forwarded from webview (undefined if not provided)
              selectedFile,          // from active editor (undefined if no editor open)
              selectedRange,         // from active selection (undefined if no selection or empty)
              this._repoPath,        // repo_root = workspace root (same as repoPath)
              this._dbPath,          // NEW: local db path for v3 local-first
            );
          } else {
            void webviewView.webview.postMessage({
              type: 'error',
              message: 'No workspace folder open.',
            });
          }
          break;

        case 'openFile': {
          // CHAT-03: open file at cited line (convert 1-indexed to 0-indexed for VS Code Position)
          const uri = vscode.Uri.file(msg.filePath);
          try {
            const doc = await vscode.workspace.openTextDocument(uri);
            const line0 = Math.max(0, msg.lineStart - 1);
            await vscode.window.showTextDocument(doc, {
              selection: new vscode.Range(
                new vscode.Position(line0, 0),
                new vscode.Position(line0, 0)
              ),
            });
          } catch {
            void vscode.window.showErrorMessage(`Cannot open file: ${msg.filePath}`);
          }
          break;
        }

        case 'indexWorkspace':
          await this.triggerIndex();
          break;

        case 'clearIndex':
          await this.triggerClear();
          break;

        case 'configureKeys':
          void vscode.commands.executeCommand('nexus.setApiKey');
          break;

        case 'openSettings':
          void vscode.commands.executeCommand('nexus.openSettings');
          break;

        case 'postReviewToPR': {
          try {
            const response = await fetch(`${this._client.backendUrl}/review/post-pr`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                findings: msg.findings,
                repo: msg.repo,
                pr_number: msg.pr_number,
                commit_sha: msg.commit_sha,
              }),
            });
            if (response.ok) {
              const data = await response.json() as { posted: number; overflow: boolean };
              vscode.window.showInformationMessage(
                `Posted ${data.posted} review comment(s) to GitHub PR #${msg.pr_number}.`
              );
            } else {
              const err = await response.text();
              vscode.window.showErrorMessage(`Post to GitHub PR failed: ${err}`);
            }
          } catch (err) {
            vscode.window.showErrorMessage(`Post to GitHub PR error: ${String(err)}`);
          }
          break;
        }
      }
    });
  }

  async triggerIndex(): Promise<void> {
    if (!this._repoPath) {
      void vscode.window.showWarningMessage('Nexus: No workspace folder open.');
      return;
    }

    try {
      await this._client.startIndex(this._repoPath, this._dbPath);
      void this._postStatus({ status: 'running' });

      await this._client.pollUntilComplete(this._repoPath, (status) => {
        void this._postStatus(status);
      });
    } catch (err) {
      void this._postStatus({ status: 'failed', error: String(err) });
    }
  }

  async triggerClear(): Promise<void> {
    if (!this._repoPath) {
      return;
    }
    try {
      await this._client.clearIndex(this._repoPath, this._dbPath);
      void this._postStatus({ status: 'not_indexed' });
    } catch (err) {
      void vscode.window.showErrorMessage(`Nexus: Clear failed — ${String(err)}`);
    }
  }

  private _postStatus(status: IndexStatus): Thenable<boolean> | undefined {
    if (status.status === 'complete') {
      this._neverIndexed = false;
      this._reindexRequired = false;
      this._broadcastReindexState();
    }
    return this._view?.webview.postMessage({ type: 'indexStatus', status });
  }

  setReindexState(reindexRequired: boolean, neverIndexed: boolean): void {
    this._reindexRequired = reindexRequired;
    if (!neverIndexed) { this._neverIndexed = false; } // once indexed, stays false
    this._broadcastReindexState();
  }

  postLog(level: 'info' | 'warning' | 'error', message: string): void {
    void this._view?.webview.postMessage({ type: 'log', level, message });
  }

  broadcastKeyStatus(missing: string[]): void {
    this._missingProviders = missing;
    void this._view?.webview.postMessage({ type: 'keyStatus', missing });
  }

  broadcastConfigStatus(): void {
    const config = vscode.workspace.getConfiguration('nexus');
    void this._view?.webview.postMessage({
      type: 'configStatus',
      chat_provider: config.get<string>('chatProvider', 'mistral'),
      chat_model: config.get<string>('chatModel', 'mistral-small-latest'),
      embedding_provider: config.get<string>('embeddingProvider', 'mistral'),
      embedding_model: config.get<string>('embeddingModel', 'mistral-embed'),
    });
  }

  private _broadcastReindexState(): void {
    void this._view?.webview.postMessage({
      type: 'reindexState',
      reindex_required: this._reindexRequired,
      never_indexed: this._neverIndexed,
    });
  }

  dispose(): void {
    this._highlight.dispose();
  }

  private _getHtmlForWebview(webview: vscode.Webview): string {
    const scriptUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'out', 'webview', 'index.js')
    );
    const styleUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this._extensionUri, 'out', 'webview', 'index.css')
    );
    const nonce = getNonce();

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy"
    content="default-src 'none'; script-src 'nonce-${nonce}'; style-src ${webview.cspSource} 'unsafe-inline';">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Nexus</title>
  <link rel="stylesheet" href="${styleUri}">
</head>
<body>
  <div id="root"></div>
  <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }
}
