import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as net from 'net';
import * as fs from 'fs';
import * as os from 'os';

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

  private _isProcessAlive(pid: number): boolean {
    try {
      process.kill(pid, 0); // signal 0 = liveness probe; throws ESRCH if process is gone
      return true;
    } catch { return false; }
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
   * Extract the bundled .tar.gz into globalStoragePath/<version>/ on first run,
   * then return the path to the executable.  Subsequent calls for the same version
   * skip extraction and return immediately.
   */
  private async _ensureExtracted(version: string): Promise<string | undefined> {
    const archiveName = this._archiveName();
    const executableName = this._executableName();
    if (!archiveName || !executableName) { return undefined; }

    const archivePath = path.join(this._extensionPath, 'bin', archiveName);
    if (!fs.existsSync(archivePath)) {
      this._channel.appendLine(`[SidecarManager] Archive not found at ${archivePath}. Skipping spawn.`);
      return undefined;
    }

    // Cache extracted files under globalStoragePath/<version>/ so we only
    // extract once per version and re-extract automatically on upgrade.
    const cacheDir = path.join(path.dirname(this._lockfilePath), 'backend', version);
    const executablePath = path.join(cacheDir, executableName);

    if (fs.existsSync(executablePath)) {
      this._channel.appendLine(`[SidecarManager] Using cached backend at ${executablePath}`);
      return executablePath;
    }

    this._channel.appendLine(`[SidecarManager] Extracting backend archive to ${cacheDir} ...`);
    fs.mkdirSync(cacheDir, { recursive: true });

    await new Promise<void>((resolve, reject) => {
      // `tar` is available on macOS, Linux, and Windows 10+.
      const tarArgs = process.platform === 'win32'
        ? ['-xzf', archivePath, '-C', cacheDir]
        : ['-xzf', archivePath, '-C', cacheDir];
      const tar = cp.spawn('tar', tarArgs, { stdio: 'pipe' });
      tar.on('close', (code) => {
        if (code === 0) { resolve(); }
        else { reject(new Error(`tar exited with code ${code}`)); }
      });
      tar.on('error', reject);
    });

    // Permissions are preserved from the tar (set at build time in build.py).

    this._channel.appendLine(`[SidecarManager] Extraction complete.`);
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
    const lock = this._readLock();
    if (lock && lock.version === version && this._isProcessAlive(lock.pid)) {
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

    const proc = cp.execFile(binaryPath, ['--port', String(port)], {
      detached: true,              // independent of the extension host process
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    proc.unref();                  // don't keep the extension host alive for this child
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
   * The backend process is NOT killed — it is detached and shared across all
   * windows. It will self-terminate via its idle watchdog once all clients stop
   * sending requests.
   */
  dispose(): void {
    this._channel.dispose();
  }
}
