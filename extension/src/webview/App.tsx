import React, { useState, useEffect, useRef, useCallback } from 'react';

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

const vscode = acquireVsCodeApi();

let counter = 0;
const newId = () => String(++counter);

// ── Markdown renderer (React elements, no innerHTML) ───────────────────────

function applyInline(text: string, key: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    const k = `${key}-i${i}`;
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={k}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('*') && part.endsWith('*')) return <em key={k}>{part.slice(1, -1)}</em>;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={k}>{part.slice(1, -1)}</code>;
    return part;
  });
}

function renderMarkdown(text: string): React.ReactElement {
  const lines = text.split('\n');
  const blocks: React.ReactNode[] = [];
  let listItems: React.ReactNode[] = [];
  let codeLines: string[] = [];
  let inCode = false;
  let bk = 0;

  const flushList = () => {
    if (listItems.length) { blocks.push(<ul key={bk++}>{listItems}</ul>); listItems = []; }
  };
  const flushCode = () => {
    if (codeLines.length) { blocks.push(<pre key={bk++}><code>{codeLines.join('\n')}</code></pre>); codeLines = []; }
    inCode = false;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith('```')) { inCode ? flushCode() : (flushList(), inCode = true); continue; }
    if (inCode) { codeLines.push(line); continue; }

    const h = line.match(/^(#{1,3}) (.+)/);
    if (h) {
      flushList();
      const Tag = (['h1', 'h2', 'h3'] as const)[h[1].length - 1];
      blocks.push(<Tag key={bk++}>{applyInline(h[2], String(bk))}</Tag>);
      continue;
    }

    const li = line.match(/^[ \t]*(?:[-*]|\d+\.) (.+)/);
    if (li) { listItems.push(<li key={listItems.length}>{applyInline(li[1], `li${listItems.length}`)}</li>); continue; }

    if (!line.trim()) { flushList(); continue; }

    flushList();
    const para: string[] = [line];
    while (i + 1 < lines.length) {
      const nx = lines[i + 1];
      if (!nx.trim() || nx.startsWith('#') || nx.startsWith('```') || nx.match(/^[ \t]*(?:[-*]|\d+\.) /)) break;
      para.push(lines[++i]);
    }
    const content: React.ReactNode[] = [];
    para.forEach((pl, pi) => {
      if (pi) content.push(<br key={`br${pi}`} />);
      const r = applyInline(pl, `p${bk}l${pi}`);
      Array.isArray(r) ? content.push(...r) : content.push(r);
    });
    blocks.push(<p key={bk++}>{content}</p>);
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
  const [indexExpanded, setIndexExpanded] = useState(true);
  const [activityExpanded, setActivityExpanded] = useState(false);
  const [expandedCitations, setExpandedCitations] = useState<Set<string>>(new Set());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const addLog = useCallback((level: LogEntry['level'], message: string) => {
    const t = new Date().toTimeString().slice(0, 8);
    setLogs((prev) => [{ id: `${Date.now()}-${Math.random()}`, level, message, time: t }, ...prev].slice(0, 100));
  }, []);

  useEffect(() => {
    const handle = (event: MessageEvent): void => {
      const msg = event.data as IncomingMessage;
      switch (msg.type) {
        case 'token':
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.role === 'assistant' && last.isStreaming) {
              return [...prev.slice(0, -1), { ...last, content: last.content + msg.content }];
            }
            return [...prev, { id: newId(), role: 'assistant', content: msg.content, isStreaming: true }];
          });
          break;

        case 'citations':
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.role === 'assistant') return [...prev.slice(0, -1), { ...last, citations: msg.citations }];
            return prev;
          });
          break;

        case 'done':
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last?.role === 'assistant') return [...prev.slice(0, -1), { ...last, isStreaming: false }];
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
            // Auto-expand Activity so progress is visible
            setActivityExpanded(true);
            // Only log the "started" event once (no files_processed yet)
            if (s.files_processed === undefined) {
              addLog('info', 'Indexing started…');
            } else {
              addLog('info', `Parsing ${s.files_processed} files…`);
            }
          } else if (s.status === 'complete') {
            const parts = [`${s.nodes_indexed ?? 0} nodes`];
            if (s.files_processed) parts.push(`${s.files_processed} files`);
            if (s.edges_indexed) parts.push(`${s.edges_indexed} edges`);
            if ((s.nodes_indexed ?? 0) === 0) {
              addLog('warning', `0 nodes indexed — verify repo contains .py/.ts files`);
            } else {
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
    window.addEventListener('message', handle);
    return () => window.removeEventListener('message', handle);
  }, [addLog]);

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>): void => {
      setInputValue(e.target.value);
      const el = e.target;
      el.style.height = 'auto';
      el.style.height = `${el.scrollHeight}px`;
    },
    []
  );

  const handleClear = useCallback(() => {
    setMessages([]);
    setExpandedCitations(new Set());
  }, []);

  const handleSend = useCallback((): void => {
    const question = inputValue.trim();
    if (!question || isStreaming) return;
    setMessages((prev) => [...prev, { id: newId(), role: 'user', content: question }]);
    setInputValue('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
    setIsStreaming(true);
    addLog('info', `Query: "${question.length > 55 ? question.slice(0, 55) + '…' : question}"`);
    vscode.postMessage({ type: 'query', question });
  }, [inputValue, isStreaming, addLog]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>): void => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  const handleCitationClick = (c: Citation): void => {
    vscode.postMessage({ type: 'openFile', filePath: c.file_path, lineStart: c.line_start });
  };

  const handleIndexWorkspace = (): void => {
    vscode.postMessage({ type: 'indexWorkspace' });
  };

  // ── Section header helper ──────────────────────────────────────────────
  const SectionHeader = ({
    expanded,
    onToggle,
    title,
    actions,
    badges,
  }: {
    expanded: boolean;
    onToggle: () => void;
    title: string;
    actions?: React.ReactNode;
    badges?: React.ReactNode;
  }) => (
    <div className="section-header" onClick={onToggle}>
      <div className="section-header-title">
        <span className="section-chevron">{expanded ? '▾' : '▸'}</span>
        {title}
        {badges}
      </div>
      <div className="section-header-actions" onClick={(e) => e.stopPropagation()}>
        {actions}
      </div>
    </div>
  );

  // ── Index section ──────────────────────────────────────────────────────
  const { status, nodes_indexed, files_processed, edges_indexed, error } = indexStatus;
  const isIndexing = status === 'running' || status === 'pending';

  let dotClass = 'status-dot idle';
  let nodeLabel: React.ReactNode = 'Not indexed';
  let metaLabel: string | null = null;

  if (isIndexing) {
    dotClass = 'status-dot running';
    nodeLabel = (
      <>
        <span className="spinner" />
        <span>
          {files_processed !== undefined
            ? `Indexing — ${files_processed} files…`
            : 'Indexing…'}
        </span>
      </>
    );
  } else if (status === 'complete') {
    if ((nodes_indexed ?? 0) === 0) {
      dotClass = 'status-dot failed';
      nodeLabel = '0 nodes — check repo';
    } else {
      dotClass = 'status-dot complete';
      nodeLabel = `${nodes_indexed!.toLocaleString()} nodes`;
      const mp: string[] = [];
      if (files_processed) mp.push(`${files_processed} files`);
      if (edges_indexed) mp.push(`${edges_indexed} edges`);
      if (mp.length) metaLabel = mp.join(' · ');
    }
  } else if (status === 'failed') {
    dotClass = 'status-dot failed';
    nodeLabel = 'Index failed';
    if (error) metaLabel = error;
  }

  // ── Activity badges ────────────────────────────────────────────────────
  const warnCount = logs.filter((l) => l.level === 'warning').length;
  const errorCount = logs.filter((l) => l.level === 'error').length;

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <div id="root">

      {/* ① INDEX */}
      <div className="panel-section">
        <SectionHeader
          expanded={indexExpanded}
          onToggle={() => setIndexExpanded((v) => !v)}
          title="Index"
          actions={
            <button
              className="icon-btn"
              onClick={handleIndexWorkspace}
              title={status === 'complete' ? 'Re-index workspace' : 'Index workspace'}
            >
              ↺
            </button>
          }
        />
        {indexExpanded && (
          <div className="index-body">
            <div className="index-status-row">
              <span className={dotClass} />
              {nodeLabel}
            </div>
            {isIndexing && (
              <div className="progress-bar-track">
                <div className="progress-bar-fill" />
              </div>
            )}
            {metaLabel && <div className="index-meta">{metaLabel}</div>}
          </div>
        )}
      </div>

      {/* ② CHAT */}
      <div className="panel-section panel-section-chat">
        <SectionHeader
          expanded={true}
          onToggle={() => {/* chat section always open */}}
          title="Chat"
          actions={
            messages.length > 0 ? (
              <button
                className="icon-btn"
                title="Clear conversation"
                disabled={isStreaming}
                onClick={handleClear}
              >
                ⊘
              </button>
            ) : null
          }
        />
        <div className="chat-body">
          <div className="message-list">
            {messages.length === 0 ? (
              <div className="empty-state">
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
                          {(() => {
                            const CITATION_PREVIEW = 5;
                            const isExpanded = expandedCitations.has(msg.id);
                            const shownCitations = isExpanded ? msg.citations : msg.citations.slice(0, CITATION_PREVIEW);
                            const hiddenCount = msg.citations.length - CITATION_PREVIEW;
                            return (
                              <>
                                {shownCitations.map((c) => {
                                  const filename = c.file_path.split('/').pop() ?? c.file_path;
                                  const label = filename.length > 18
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
                                {!isExpanded && hiddenCount > 0 && (
                                  <button
                                    className="citation-chip citation-chip-more"
                                    onClick={() => setExpandedCitations(prev => new Set([...prev, msg.id]))}
                                    title={`Show ${hiddenCount} more citations`}
                                  >
                                    +{hiddenCount} more
                                  </button>
                                )}
                              </>
                            );
                          })()}
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
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="Ask about your codebase…"
              disabled={isStreaming}
            />
            <button className="send-btn" onClick={handleSend} disabled={isStreaming || !inputValue.trim()}>
              {isStreaming ? '…' : 'Ask'}
            </button>
          </div>
        </div>
      </div>

      {/* ③ ACTIVITY */}
      <div className="panel-section">
        <SectionHeader
          expanded={activityExpanded}
          onToggle={() => setActivityExpanded((v) => !v)}
          title="Activity"
          badges={
            <>
              {errorCount > 0 && <span className="log-badge error">{errorCount}</span>}
              {warnCount > 0 && <span className="log-badge warning">{warnCount}</span>}
            </>
          }
          actions={
            logs.length > 0 ? (
              <button
                className="icon-btn icon-btn-hoverable"
                title="Clear activity log"
                onClick={() => setLogs([])}
              >
                ×
              </button>
            ) : null
          }
        />
        {activityExpanded && (
          <div className="activity-body">
            {/* Live progress row — pinned at top while indexing */}
            {isIndexing && (
              <div className="log-entry log-info log-progress">
                <div className="log-progress-row">
                  <span className="spinner" />
                  <span className="log-message">
                    {files_processed !== undefined
                      ? `Indexing — parsing ${files_processed} files…`
                      : 'Indexing started…'}
                  </span>
                </div>
                <div className="progress-bar-track">
                  <div className="progress-bar-fill" />
                </div>
              </div>
            )}
            {logs.length === 0 && !isIndexing ? (
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

    </div>
  );
}
