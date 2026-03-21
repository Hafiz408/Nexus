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

// ── Markdown renderer — produces React elements, no innerHTML ──────────────

type ReactChildren = React.ReactNode[];

/** Apply inline formatting (bold, italic, inline code) to a text string.
 *  Returns an array of React nodes. */
function applyInline(text: string, key: string): React.ReactNode {
  // Split on **bold**, *italic*, `code` patterns
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    const k = `${key}-${i}`;
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={k}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('*') && part.endsWith('*')) {
      return <em key={k}>{part.slice(1, -1)}</em>;
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={k}>{part.slice(1, -1)}</code>;
    }
    return part;
  });
}

/** Convert markdown text to an array of React block elements. */
function renderMarkdown(text: string): React.ReactElement {
  const lines = text.split('\n');
  const blocks: ReactChildren = [];
  let listItems: React.ReactNode[] = [];
  let codeLines: string[] = [];
  let inCode = false;
  let blockKey = 0;

  const flushList = () => {
    if (listItems.length > 0) {
      blocks.push(<ul key={blockKey++}>{listItems}</ul>);
      listItems = [];
    }
  };

  const flushCode = () => {
    if (codeLines.length > 0) {
      blocks.push(
        <pre key={blockKey++}>
          <code>{codeLines.join('\n')}</code>
        </pre>
      );
      codeLines = [];
    }
    inCode = false;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Fenced code block toggle
    if (line.startsWith('```')) {
      if (inCode) {
        flushCode();
      } else {
        flushList();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeLines.push(line);
      continue;
    }

    // Headers
    const h3 = line.match(/^### (.+)/);
    const h2 = line.match(/^## (.+)/);
    const h1 = line.match(/^# (.+)/);
    if (h3 || h2 || h1) {
      flushList();
      const match = (h3 || h2 || h1)!;
      const Tag = h3 ? 'h3' : h2 ? 'h2' : 'h1';
      blocks.push(
        <Tag key={blockKey++}>{applyInline(match[1], String(blockKey))}</Tag>
      );
      continue;
    }

    // List items  - item  or  * item  or  1. item
    const li = line.match(/^[ \t]*[-*] (.+)$/) || line.match(/^[ \t]*\d+\. (.+)$/);
    if (li) {
      listItems.push(
        <li key={listItems.length}>{applyInline(li[1], `li-${listItems.length}`)}</li>
      );
      continue;
    }

    // Blank line — flush list, start new paragraph break
    if (line.trim() === '') {
      flushList();
      continue;
    }

    // Regular paragraph line — accumulate consecutive lines into one <p>
    flushList();
    const paraLines: string[] = [line];
    while (i + 1 < lines.length) {
      const next = lines[i + 1];
      if (
        next.trim() === '' ||
        next.startsWith('#') ||
        next.startsWith('```') ||
        next.match(/^[ \t]*[-*] /) ||
        next.match(/^[ \t]*\d+\. /)
      ) {
        break;
      }
      i++;
      paraLines.push(next);
    }
    const paraContent: React.ReactNode[] = [];
    paraLines.forEach((pl, pi) => {
      if (pi > 0) paraContent.push(<br key={`br-${pi}`} />);
      const inlined = applyInline(pl, `p-${blockKey}-${pi}`);
      if (Array.isArray(inlined)) paraContent.push(...inlined);
      else paraContent.push(inlined);
    });
    blocks.push(<p key={blockKey++}>{paraContent}</p>);
  }

  // Flush any remaining list or code block
  flushList();
  if (inCode) flushCode();

  return <>{blocks}</>;
}

// ──────────────────────────────────────────────────────────────────────────

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

    let dotClass = 'status-dot idle';
    let label: React.ReactNode = 'Not indexed';
    let action: React.ReactNode = (
      <button className="status-btn" onClick={handleIndexWorkspace} title="Index workspace">
        ↺
      </button>
    );

    if (status === 'running' || status === 'pending') {
      dotClass = 'status-dot running';
      label = (
        <>
          <span className="spinner" />
          <span>Indexing{nodes_indexed !== undefined ? ` — ${nodes_indexed} nodes` : '…'}</span>
        </>
      );
      action = null;
    } else if (status === 'complete') {
      if (nodes_indexed === 0) {
        dotClass = 'status-dot failed';
        label = <span title="No Python/TypeScript functions found">0 nodes — check path</span>;
      } else {
        dotClass = 'status-dot complete';
        label = <span>{nodes_indexed?.toLocaleString()} nodes</span>;
      }
    } else if (status === 'failed') {
      dotClass = 'status-dot failed';
      label = <span title={error ?? undefined}>Index failed</span>;
    }

    return (
      <div className="status-bar">
        <div className="status-bar-left">
          <span className={dotClass} />
          {label}
        </div>
        {action}
      </div>
    );
  };

  return (
    <div id="root">
      {/* CHAT-04: Index status bar */}
      {renderStatusBar()}

      {/* CHAT-01: Message list */}
      <div className="message-list">
        {messages.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">⌘</div>
            <div className="empty-state-title">Nexus</div>
            <div className="empty-state-hint">
              Ask anything about your codebase — functions, patterns, architecture.
            </div>
          </div>
        ) : (
          messages.map((msg, idx) => {
            const isLastStreaming = msg.isStreaming && idx === messages.length - 1;

            if (msg.role === 'user') {
              return (
                <div key={msg.id} className="message message-user">
                  <div className="message-bubble">{msg.content}</div>
                </div>
              );
            }

            return (
              <div key={msg.id} className="message message-assistant">
                <div className={`message-bubble${isLastStreaming ? ' streaming-cursor' : ''}`}>
                  {renderMarkdown(msg.content)}
                </div>
                {/* CHAT-03: Citation chips */}
                {msg.citations && msg.citations.length > 0 && (
                  <div className="citations">
                    <div className="citations-label">Sources</div>
                    <div className="citations-chips">
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
                  </div>
                )}
              </div>
            );
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="input-area">
        <textarea
          ref={textareaRef}
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about your codebase…"
          disabled={isStreaming}
          rows={1}
        />
        <button onClick={handleSend} disabled={isStreaming || !inputValue.trim()}>
          {isStreaming ? '…' : 'Ask'}
        </button>
      </div>
    </div>
  );
}
