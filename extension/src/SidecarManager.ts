import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as net from 'net';
import * as fs from 'fs';
import * as os from 'os';
import * as crypto from 'crypto';

interface BackendLock {
  pid: number;
  port: number;
  version: string;
}

export class SidecarManager implements vscode.Disposable {
  private _process: cp.ChildProcess | undefined;
  private _didSpawn = false;
  private readonly _channel: vscode.OutputChannel;
  private readonly _extensionPath: string;
  private readonly _lockfilePath: string;
  private _backendUrl = '';

  /** True if this instance launched a new backend process (vs. reusing an existing one). */
  get didSpawn(): boolean { return this._didSpawn; }

  /** The backend URL resolved by start(). Empty string until start() is called. */
  get backendUrl(): string { return this._backendUrl; }

  constructor(extensionPath: string, globalStoragePath: string) {
    this._extensionPath = extensionPath;
    this._lockfilePath = path.join(globalStoragePath, 'backend.lock');
    this._channel = vscode.window.createOutputChannel('Nexus Backend');
  }

  // ---------------------------------------------------------------------------
  // Lockfile helpers
  // ---------------------------------------------------------------------------

  private _readLock(): BackendLock | null {
    try {
      return JSON.parse(fs.readFileSync(this._lockfilePath, 'utf-8')) as BackendLock;
    } catch { return null; }
  }

  private _writeLock(lock: BackendLock): void {
    try {
      fs.mkdirSync(path.dirname(this._lockfilePath), { recursive: true });
      // Atomic write: temp file + rename prevents a concurrent reader seeing partial JSON
      const tmp = this._lockfilePath + '.tmp';
      fs.writeFileSync(tmp, JSON.stringify(lock));
      fs.renameSync(tmp, this._lockfilePath);
    } catch { /* non-fatal — dynamic port still works, reuse just won't happen */ }
  }

  /** Delete the lockfile only if it still belongs to the given PID. */
  private _deleteLock(ownedPid: number): void {
    try {
      const lock = this._readLock();
      if (lock?.pid === ownedPid) {
        fs.unlinkSync(this._lockfilePath);
      }
    } catch { /* already gone */ }
  }

  // ---------------------------------------------------------------------------
  // Port + process helpers
  // ---------------------------------------------------------------------------

  private _getVersion(): string {
    try {
      const pkg = JSON.parse(
        fs.readFileSync(path.join(this._extensionPath, 'package.json'), 'utf-8')
      ) as { version?: string };
      return pkg.version ?? '0.0.0';
    } catch { return '0.0.0'; }
  }


  private _getFreePort(): Promise<number> {
    return new Promise((resolve, reject) => {
      const server = net.createServer();
      server.listen(0, '127.0.0.1', () => {
        const { port } = server.address() as net.AddressInfo;
        server.close(() => resolve(port));
      });
      server.on('error', reject);
    });
  }

  private async _checkHealth(url: string): Promise<boolean> {
    try {
      const res = await fetch(`${url}/api/health`);
      if (!res.ok) { return false; }
      const json = await res.json() as { status?: string };
      return json.status === 'ok';
    } catch { return false; }
  }

  private _archiveName(): string | undefined {
    if (process.platform === 'darwin') { return 'nexus-backend-mac.tar.gz'; }
    if (process.platform === 'win32') { return 'nexus-backend-win.tar.gz'; }
    return undefined;
  }

  /** Executable path inside the extracted directory. */
  private _executableName(): string | undefined {
    if (process.platform === 'darwin') { return path.join('nexus-backend-mac', 'nexus-backend-mac'); }
    if (process.platform === 'win32') { return path.join('nexus-backend-win', 'nexus-backend-win.exe'); }
    return undefined;
  }

