import { IndexStatus } from './types';

export class BackendClient {
  constructor(public backendUrl: string) {}

  async startIndex(repoPath: string, dbPath: string): Promise<void> {
    const res = await fetch(`${this.backendUrl}/index`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_path: repoPath, db_path: dbPath }),
    });
    if (!res.ok) {
      throw new Error(`POST /index failed: ${res.status}`);
    }
  }

  async clearIndex(repoPath: string, dbPath: string): Promise<void> {
    const res = await fetch(
      `${this.backendUrl}/index?repo_path=${encodeURIComponent(repoPath)}&db_path=${encodeURIComponent(dbPath)}`,
      { method: 'DELETE' }
    );
    if (!res.ok) {
      throw new Error(`DELETE /index failed: ${res.status}`);
    }
  }

  async getStatus(repoPath: string): Promise<IndexStatus> {
    // status endpoint currently reads from in-memory dict, db_path not required
    const res = await fetch(
      `${this.backendUrl}/index/status?repo_path=${encodeURIComponent(repoPath)}`
    );
    if (!res.ok) {
      return { status: 'not_indexed' };
    }
    return res.json() as Promise<IndexStatus>;
  }

  // WATCH-03: incremental re-index — sends only the changed file paths
  async indexFiles(repoPath: string, changedFiles: string[], dbPath: string): Promise<void> {
    const res = await fetch(`${this.backendUrl}/index`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_path: repoPath, changed_files: changedFiles, db_path: dbPath }),
    });
    if (!res.ok) {
      throw new Error(`POST /index (incremental) failed: ${res.status}`);
    }
  }

  async postConfig(body: Record<string, unknown>): Promise<{ reindex_required: boolean }> {
    const resp = await fetch(`${this.backendUrl}/api/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      throw new Error(`Config push failed: ${resp.status}`);
    }
    return resp.json() as Promise<{ reindex_required: boolean }>;
  }

  /** Keepalive — resets the backend idle watchdog. Returns true if backend responded OK. */
  async ping(): Promise<boolean> {
    try {
      const res = await fetch(`${this.backendUrl}/api/health`);
      return res.ok;
    } catch {
      return false;
    }
  }

  // SSE-01: poll every 2 seconds until complete or failed
  pollUntilComplete(
    repoPath: string,
    onProgress: (status: IndexStatus) => void,
    timeoutMs = 10 * 60 * 1000,  // 10-minute cap — prevents zombie interval if backend hangs
    signal?: AbortSignal,
  ): Promise<IndexStatus> {
    return new Promise((resolve, reject) => {
      const start = Date.now();
      let inFlight = false;

      const stop = (err?: Error) => {
        clearInterval(interval);
        signal?.removeEventListener('abort', onAbort);
        if (err) { reject(err); } else { resolve({ status: 'not_indexed' }); }
      };

      // Cancel polling immediately when the caller aborts (e.g. extension deactivate).
      const onAbort = () => stop();
      signal?.addEventListener('abort', onAbort, { once: true });

      const interval = setInterval(async () => {
        if (inFlight) { return; }  // skip tick if previous getStatus call is still in flight
        if (Date.now() - start > timeoutMs) {
          stop(new Error('Indexing timed out — backend did not complete within the expected time.'));
          return;
        }
        inFlight = true;
        try {
          const status = await this.getStatus(repoPath);
          onProgress(status);
          if (status.status === 'complete' || status.status === 'failed') {
            clearInterval(interval);
            signal?.removeEventListener('abort', onAbort);
            resolve(status);
          }
        } catch (err) {
          stop(err instanceof Error ? err : new Error(String(err)));
        } finally {
          inFlight = false;
        }
      }, 2000);
    });
  }
}
