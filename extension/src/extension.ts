import * as vscode from 'vscode';

// SidebarProvider will be implemented in Plan 02
// Inline stub here so extension.ts compiles independently
class SidebarProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = 'nexus.sidebar';

  constructor(private readonly _extensionUri: vscode.Uri) {}

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri],
    };
    webviewView.webview.html = '<html><body><p>Loading Nexus...</p></body></html>';
  }

  triggerIndex(): void {
    // Will be implemented in SidebarProvider.ts (Plan 02)
  }

  triggerClear(): void {
    // Will be implemented in SidebarProvider.ts (Plan 02)
  }
}

export function activate(context: vscode.ExtensionContext): void {
  const provider = new SidebarProvider(context.extensionUri);

  // EXT-01: Register WebviewViewProvider for nexus.sidebar
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      SidebarProvider.viewType,
      provider,
      { webviewOptions: { retainContextWhenHidden: true } }
    )
  );

  // EXT-02: Register commands
  context.subscriptions.push(
    vscode.commands.registerCommand('nexus.indexWorkspace', () => {
      provider.triggerIndex();
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('nexus.clearIndex', () => {
      provider.triggerClear();
    })
  );

  // EXT-04: Auto-index on workspace open
  if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
    provider.triggerIndex();
  }
}

export function deactivate(): void {}
