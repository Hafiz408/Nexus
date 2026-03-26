import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as net from 'net';
import * as fs from 'fs';

export class SidecarManager implements vscode.Disposable {
  private _process: cp.ChildProcess | undefined;
  private readonly _channel: vscode.OutputChannel;
  private readonly _backendUrl: string;
  private readonly _extensionPath: string;

  constructor(extensionPath: string, backendUrl: string) {
    this._extensionPath = extensionPath;
    this._backendUrl = backendUrl;
    this._channel = vscode.window.createOutputChannel('Nexus Backend');
  }

  /** Returns true if port 8000 is already occupied (dev mode) */
  private _isPortOccupied(): Promise<boolean> {
    return new Promise((resolve) => {
      const socket = net.createConnection({ host: 'localhost', port: 8000 });
      const timer = setTimeout(() => {
        socket.destroy();
        resolve(false);
      }, 500);

      socket.on('connect', () => {
        clearTimeout(timer);
        socket.destroy();
        resolve(true);
      });

      socket.on('error', () => {
        clearTimeout(timer);
        resolve(false);
      });
    });
  }

  /** Poll GET /health until HTTP 200 or timeout */
  async waitForHealth(timeoutMs = 30_000): Promise<void> {
    const healthUrl = `${this._backendUrl}/health`;
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

    throw new Error(`[SidecarManager] Backend did not respond with HTTP 200 within ${timeoutMs}ms`);
  }

  /** Resolve the binary name for the current platform */
  private _binaryName(): string | undefined {
    if (process.platform === 'darwin') {
      return 'nexus-backend-mac';
    } else if (process.platform === 'win32') {
      return 'nexus-backend-win.exe';
    }
    return undefined;
  }

  /** Spawn the sidecar binary. Returns false if port already occupied (dev skip). */
  async start(): Promise<boolean> {
    const occupied = await this._isPortOccupied();
    if (occupied) {
      this._channel.appendLine('[SidecarManager] Port 8000 already in use — skipping sidecar spawn (dev mode).');
      return false;
    }

    const binaryName = this._binaryName();
    if (!binaryName) {
      this._channel.appendLine(`[SidecarManager] Unsupported platform: ${process.platform}. Skipping spawn.`);
      return false;
    }

    const binaryPath = path.join(this._extensionPath, 'bin', binaryName);

    if (!fs.existsSync(binaryPath)) {
      this._channel.appendLine(`[SidecarManager] Binary not found at ${binaryPath}. Skipping spawn.`);
      return false;
    }

    this._channel.appendLine(`[SidecarManager] Spawning backend: ${binaryPath}`);

    const proc = cp.spawn(binaryPath, [], { stdio: ['ignore', 'pipe', 'pipe'] });
    this._process = proc;

    proc.stdout?.on('data', (data: Buffer) => {
      const lines = data.toString().split(/\r?\n/);
      for (const line of lines) {
        if (line.trim()) {
          this._channel.appendLine(`[stdout] ${line}`);
        }
      }
    });

    proc.stderr?.on('data', (data: Buffer) => {
      const lines = data.toString().split(/\r?\n/);
      for (const line of lines) {
        if (line.trim()) {
          this._channel.appendLine(`[stderr] ${line}`);
        }
      }
    });

    proc.on('exit', (code, signal) => {
      this._channel.appendLine(`[SidecarManager] Backend process exited — code: ${code}, signal: ${signal}`);
      this._process = undefined;
    });

    proc.on('error', (err) => {
      this._channel.appendLine(`[SidecarManager] Failed to start backend process: ${err.message}`);
      this._process = undefined;
    });

    return true;
  }

  /** Kill the sidecar process */
  dispose(): void {
    if (this._process) {
      this._channel.appendLine('[SidecarManager] Terminating backend process.');
      this._process.kill();
      this._process = undefined;
    }
    this._channel.dispose();
  }
}
