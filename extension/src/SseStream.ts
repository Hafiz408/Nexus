import * as vscode from 'vscode';
import { Citation } from './types';

const QUERY_TIMEOUT_MS = 30_000;

/** Build an AbortSignal that fires on the earliest of: user cancel or 30 s timeout.
 *
 * AbortSignal.any() requires Node 20 / Electron 31 (VS Code ≥ 1.90). On older
 * hosts the user-cancel signal is returned as-is (no timeout), which is safe —
 * the stream will still be cancelled on new queries and sidebar close.
 */
function makeFetchSignal(userSignal?: AbortSignal): AbortSignal {
  const timeout = AbortSignal.timeout(QUERY_TIMEOUT_MS);
  if (!userSignal) { return timeout; }
  if (typeof AbortSignal.any === 'function') {
    return AbortSignal.any([userSignal, timeout]);
  }
  return userSignal;  // graceful degradation: cancel works, timeout does not
}

export async function streamQuery(
  question: string,
  repoPath: string,
  webview: vscode.Webview,
  backendUrl: string,
  onCitations?: (citations: Citation[]) => void,
  intentHint?: string,
  targetNodeId?: string,
  selectedFile?: string,
  selectedRange?: [number, number],
  repoRoot?: string,
  dbPath?: string,
  signal?: AbortSignal,
): Promise<void> {
  const config = vscode.workspace.getConfiguration('nexus');
  const maxNodes = config.get<number>('maxNodes', 10);
  const hopDepth = config.get<number>('hopDepth', 1);

  const fetchSignal = makeFetchSignal(signal);

  let response: Response;
  try {
    response = await fetch(`${backendUrl}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: fetchSignal,
      body: JSON.stringify({
        question,
        repo_path: repoPath,
        max_nodes: maxNodes,
        hop_depth: hopDepth,
        ...(intentHint    ? { intent_hint: intentHint }       : {}),
        ...(targetNodeId  ? { target_node_id: targetNodeId }  : {}),
        ...(selectedFile  ? { selected_file: selectedFile }   : {}),
        ...(selectedRange ? { selected_range: selectedRange } : {}),
        ...(repoRoot      ? { repo_root: repoRoot }           : {}),
        ...(dbPath        ? { db_path: dbPath }               : {}),  // NEW
      }),
    });
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') {
      if (signal?.aborted) { return; }  // user-requested cancel — silent
      void webview.postMessage({ type: 'error', message: 'Query timed out. Please try again.' });
      return;
    }
    void webview.postMessage({ type: 'error', message: `Cannot reach backend: ${String(err)}` });
    return;
  }

  if (!response.ok || !response.body) {
    void webview.postMessage({ type: 'error', message: `Backend error: ${response.status}` });
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      // SSE events are separated by double newline (\n\n)
      // Split and keep last incomplete chunk in buffer
      const parts = buffer.split('\n\n');
      buffer = parts.pop() ?? '';

      for (const part of parts) {
        if (!part.trim()) {
          continue;
        }
        const lines = part.split('\n');
        const eventLine = lines.find((l) => l.startsWith('event: '));
        const dataLine = lines.find((l) => l.startsWith('data: '));
        if (!eventLine || !dataLine) {
          continue;
        }

        const eventType = eventLine.slice(7).trim();
        try {
          const data = JSON.parse(dataLine.slice(6)) as Record<string, unknown>;

          switch (eventType) {
            case 'token':
              void webview.postMessage({ type: 'token', content: data['content'] as string });
              break;
            case 'citations': {
              const citations = data['citations'] as Citation[];
              void webview.postMessage({ type: 'citations', citations });
              onCitations?.(citations);
              break;
            }
            case 'done':
              void webview.postMessage({ type: 'done', retrieval_stats: data });
              break;
            case 'error':
              void webview.postMessage({ type: 'error', message: data['message'] as string });
              break;
            case 'result': {
              void webview.postMessage({
                type: 'result',
                intent: data['intent'] as string,
                result: data['result'] as Record<string, unknown>,
                has_github_token: data['has_github_token'] as boolean | undefined,
                file_written: data['file_written'] as boolean | undefined,
                written_path: data['written_path'] as string | null | undefined,
              });
              break;
            }
          }
        } catch {
          // Skip malformed events — do not crash the stream
        }
      }
    }
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') {
      if (signal?.aborted) { return; }  // user-requested cancel — silent
      // Timeout fired during streaming
      void webview.postMessage({ type: 'error', message: 'Query timed out. Please try again.' });
      return;
    }
    // Stream interrupted (backend crash, network drop) — notify webview so isStreaming resets
    void webview.postMessage({
      type: 'error',
      message: `Stream interrupted: ${err instanceof Error ? err.message : String(err)}`,
    });
  } finally {
    reader.releaseLock();
  }
}
