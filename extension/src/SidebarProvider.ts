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

  constructor(
    private readonly _extensionUri: vscode.Uri,
    client: BackendClient
  ) {
    this._client = client;  // use the passed-in client instead of constructing internally
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

    // SSE-03: handle messages from webview
    webviewView.webview.onDidReceiveMessage(async (msg: WebviewToHostMessage) => {
      switch (msg.type) {
        case 'query':
          if (this._repoPath) {
            const config = vscode.workspace.getConfiguration('nexus');
            const backendUrl = config.get<string>('backendUrl', 'http://localhost:8000');
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
              backendUrl,
              (citations) => { void this._highlight.highlightCitations(citations); },
              msg.intent_hint,
              msg.target_node_id,   // forwarded from webview (undefined if not provided)
              selectedFile,          // from active editor (undefined if no editor open)
              selectedRange,         // from active selection (undefined if no selection or empty)
              this._repoPath,        // repo_root = workspace root (same as repoPath)
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

        case 'postReviewToPR': {
          const config = vscode.workspace.getConfiguration('nexus');
          const backendUrl = config.get<string>('backendUrl', 'http://localhost:8000');
          try {
            const response = await fetch(`${backendUrl}/review/post-pr`, {
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
      await this._client.startIndex(this._repoPath);
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
      await this._client.clearIndex(this._repoPath);
      void this._postStatus({ status: 'not_indexed' });
    } catch (err) {
      void vscode.window.showErrorMessage(`Nexus: Clear failed — ${String(err)}`);
    }
  }

  private _postStatus(status: IndexStatus): Thenable<boolean> | undefined {
    return this._view?.webview.postMessage({ type: 'indexStatus', status });
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
