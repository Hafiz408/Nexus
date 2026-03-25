import * as vscode from 'vscode';
import { Citation } from './types';

export async function streamQuery(
  question: string,
  repoPath: string,
  webview: vscode.Webview,
  backendUrl: string,
  onCitations?: (citations: Citation[]) => void,
  intentHint?: string,
): Promise<void> {
  const config = vscode.workspace.getConfiguration('nexus');
  const maxNodes = config.get<number>('maxNodes', 10);
  const hopDepth = config.get<number>('hopDepth', 1);

  let response: Response;
  try {
    response = await fetch(`${backendUrl}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        repo_path: repoPath,
        max_nodes: maxNodes,
        hop_depth: hopDepth,
        ...(intentHint ? { intent_hint: intentHint } : {}),
      }),
    });
  } catch (err) {
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
  } finally {
    reader.releaseLock();
  }
}
