import * as vscode from 'vscode';
import { SidebarProvider } from './SidebarProvider';

export function activate(context: vscode.ExtensionContext): void {
  const provider = new SidebarProvider(context.extensionUri);

  // EXT-01: Register WebviewViewProvider for nexus.sidebar
  // retainContextWhenHidden: true — keeps React state (chat history) alive when sidebar is hidden
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
      void provider.triggerIndex();
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('nexus.clearIndex', () => {
      void provider.triggerClear();
    })
  );

  // EXT-04: Auto-index on workspace open
  if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
    void provider.triggerIndex();
  }
}

export function deactivate(): void {}
