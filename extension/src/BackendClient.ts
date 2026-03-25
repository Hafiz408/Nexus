import { IndexStatus } from './types';

export class BackendClient {
  constructor(private readonly backendUrl: string) {}

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

  async getStatus(repoPath: string, dbPath?: string): Promise<IndexStatus> {
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

  // SSE-01: poll every 2 seconds until complete or failed
  pollUntilComplete(
    repoPath: string,
    onProgress: (status: IndexStatus) => void
  ): Promise<IndexStatus> {
    return new Promise((resolve, reject) => {
      const interval = setInterval(async () => {
        try {
          const status = await this.getStatus(repoPath);
          onProgress(status);
          if (status.status === 'complete' || status.status === 'failed') {
            clearInterval(interval);
            resolve(status);
          }
        } catch (err) {
          clearInterval(interval);
          reject(err);
        }
      }, 2000);
    });
  }
}