  /**
   * Fetches the checksums.sha256 file from the GitHub Release and returns the
   * SHA256 hash for the given archive name.
   */
  private async _fetchChecksum(baseUrl: string, archiveName: string): Promise<string> {
    this._channel.appendLine(`[SidecarManager] Fetching checksum for ${archiveName}...`);
    const res = await fetch(`${baseUrl}/checksums.sha256`);
    if (!res.ok) {
      throw new Error(`Failed to fetch checksums: HTTP ${res.status}`);
    }
    const text = await res.text();
    for (const line of text.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed) { continue; }
      const spaceIdx = trimmed.indexOf(' ');
      if (spaceIdx === -1) { continue; }
      const hash = trimmed.slice(0, spaceIdx);
      const filename = trimmed.slice(spaceIdx).trim();
      if (filename === archiveName) {
        return hash;
      }
    }
    throw new Error(`No checksum found for ${archiveName} in checksums.sha256`);
  }

  /**
   * Stream-downloads a file from `url`, reports incremental progress via the
   * VS Code progress API, verifies the SHA256 digest against `expectedHash`,
   * and writes the verified bytes to `destPath`.
   *
   * Deletes the temp file and throws on SHA256 mismatch.
   */
  private async _downloadAndVerify(
    url: string,
    destPath: string,
    expectedHash: string,
    progress: vscode.Progress<{ message?: string; increment?: number }>,
  ): Promise<void> {
    const res = await fetch(url);
    if (!res.ok) {
      throw new Error(`Download failed: HTTP ${res.status}`);
    }
    if (!res.body) {
      throw new Error('Response body is null');
    }
    const contentLength = parseInt(res.headers.get('content-length') ?? '0', 10);
    const hash = crypto.createHash('sha256');
    const chunks: Uint8Array[] = [];
    let received = 0;
    let lastPct = 0;

    for await (const chunk of res.body as unknown as AsyncIterable<Uint8Array>) {
      hash.update(chunk);
      chunks.push(chunk);
      received += chunk.length;
      if (contentLength > 0) {
        const pct = Math.floor((received / contentLength) * 100);
        if (pct > lastPct) {
          progress.report({ increment: pct - lastPct });
          lastPct = pct;
        }
      }
    }

    const digest = hash.digest('hex');
    if (digest !== expectedHash) {
      fs.rmSync(destPath, { force: true });
      throw new Error(`SHA256 mismatch: expected ${expectedHash}, got ${digest}`);
    }

    fs.writeFileSync(destPath, Buffer.concat(chunks));
    this._channel.appendLine(`[SidecarManager] Download complete: ${received} bytes, SHA256 verified.`);
  }

  /**
   * Shows an error notification for a failed download, offering a button to
   * open the GitHub Releases page for manual download.
   */
  private async _showDownloadError(errMsg: string): Promise<void> {
    const action = await vscode.window.showErrorMessage(
      `Nexus: Failed to download backend — ${errMsg}. Download manually or check your network.`,
      'Open GitHub Releases',
    );
    if (action === 'Open GitHub Releases') {
      await vscode.env.openExternal(vscode.Uri.parse('https://github.com/Hafiz408/Nexus/releases'));
    }
  }

  /**
   * Ensures the backend binary for the given version is available on disk,
   * downloading from GitHub Releases on cache miss.
   *
   * Warm path (cache hit): returns immediately with no network call or notification.
   * Cold path (cache miss): fetches checksum, streams binary with progress UI,
   *   verifies SHA256, extracts, deletes archive.
   * Dev-build / no-matching-release: checksum fetch returns 404 → logs warning,
   *   returns undefined (caller falls back to port 8000).
   */
  private async _ensureExtracted(version: string): Promise<string | undefined> {
    const archiveName = this._archiveName();
    const executableName = this._executableName();
    if (!archiveName || !executableName) { return undefined; }

    // Warm-path guard: binary already cached — no network call, no notification (DIST-02, PRES-02)
    const cacheDir = path.join(path.dirname(this._lockfilePath), 'backend', version);
    const executablePath = path.join(cacheDir, executableName);
    if (fs.existsSync(executablePath)) {
      this._channel.appendLine(`[SidecarManager] Using cached backend at ${executablePath}`);
      return executablePath;
    }

    // Cold path: download from GitHub Releases
    const baseUrl = `https://github.com/Hafiz408/Nexus/releases/download/v${version}`;
    const archiveUrl = `${baseUrl}/${archiveName}`;

    // Fetch checksum before download — if 404, this is a dev build / no matching release
    let expectedHash: string;
    try {
      expectedHash = await this._fetchChecksum(baseUrl, archiveName);
    } catch (err) {
      // Dev build / no-matching-release fallback: log warning + return undefined to use port 8000
      this._channel.appendLine(`[SidecarManager] Checksum fetch failed: ${err instanceof Error ? err.message : String(err)}. No GitHub Release for v${version}?`);
      return undefined;
    }

    // Download with progress notification (DIST-01, PRES-01, PRES-03)
    fs.mkdirSync(cacheDir, { recursive: true });
    const tmpPath = path.join(cacheDir, archiveName + '.tmp');

    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: 'Downloading Nexus backend\u2026',
        cancellable: false,
      },
      async (progress) => {
        await this._downloadAndVerify(archiveUrl, tmpPath, expectedHash, progress);
      }
    );

    // Extract to cache directory
    this._channel.appendLine(`[SidecarManager] Extracting backend archive to ${cacheDir} ...`);
    await new Promise<void>((resolve, reject) => {
      const tarArgs = ['-xzf', tmpPath, '-C', cacheDir];
      const tar = cp.execFile('tar', tarArgs);
      tar.on('close', (code) => {
        if (code === 0) { resolve(); }
        else { reject(new Error(`tar exited with code ${code}`)); }
      });
      tar.on('error', reject);
    });

    // Delete temp archive after successful extraction (CONTEXT.md: "Downloaded archive is deleted after successful extraction")
    fs.rmSync(tmpPath, { force: true });
    this._channel.appendLine('[SidecarManager] Extraction complete.');

    return executablePath;
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /**
   * Start or reuse a backend process.
   *
   * Reuse path  : lockfile exists + version matches + PID alive + healthy  → return existing URL.
   * Spawn path  : anything else → pick a free OS port, spawn binary, write lockfile.
   * Skipped     : unsupported platform or binary missing → returns fallback URL (nothing spawned).
   *
   * Check `didSpawn` after calling to decide whether to wait for health.
   */
  async start(): Promise<string> {
    const version = this._getVersion();

    // --- Reuse path ---
    // HTTP health check is the sole gating condition — no process.kill liveness probe.
    const lock = this._readLock();
    if (lock && lock.version === version) {
      const url = `http://127.0.0.1:${lock.port}`;
      if (await this._checkHealth(url)) {
        this._channel.appendLine(
          `[SidecarManager] Reusing existing backend at ${url} (PID ${lock.pid}).`
        );
        this._backendUrl = url;
        return url;
      }
    }

    // --- Spawn path ---
    if (!this._archiveName()) {
      this._channel.appendLine(
        `[SidecarManager] Unsupported platform: ${process.platform}. Skipping spawn.`
      );
      this._backendUrl = 'http://127.0.0.1:8000';
      return this._backendUrl;
    }

    const binaryPath = await this._ensureExtracted(version);
    if (!binaryPath) {
      this._backendUrl = 'http://127.0.0.1:8000';
      return this._backendUrl;
    }

    const port = await this._getFreePort();
    const url = `http://127.0.0.1:${port}`;
    this._channel.appendLine(`[SidecarManager] Spawning backend on port ${port}: ${binaryPath}`);

    const proc = cp.execFile(binaryPath, ['--port', String(port)]);
    this._process = proc;
    this._didSpawn = true;

    proc.stdout?.on('data', (data: Buffer) => {
      for (const line of data.toString().split(/\r?\n/)) {
        if (line.trim()) { this._channel.appendLine(`[stdout] ${line}`); }
      }
    });

    proc.stderr?.on('data', (data: Buffer) => {
      for (const line of data.toString().split(/\r?\n/)) {
        if (line.trim()) { this._channel.appendLine(`[stderr] ${line}`); }
      }
    });

    proc.on('exit', (code, signal) => {
      this._channel.appendLine(
        `[SidecarManager] Backend process exited — code: ${code}, signal: ${signal}`
      );
      this._process = undefined;
    });

    proc.on('error', (err) => {
      this._channel.appendLine(`[SidecarManager] Failed to start backend: ${err.message}`);
      this._process = undefined;
    });

    if (proc.pid !== undefined) {
      this._writeLock({ pid: proc.pid, port, version });
    }

    this._backendUrl = url;
    return url;
  }

  /** Poll GET /api/health until HTTP 200 or timeout. Only call this after a fresh spawn. */
  async waitForHealth(timeoutMs = 30_000): Promise<void> {
    const healthUrl = `${this._backendUrl}/api/health`;
    const deadline = Date.now() + timeoutMs;

    while (Date.now() < deadline) {
      try {
        const res = await fetch(healthUrl);
        if (res.status === 200) {
          this._channel.appendLine('[SidecarManager] Backend health check passed.');
          return;
        }
      } catch {
        // backend not ready yet — keep polling
      }
      await new Promise<void>((resolve) => setTimeout(resolve, 500));
    }

    throw new Error(`[SidecarManager] Backend did not respond within ${timeoutMs}ms`);
  }

  /** Reveal the backend output channel in the UI. */
  showOutputChannel(): void {
    this._channel.show();
  }

  /**
   * Clean up this manager instance.
   *
   * The backend process is NOT killed here — it will self-terminate via its
   * idle watchdog once all clients stop sending requests.
   */
  dispose(): void {
    this._channel.dispose();
  }
}
