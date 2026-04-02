import * as vscode from 'vscode';
import { BackendClient } from './BackendClient';

export class FileWatcher {
  private readonly _watcher: vscode.FileSystemWatcher;
  private _debounceTimer: ReturnType<typeof setTimeout> | undefined;
  private _pendingFiles: Set<string> = new Set();

  constructor(
    private readonly _repoPath: string,
    private readonly _client: BackendClient,
    private readonly _dbPath: string,
    private readonly _onFlush?: (files: string[]) => void
  ) {
    // WATCH-01: RelativePattern scopes watcher to workspace root only (not global FS)
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    const pattern = workspaceFolder
      ? new vscode.RelativePattern(workspaceFolder, '**/*.{py,ts,tsx,js,jsx}')
      : '**/*.{py,ts,tsx,js,jsx}';

    this._watcher = vscode.workspace.createFileSystemWatcher(pattern);

    // WATCH-01: subscribe to save, new-file, and delete events
    this._watcher.onDidChange(uri => this._onFileEvent(uri));
    this._watcher.onDidCreate(uri => this._onFileEvent(uri));
    // Deleted files must be cleaned up from the index — nodes and FTS rows
    // would otherwise linger as ghost entries that vector search can find but
    // the graph cannot expand from (causing "seed node not in graph" warnings).
    this._watcher.onDidDelete(uri => this._onFileEvent(uri));
  }

  private _onFileEvent(uri: vscode.Uri): void {
    // WATCH-02: accumulate into Set (deduplicates rapid multi-fire for same file),
    // reset 2-second debounce timer on each event
    this._pendingFiles.add(uri.fsPath);
    if (this._debounceTimer !== undefined) {
      clearTimeout(this._debounceTimer);
    }
    this._debounceTimer = setTimeout(() => {
      void this._flush();
    }, 2000);
  }

  private async _flush(): Promise<void> {
    this._debounceTimer = undefined;
    const files = Array.from(this._pendingFiles);
    // Clear BEFORE async call — prevents a second timer racing into a non-empty set
    this._pendingFiles.clear();
    if (files.length === 0) { return; }
    try {
      // WATCH-03: send only the changed file paths for incremental re-index
      await this._client.indexFiles(this._repoPath, files, this._dbPath);
      this._onFlush?.(files);  // log only after confirmed success
    } catch (err) {
      // Do not call _onFlush here — it logs a success-looking message.
      // Errors are console-logged; surfacing them to the Activity panel
      // requires a dedicated error callback which is not yet wired.
      console.error(`[FileWatcher] Auto-reindex failed: ${String(err)}`);
    }
  }

  dispose(): void {
    // WATCH-02 / Pitfall 5: always clear timer before disposing watcher
    if (this._debounceTimer !== undefined) {
      clearTimeout(this._debounceTimer);
    }
    this._watcher.dispose();
  }
}
