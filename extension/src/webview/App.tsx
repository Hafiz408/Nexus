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
  edges_indexed?: number;
  files_processed?: number;
  error?: string | null;
}

interface LogEntry {
  id: string;
  level: 'info' | 'warning' | 'error';
  message: string;
  time: string;
}

type IncomingMessage =
  | { type: 'token'; content: string }
  | { type: 'citations'; citations: Citation[] }
  | { type: 'done'; retrieval_stats: Record<string, unknown> }
  | { type: 'error'; message: string }
  | { type: 'indexStatus'; status: IndexStatus }
  | { type: 'log'; level: LogEntry['level']; message: string };

// Initialize vscode API once at module level
const vscode = acquireVsCodeApi();

let messageIdCounter = 0;
function newId(): string {
  return String(++messageIdCounter);
}

// ── Markdown renderer — produces React elements ────────────────────────────

type ReactChildren = React.ReactNode[];

function applyInline(text: string, key: string): React.ReactNode {
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
        <pre key={blockKey++}><code>{codeLines.join('\n')}</code></pre>
      );
      codeLines = [];
    }
    inCode = false;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (line.startsWith('```')) {
      if (inCode) { flushCode(); } else { flushList(); inCode = true; }
      continue;
    }
    if (inCode) { codeLines.push(line); continue; }

    const h3 = line.match(/^### (.+)/);
    const h2 = line.match(/^## (.+)/);
    const h1 = line.match(/^# (.+)/);
    if (h3 || h2 || h1) {
      flushList();
      const match = (h3 || h2 || h1)!;
      const Tag = h3 ? 'h3' : h2 ? 'h2' : 'h1';
      blocks.push(<Tag key={blockKey++}>{applyInline(match[1], String(blockKey))}</Tag>);
      continue;
    }

    const li = line.match(/^[ \t]*[-*] (.+)$/) || line.match(/^[ \t]*\d+\. (.+)$/);
    if (li) {
      listItems.push(<li key={listItems.length}>{applyInline(li[1], `li-${listItems.length}`)}</li>);
      continue;
    }

    if (line.trim() === '') { flushList(); continue; }

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
      ) break;
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
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [logsExpanded, setLogsExpanded] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const addLog = useCallback((level: LogEntry['level'], message: string) => {
    const now = new Date();
    const time = now.toTimeString().slice(0, 8);
    setLogs((prev) =>
      [{ id: `${Date.now()}-${Math.random()}`, level, message, time }, ...prev].slice(0, 100)
    );
  }, []);

  // Listen for messages from extension host
  useEffect(() => {
    const handleMessage = (event: MessageEvent): void => {
      const msg = event.data as IncomingMessage;

      switch (msg.type) {
        case 'token':
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.role === 'assistant' && last.isStreaming) {
              return [...prev.slice(0, -1), { ...last, content: last.content + msg.content }];
            }
            return [...prev, { id: newId(), role: 'assistant', content: msg.content, isStreaming: true }];
          });
          break;

        case 'citations':
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.role === 'assistant') {
              return [...prev.slice(0, -1), { ...last, citations: msg.citations }];
            }
            return prev;
          });
          break;

        case 'done':
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.role === 'assistant') {
              return [...prev.slice(0, -1), { ...last, isStreaming: false }];
            }
            return prev;
          });
          setIsStreaming(false);
          break;

        case 'error':
          setMessages((prev) => [
            ...prev,
            { id: newId(), role: 'assistant', content: `Error: ${msg.message}`, isStreaming: false },
          ]);
          setIsStreaming(false);
          addLog('error', `Error: ${msg.message}`);
          break;

        case 'indexStatus': {
          const s = msg.status;
          setIndexStatus(s);
          if (s.status === 'running') {
            addLog('info', 'Indexing started…');
          } else if (s.status === 'complete') {
            if (s.nodes_indexed === 0) {
              addLog('warning', '0 nodes indexed — verify repo contains .py/.ts files');
            } else {
              const parts = [`${s.nodes_indexed} nodes`];
              if (s.files_processed) parts.push(`${s.files_processed} files`);
              if (s.edges_indexed) parts.push(`${s.edges_indexed} edges`);
              addLog('info', `Index complete: ${parts.join(' · ')}`);
            }
          } else if (s.status === 'failed') {
            addLog('error', `Index failed${s.error ? ': ' + s.error : ''}`);
          }
          break;
        }

        case 'log':
          addLog(msg.level, msg.message);
          break;
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [addLog]);

  const handleSend = useCallback((): void => {
    const question = inputValue.trim();
    if (!question || isStreaming) return;

    setMessages((prev) => [...prev, { id: newId(), role: 'user', content: question }]);
    setInputValue('');
    setIsStreaming(true);

    const preview = question.length > 55 ? `${question.slice(0, 55)}…` : question;
    addLog('info', `Query: "${preview}"`);
    vscode.postMessage({ type: 'query', question });
  }, [inputValue, isStreaming, addLog]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>): void => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleCitationClick = (citation: Citation): void => {
    vscode.postMessage({ type: 'openFile', filePath: citation.file_path, lineStart: citation.line_start });
  };

  const handleIndexWorkspace = (): void => {
    vscode.postMessage({ type: 'indexWorkspace' });
  };

  // ── Header section ────────────────────────────────────────────────────────
  const renderHeader = (): React.JSX.Element => {
    const { status, nodes_indexed, files_processed, edges_indexed, error } = indexStatus;

    let dotClass = 'status-dot idle';
    let statusText: React.ReactNode = 'Not indexed';
    let metaText: string | null = null;

    if (status === 'running' || status === 'pending') {
      dotClass = 'status-dot running';
      statusText = (
        <>
          <span className="spinner" />
          <span>Indexing{nodes_indexed !== undefined ? ` — ${nodes_indexed} nodes` : '…'}</span>
        </>
      );
    } else if (status === 'complete') {
      if (nodes_indexed === 0) {
        dotClass = 'status-dot failed';
        statusText = '0 nodes — check repo';
      } else {
        dotClass = 'status-dot complete';
        statusText = `${nodes_indexed?.toLocaleString()} nodes`;
        const metaParts: string[] = [];
        if (files_processed) metaParts.push(`${files_processed} files`);
        if (edges_indexed) metaParts.push(`${edges_indexed} edges`);
        if (metaParts.length) metaText = metaParts.join(' · ');
      }
    } else if (status === 'failed') {
      dotClass = 'status-dot failed';
      statusText = 'Index failed';
      if (error) metaText = error;
    }

    return (
      <div className="panel-header">
        <div className="header-main">
          <div className="header-status">
            <span className={dotClass} />
            <span>{statusText}</span>
          </div>
          <button
            className="icon-btn"
            onClick={handleIndexWorkspace}
            title={status === 'complete' ? 'Re-index workspace' : 'Index workspace'}
          >
            ↺
          </button>
        </div>
        {metaText && <div className="header-meta">{metaText}</div>}
      </div>
    );
  };

  // ── General (activity log) section ───────────────────────────────────────
  const warnCount = logs.filter((l) => l.level === 'warning').length;
  const errorCount = logs.filter((l) => l.level === 'error').length;

  const renderGeneral = (): React.JSX.Element => (
    <div className="panel-general">
      <div
        className="section-bar general-section-bar"
        onClick={() => setLogsExpanded((v) => !v)}
      >
        <div className="section-label">
          <span>{logsExpanded ? '▾' : '▸'}</span>
          <span>Activity</span>
          {errorCount > 0 && <span className="log-badge error">{errorCount}</span>}
          {warnCount > 0 && <span className="log-badge warning">{warnCount}</span>}
        </div>
        {logs.length > 0 && (
          <button
            className="icon-btn"
            title="Clear activity log"
            onClick={(e) => { e.stopPropagation(); setLogs([]); }}
          >
            ×
          </button>
        )}
      </div>

      {logsExpanded && (
        <div className="log-list">
          {logs.length === 0 ? (
            <div className="log-entry log-info">
              <span className="log-message" style={{ opacity: 0.4 }}>No activity yet</span>
            </div>
          ) : (
            logs.map((entry) => (
              <div key={entry.id} className={`log-entry log-${entry.level}`}>
                <span className="log-time">{entry.time}</span>
                <span className="log-message">{entry.message}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div id="root">
      {/* ① Header — index status */}
      {renderHeader()}

      {/* ② Chat — message history + input */}
      <div className="panel-chat">
        <div className="section-bar chat-section-bar">
          <span className="section-label">Chat</span>
          {messages.length > 0 && (
            <button
              className="icon-btn"
              title="Clear conversation"
              disabled={isStreaming}
              onClick={() => setMessages([])}
            >
              ⊘
            </button>
          )}
        </div>

        <div className="message-list">
          {messages.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">⌘</div>
              <div className="empty-state-title">Ask your codebase</div>
              <div className="empty-state-hint">
                Functions, patterns, architecture — just ask.
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
                  {msg.citations && msg.citations.length > 0 && (
                    <div className="citations">
                      <div className="citations-label">Sources</div>
                      <div className="citations-chips">
                        {msg.citations.map((c) => {
                          const filename = c.file_path.split('/').pop() ?? c.file_path;
                          const label =
                            filename.length > 18
                              ? `${filename.slice(0, 16)}…:${c.line_start}`
                              : `${filename}:${c.line_start}`;
                          return (
                            <button
                              key={c.node_id}
                              className="citation-chip"
                              onClick={() => handleCitationClick(c)}
                              title={`${c.file_path}:${c.line_start}–${c.line_end}`}
                            >
                              {label}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              );
            })
          )}
          <div ref={messagesEndRef} />
        </div>

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

      {/* ③ General — activity log */}
      {renderGeneral()}
    </div>
  );
}
