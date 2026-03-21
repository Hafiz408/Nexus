import React, { useState, useEffect, useRef, useCallback } from 'react';

// acquireVsCodeApi is injected by VS Code into the webview context.
// Must be called exactly once — store reference.
declare function acquireVsCodeApi(): {
  postMessage(msg: unknown): void;
  getState(): unknown;
  setState(state: unknown): void;
};

interface Citation {
  node_id: string;
  file_path: string;
  line_start: number;
  line_end: number;
  name: string;
  type: string;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
  isStreaming?: boolean;
}

interface IndexStatus {
  status: 'pending' | 'running' | 'complete' | 'failed' | 'not_indexed';
  nodes_indexed?: number;
  error?: string | null;
}

type IncomingMessage =
  | { type: 'token'; content: string }
  | { type: 'citations'; citations: Citation[] }
  | { type: 'done'; retrieval_stats: Record<string, unknown> }
  | { type: 'error'; message: string }
  | { type: 'indexStatus'; status: IndexStatus };

// Initialize vscode API once at module level
const vscode = acquireVsCodeApi();

let messageIdCounter = 0;
function newId(): string {
  return String(++messageIdCounter);
}

export function App(): React.JSX.Element {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [indexStatus, setIndexStatus] = useState<IndexStatus>({ status: 'not_indexed' });
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom when messages update
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // CHAT-02: Listen for messages from extension host
  useEffect(() => {
    const handleMessage = (event: MessageEvent): void => {
      const msg = event.data as IncomingMessage;

      switch (msg.type) {
        case 'token':
          // Append token to last assistant message (streaming)
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.role === 'assistant' && last.isStreaming) {
              return [
                ...prev.slice(0, -1),
                { ...last, content: last.content + msg.content },
              ];
            }
            // Start new assistant message
            return [
              ...prev,
              {
                id: newId(),
                role: 'assistant',
                content: msg.content,
                isStreaming: true,
              },
            ];
          });
          break;

        case 'citations':
          // Attach citations to last assistant message
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.role === 'assistant') {
              return [
                ...prev.slice(0, -1),
                { ...last, citations: msg.citations },
              ];
            }
            return prev;
          });
          break;

        case 'done':
          // Mark last assistant message as no longer streaming
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.role === 'assistant') {
              return [
                ...prev.slice(0, -1),
                { ...last, isStreaming: false },
              ];
            }
            return prev;
          });
          setIsStreaming(false);
          break;

        case 'error':
          setMessages((prev) => [
            ...prev,
            {
              id: newId(),
              role: 'assistant',
              content: `Error: ${msg.message}`,
              isStreaming: false,
            },
          ]);
          setIsStreaming(false);
          break;

        case 'indexStatus':
          setIndexStatus(msg.status);
          break;
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  const handleSend = useCallback((): void => {
    const question = inputValue.trim();
    if (!question || isStreaming) {
      return;
    }

    // Add user message immediately
    setMessages((prev) => [
      ...prev,
      { id: newId(), role: 'user', content: question },
    ]);
    setInputValue('');
    setIsStreaming(true);

    // Send query to extension host (which proxies to backend SSE)
    vscode.postMessage({ type: 'query', question });
  }, [inputValue, isStreaming]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>): void => {
    // Send on Enter, allow Shift+Enter for newline
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // CHAT-03: Citation click sends openFile to extension host
  const handleCitationClick = (citation: Citation): void => {
    vscode.postMessage({
      type: 'openFile',
      filePath: citation.file_path,
      lineStart: citation.line_start,
    });
  };

  // CHAT-04: Status bar actions
  const handleIndexWorkspace = (): void => {
    vscode.postMessage({ type: 'indexWorkspace' });
  };

  const renderStatusBar = (): React.JSX.Element => {
    const { status, nodes_indexed, error } = indexStatus;
    let content: React.ReactNode;

    if (status === 'running' || status === 'pending') {
      content = (
        <>
          <span className="spinner" />
          <span>Indexing{nodes_indexed !== undefined ? ` — ${nodes_indexed} nodes` : '...'}</span>
        </>
      );
    } else if (status === 'complete' && nodes_indexed !== undefined) {
      if (nodes_indexed === 0) {
        content = (
          <>
            <span style={{ color: 'var(--vscode-errorForeground)' }}>
              ⚠ Ready — 0 nodes. No Python/TypeScript functions found.
            </span>
            <button onClick={handleIndexWorkspace} title="Re-index">Re-index</button>
          </>
        );
      } else {
        content = (
          <>
            <span>✓ Ready — {nodes_indexed} nodes</span>
            <button onClick={handleIndexWorkspace} title="Re-index">↺</button>
          </>
        );
      }
    } else if (status === 'failed') {
      content = (
        <>
          <span style={{ color: 'var(--vscode-errorForeground)' }}
                title={error ?? undefined}>
            ✗ Index failed{error ? ` — ${error}` : ''}
          </span>
          <button onClick={handleIndexWorkspace}>Retry</button>
        </>
      );
    } else {
      content = (
        <>
          <span>Not indexed</span>
          <button onClick={handleIndexWorkspace}>Index Workspace</button>
        </>
      );
    }

    return <div className="status-bar">{content}</div>;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* CHAT-04: Index status bar */}
      {renderStatusBar()}

      {/* CHAT-01: Message list */}
      <div className="message-list">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`message ${msg.role === 'user' ? 'message-user' : 'message-assistant'}`}
          >
            <div>{msg.content}</div>
            {/* CHAT-03: Citation chips */}
            {msg.citations && msg.citations.length > 0 && (
              <div className="citations">
                {msg.citations.map((c) => (
                  <button
                    key={c.node_id}
                    className="citation-chip"
                    onClick={() => handleCitationClick(c)}
                    title={`${c.file_path}:${c.line_start}-${c.line_end}`}
                  >
                    {c.file_path.split('/').pop()}:{c.line_start}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="input-area">
        <textarea
          ref={textareaRef}
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about your codebase..."
          disabled={isStreaming}
          rows={1}
        />
        <button onClick={handleSend} disabled={isStreaming || !inputValue.trim()}>
          {isStreaming ? '...' : 'Ask'}
        </button>
      </div>
    </div>
  );
}
