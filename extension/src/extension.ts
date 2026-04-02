import * as path from 'path';
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

  // SIDECAR-01: Start or reuse the bundled backend binary.
  // Uses a lockfile in globalStorageUri so multiple IDE windows share one process.
  // Developer override: if nexus.backendUrl is explicitly set, skip the sidecar entirely.
  const backendUrlOverride = config.get<string>('backendUrl', '');
  // The package.json default for backendUrl is "http://localhost:8000".
  // config.get() returns that default even when the user has never touched the setting,
  // so we must exclude it to avoid treating unset as "override".
  const useOverride = !!backendUrlOverride && backendUrlOverride !== 'http://localhost:8000';

  const sidecar = new SidecarManager(context.extensionPath, context.globalStorageUri.fsPath);
  context.subscriptions.push(sidecar);

  const backendUrl = useOverride
    ? backendUrlOverride
    : await sidecar.start();

  if (!useOverride && sidecar.didSpawn) {
    try {
      await sidecar.waitForHealth(backendUrl);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      console.warn(`[Nexus] ${msg}`);
      const action = await vscode.window.showErrorMessage(
        'Nexus: Backend failed to start. See the output channel for details.',
        'Open Logs'
      );
      if (action === 'Open Logs') {
        sidecar.showOutputChannel();
      }
    }
  }

  // Construct ONE shared BackendClient — both SidebarProvider and FileWatcher use it
  const client = new BackendClient(backendUrl);

  // Restart state — prevents concurrent restarts, rapid crash loops, and infinite retry.
  let _restartInProgress = false;
  let _lastRestartTime = 0;
  let _consecutiveRestartFailures = 0;
  const RESTART_MIN_INTERVAL_MS = 10_000;
  const MAX_CONSECUTIVE_RESTART_FAILURES = 5;

  /**
   * Restart the backend after an unexpected exit (idle watchdog SIGTERM, crash, etc.).
   * Updates client.backendUrl so all in-flight and future calls use the new address.
   * Guards against concurrent calls, rapid crash loops, and infinite restart cycles.
   */
  const _restartBackend = async (): Promise<void> => {
    if (_restartInProgress) { return; }
    if (Date.now() - _lastRestartTime < RESTART_MIN_INTERVAL_MS) { return; }
    if (_consecutiveRestartFailures >= MAX_CONSECUTIVE_RESTART_FAILURES) { return; }
    _restartInProgress = true;
    _lastRestartTime = Date.now();
    try {
      const newUrl = await sidecar.start();
      client.backendUrl = newUrl;
      if (sidecar.didSpawn) {
        await sidecar.waitForHealth(newUrl, 15_000).catch((err: unknown) => {
          console.warn(`[Nexus] Backend restart health check failed: ${err instanceof Error ? err.message : String(err)}`);
        });
      }
      _consecutiveRestartFailures = 0;  // reset on any successful start()
    } catch (err: unknown) {
      _consecutiveRestartFailures++;
      console.warn(`[Nexus] Failed to restart backend (attempt ${_consecutiveRestartFailures}): ${err instanceof Error ? err.message : String(err)}`);
      if (_consecutiveRestartFailures >= MAX_CONSECUTIVE_RESTART_FAILURES) {
        void vscode.window.showErrorMessage(
          'Nexus: Backend failed to restart after multiple attempts. Reload the window to retry.',
          'Reload Window'
        ).then(action => {
          if (action === 'Reload Window') {
            void vscode.commands.executeCommand('workbench.action.reloadWindow');
          }
        });
      }
    } finally {
      _restartInProgress = false;
    }
  };

  // SIDECAR-03: Restart immediately when the spawned process exits unexpectedly.
  // This fires only in the window that originally launched the backend.
  if (!useOverride) {
    sidecar.onUnexpectedExit = _restartBackend;
  }

  // SIDECAR-02: Keepalive ping every 30s — resets the backend idle watchdog and
  // triggers a restart if the backend has died (covers reuse-path windows too).
  // The in-flight guard prevents pings piling up if the backend is slow to respond.
  let _keepaliveInFlight = false;
  const keepaliveInterval = setInterval(async () => {
    if (_keepaliveInFlight) { return; }
    _keepaliveInFlight = true;
    try {
      const alive = await client.ping();
      if (alive) {
        _consecutiveRestartFailures = 0;  // backend is healthy — clear failure streak
      } else if (!useOverride) {
        await _restartBackend();
      }
    } finally {
      _keepaliveInFlight = false;
    }
  }, 30_000);
  context.subscriptions.push({ dispose: () => clearInterval(keepaliveInterval) });

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

  /** Re-compute which providers are missing keys and tell the webview. */
  const syncKeyStatus = async (): Promise<void> => {
    const missing = await configManager.getMissingProviders();
    provider.broadcastKeyStatus(missing);
  };

  context.subscriptions.push(
    vscode.commands.registerCommand('nexus.setApiKey', async () => {
      await configManager.setApiKey();
      await syncKeyStatus();
    }),
    vscode.commands.registerCommand('nexus.clearApiKey', async () => {
      await configManager.clearApiKey();
      await syncKeyStatus();
    }),
    vscode.commands.registerCommand('nexus.setup', async () => {
      await configManager.setupMissingKeys();
      await syncKeyStatus();
    }),
    vscode.commands.registerCommand('nexus.openSettings', () =>
      vscode.commands.executeCommand('workbench.action.openSettings', '@ext:Hafiz408.nexus-ai')
    ),
  );

  // EXT-04: Wire FileWatcher for incremental re-index on save (WATCH-01/02/03).
  // Auto-index is intentionally disabled — user triggers the first index manually
  // via the "Index Workspace" button or the nexus.indexWorkspace command.
  // One watcher per workspace folder supports multi-root workspaces.
  let dbPath: string | undefined;
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    const repoPath = folder.uri.fsPath;
    const folderDbPath = path.join(repoPath, '.nexus', 'graph.db');
    // Use the first folder's db path for config push (single-backend config)
    dbPath ??= folderDbPath;
    const watcher = new FileWatcher(repoPath, client, folderDbPath, (files) => {
      const names = files.map(f => path.basename(f)).join(', ');
      provider.postLog('info', `Auto-reindex: ${files.length} file(s) saved — ${names}`);
    });
    context.subscriptions.push(watcher);
  }

  // CONF-01: Push config after sidecar is healthy (backend ready to accept config)
  void configManager.pushConfig(dbPath).catch(() => { /* backend may not be ready yet */ });

  // Broadcast initial key status to webview so setup guide renders correctly on load
  void syncKeyStatus();

  // EMBD-03: Snapshot current embedding settings to detect changes
  let prevEmbeddingProvider = config.get<string>('embeddingProvider', 'mistral');
  let prevEmbeddingModel = config.get<string>('embeddingModel', 'mistral-embed');

  // ONBOARD-01: Prompt first-time users to set an API key
  const welcomed = context.globalState.get<boolean>('nexus.welcomed');
  if (!welcomed) {
    const providers = ['openai', 'mistral', 'anthropic', 'ollama', 'gemini'] as const;
    const hasKey = (await Promise.all(
      providers.map(p => context.secrets.get(`nexus.apiKey.${p}`))
    )).some(Boolean);

    if (!hasKey) {
      const action = await vscode.window.showInformationMessage(
        'Welcome to Nexus AI! Set your API key to get started.',
        'Set API Key',
        'Later'
      );
      if (action === 'Set API Key') {
        await vscode.commands.executeCommand('nexus.setup');
      }
    }
    await context.globalState.update('nexus.welcomed', true);
  }

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

        let result = { reindex_required: false };
        try {
          result = await configManager.pushConfig(dbPath);
        } catch (err) {
          provider.postLog('warning', `Config push failed: ${err instanceof Error ? err.message : String(err)}`);
        }
        provider.setReindexState(result.reindex_required, false);
        provider.broadcastConfigStatus();
        await syncKeyStatus();
      }
    })
  );
}

export function deactivate(): void {}
