import * as vscode from 'vscode';
import { BackendClient } from './BackendClient';
import { FileWatcher } from './FileWatcher';
import { SidebarProvider } from './SidebarProvider';

export function activate(context: vscode.ExtensionContext): void {
  // Construct ONE shared BackendClient — both SidebarProvider and FileWatcher use it
  const config = vscode.workspace.getConfiguration('nexus');
  const backendUrl = config.get<string>('backendUrl', 'http://localhost:8000');
  const client = new BackendClient(backendUrl);

  const provider = new SidebarProvider(context.extensionUri, client);

  // EXT-01: Register WebviewViewProvider for nexus.sidebar
  // retainContextWhenHidden: true — keeps React state (chat history) alive when sidebar is hidden
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      SidebarProvider.viewType,
      provider,
      { webviewOptions: { retainContextWhenHidden: true } }
    )
  );

  context.subscriptions.push({ dispose: () => provider.dispose() });

  // EXT-02: Register commands
  context.subscriptions.push(
    vscode.commands.registerCommand('nexus.indexWorkspace', () => {
      void provider.triggerIndex();
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('nexus.clearIndex', () => {
      void provider.triggerClear();
    })
  );

  // EXT-04: Wire FileWatcher for incremental re-index on save (WATCH-01/02/03).
  // Auto-index is intentionally disabled — user triggers the first index manually
  // via the "Index Workspace" button or the nexus.indexWorkspace command.
  if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
    const repoPath = vscode.workspace.workspaceFolders[0].uri.fsPath;
    const watcher = new FileWatcher(repoPath, client);
    context.subscriptions.push(watcher);
  }
}

export function deactivate(): void {}
