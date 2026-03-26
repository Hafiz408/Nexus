import * as vscode from 'vscode';
import { BackendClient } from './BackendClient';
import { ConfigManager } from './ConfigManager';
import { FileWatcher } from './FileWatcher';
import { SidebarProvider } from './SidebarProvider';
import { SidecarManager } from './SidecarManager';

export function activate(context: vscode.ExtensionContext): void {
  void _activate(context);
}

async function _activate(context: vscode.ExtensionContext): Promise<void> {
  const config = vscode.workspace.getConfiguration('nexus');
  const backendUrl = config.get<string>('backendUrl', 'http://localhost:8000');

  // SIDECAR-01: Spawn bundled backend binary; skip if port is already occupied (dev mode)
  const sidecar = new SidecarManager(context.extensionPath, backendUrl);
  context.subscriptions.push(sidecar);

  const started = await sidecar.start();
  if (started) {
    await sidecar.waitForHealth().catch((err: unknown) => {
      // Backend didn't come up in time — log but don't crash the extension
      const msg = err instanceof Error ? err.message : String(err);
      console.warn(`[Nexus] ${msg}`);
    });
  }

  // Construct ONE shared BackendClient — both SidebarProvider and FileWatcher use it
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

  // KEYS-01/02: SecretStorage API key commands
  const configManager = new ConfigManager(context, client);

  context.subscriptions.push(
    vscode.commands.registerCommand('nexus.setApiKey', () => configManager.setApiKey()),
    vscode.commands.registerCommand('nexus.clearApiKey', () => configManager.clearApiKey()),
  );

  // EXT-04: Wire FileWatcher for incremental re-index on save (WATCH-01/02/03).
  // Auto-index is intentionally disabled — user triggers the first index manually
  // via the "Index Workspace" button or the nexus.indexWorkspace command.
  let dbPath: string | undefined;
  if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
    const repoPath = vscode.workspace.workspaceFolders[0].uri.fsPath;
    const pathMod = require('path') as typeof import('path');
    dbPath = pathMod.join(repoPath, '.nexus', 'graph.db');
    const watcher = new FileWatcher(repoPath, client, dbPath);
    context.subscriptions.push(watcher);
  }

  // CONF-01: Push config after sidecar is healthy (backend ready to accept config)
  void configManager.pushConfig(dbPath).catch(() => { /* backend may not be ready yet */ });

  // EMBD-03: Snapshot current embedding settings to detect changes
  let prevEmbeddingProvider = config.get<string>('embeddingProvider', 'mistral');
  let prevEmbeddingModel = config.get<string>('embeddingModel', 'mistral-embed');

  // CONF-01: Re-push on settings change
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration(async e => {
      if (e.affectsConfiguration('nexus')) {
        const newConfig = vscode.workspace.getConfiguration('nexus');
        const newEmbeddingProvider = newConfig.get<string>('embeddingProvider', 'mistral');
        const newEmbeddingModel = newConfig.get<string>('embeddingModel', 'mistral-embed');

        // EMBD-03: warn if embedding settings changed
        if (newEmbeddingProvider !== prevEmbeddingProvider || newEmbeddingModel !== prevEmbeddingModel) {
          void vscode.window.showWarningMessage(
            'Nexus: Embedding model changed. You must re-index the workspace before chat will work.',
            'Re-index Now'
          ).then(action => {
            if (action === 'Re-index Now') {
              void provider.triggerIndex();
            }
          });
        }

        prevEmbeddingProvider = newEmbeddingProvider;
        prevEmbeddingModel = newEmbeddingModel;

        const result = await configManager.pushConfig(dbPath).catch(() => ({ reindex_required: false }));
        // Notify webview of reindex state (never_indexed stays as-is — false param means don't force-set it)
        provider.setReindexState(result.reindex_required, false);
        // Broadcast updated config status to webview
        provider.broadcastConfigStatus();
      }
    })
  );
}

export function deactivate(): void {}
