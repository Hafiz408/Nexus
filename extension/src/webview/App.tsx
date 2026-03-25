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

interface StructuredResult {
  intent: string;
  result: Record<string, unknown>;
  has_github_token?: boolean;
  file_written?: boolean;
  written_path?: string | null;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
  isStreaming?: boolean;
  structured?: StructuredResult;
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
  | { type: 'log'; level: LogEntry['level']; message: string }
  | {
      type: 'result';
      intent: string;
      result: Record<string, unknown>;
      has_github_token?: boolean;
      file_written?: boolean;
      written_path?: string | null;
    };

const vscode = acquireVsCodeApi();

// ── Intent selector ────────────────────────────────────────────────────────
type IntentOption = 'auto' | 'explain' | 'debug' | 'review' | 'test';

const INTENT_LABELS: Record<IntentOption, string> = {
  auto:    'Ask',
  explain: 'Explain',
  debug:   'Debug',
  review:  'Review',
  test:    'Test',
};

const INTENT_OPTIONS: IntentOption[] = ['auto', 'explain', 'debug', 'review', 'test'];

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

function DebugPanel({ result, onOpenFile }: {
  result: Record<string, unknown>;
  onOpenFile: (filePath: string, lineStart: number) => void;
}): React.JSX.Element {
  const suspects = (result.suspects as Array<{
    node_id: string; file_path: string; line_start: number;
    anomaly_score: number; reasoning: string;
  }>) ?? [];
  const impactRadius = (result.impact_radius as string[]) ?? [];
  const traversalPath = (result.traversal_path as string[]) ?? [];
  const diagnosis = (result.diagnosis as string) ?? '';
  const [impactExpanded, setImpactExpanded] = useState(false);

  const displayName = (nodeId: string): string =>
    nodeId.includes('::') ? nodeId.split('::').pop()! : nodeId;

  const scoreClass = (score: number): string =>
    score >= 0.7 ? 'score-high' : score >= 0.4 ? 'score-mid' : 'score-low';

  return (
    <div className="result-panel result-panel-debug">
      {diagnosis && <div className="result-diagnosis">{renderMarkdown(diagnosis)}</div>}

      <div className="suspects-list">
        {suspects.map((s, i) => (
          <button
            key={s.node_id}
            className="suspect-row"
            onClick={() => onOpenFile(s.file_path, s.line_start)}
            title={s.reasoning}
          >
            <span className="suspect-rank">#{i + 1}</span>
            <span className="suspect-location">
              {s.file_path.split('/').pop()}:{s.line_start}
            </span>
            <div className="score-bar-track">
              <div
                className={`score-bar-fill ${scoreClass(s.anomaly_score)}`}
                style={{ width: `${Math.round(s.anomaly_score * 100)}%` }}
              />
            </div>
            <span className="suspect-score">{s.anomaly_score.toFixed(2)}</span>
          </button>
        ))}
      </div>

      {traversalPath.length > 0 && (
        <div className="traversal-breadcrumb">
          {traversalPath.slice(0, 8).map((nid, i) => (
            <React.Fragment key={nid}>
              <span className="traversal-node">{displayName(nid)}</span>
              {i < Math.min(traversalPath.length, 8) - 1 && (
                <span className="traversal-sep"> → </span>
              )}
            </React.Fragment>
          ))}
          {traversalPath.length > 8 && (
            <span className="traversal-more">+{traversalPath.length - 8} more</span>
          )}
        </div>
      )}

      {impactRadius.length > 0 && (
        <>
          <button
            className="collapsible-header"
            onClick={() => setImpactExpanded(v => !v)}
          >
            <span className="section-chevron">{impactExpanded ? '▾' : '▸'}</span>
            Impact radius ({impactRadius.length})
          </button>
          {impactExpanded && (
            <ul className="impact-list">
              {impactRadius.map(nid => (
                <li key={nid}>{displayName(nid)}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function FindingCard({ finding, severityClass }: {
  finding: {
    severity: string; category: string; description: string;
    file_path: string; line_start: number; line_end: number; suggestion: string;
  };
  severityClass: string;
}): React.JSX.Element {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="finding-card">
      <div className="finding-header">
        <span className={`severity-badge ${severityClass}`}>{finding.severity}</span>
        <span className="finding-category">{finding.category}</span>
        <span className="finding-location">
          {finding.file_path.split('/').pop()}:{finding.line_start}
        </span>
      </div>
      <div className="finding-description">{renderMarkdown(finding.description)}</div>
      <button
        className="suggestion-toggle"
        onClick={() => setExpanded(v => !v)}
      >
        <span className="section-chevron">{expanded ? '▾' : '▸'}</span>
        Suggestion
      </button>
      {expanded && <div className="finding-suggestion">{renderMarkdown(finding.suggestion)}</div>}
    </div>
  );
}

function ReviewPanel({ result, hasGithubToken }: {
  result: Record<string, unknown>;
  hasGithubToken: boolean;
}): React.JSX.Element {
  const findings = (result.findings as Array<{
    severity: 'critical' | 'warning' | 'info';
    category: string;
    description: string;
    file_path: string;
    line_start: number;
    line_end: number;
    suggestion: string;
  }>) ?? [];
  const summary = (result.summary as string) ?? '';

  const [showPrForm, setShowPrForm] = useState(false);
  const [prRepo, setPrRepo] = useState('');
  const [prNumber, setPrNumber] = useState('');
  const [prSha, setPrSha] = useState('');

  const SEVERITY_CLASS: Record<string, string> = {
    critical: 'badge-critical',
    warning: 'badge-warning',
    info: 'badge-info',
  };

  const handleSubmitPr = (): void => {
    const parsed = parseInt(prNumber, 10);
    if (!prRepo.trim() || !prNumber.trim() || !prSha.trim() || isNaN(parsed)) {
      return;
    }
    vscode.postMessage({
      type: 'postReviewToPR',
      findings: findings as Array<Record<string, unknown>>,
      repo: prRepo,
      pr_number: parsed,
      commit_sha: prSha,
    });
    setShowPrForm(false);
  };

  return (
    <div className="result-panel result-panel-review">
      {summary && <div className="result-summary">{renderMarkdown(summary)}</div>}

      <div className="findings-list">
        {findings.map((f, i) => (
          <FindingCard key={i} finding={f} severityClass={SEVERITY_CLASS[f.severity] ?? 'badge-info'} />
        ))}
      </div>

      {hasGithubToken && !showPrForm && (
        <button
          className="post-github-btn"
          onClick={() => setShowPrForm(true)}
        >
          Post to GitHub PR
        </button>
      )}

      {hasGithubToken && showPrForm && (
        <div className="pr-form">
          <input
            className="pr-form-input"
            type="text"
            placeholder="owner/repo"
            value={prRepo}
            onChange={(e) => setPrRepo(e.target.value)}
          />
          <input
            className="pr-form-input"
            type="text"
            placeholder="PR number"
            value={prNumber}
            onChange={(e) => setPrNumber(e.target.value)}
          />
          <input
            className="pr-form-input"
            type="text"
            placeholder="Commit SHA"
            value={prSha}
            onChange={(e) => setPrSha(e.target.value)}
          />
          <div className="pr-form-actions">
            <button className="pr-form-submit" onClick={handleSubmitPr}>
              Submit
            </button>
            <button className="pr-form-cancel" onClick={() => setShowPrForm(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function TestPanel({ result, fileWritten, writtenPath }: {
  result: Record<string, unknown>;
  fileWritten?: boolean;
  writtenPath?: string | null;
}): React.JSX.Element {
  const testCode = (result.test_code as string) ?? '';
  const framework = (result.framework as string) ?? '';
  const testFilePath = (result.test_file_path as string) ?? '';

  const handleCopy = (): void => {
    // VS Code WebKit does not permit navigator.clipboard (blocked by CSP).
    // document.execCommand('copy') is the accepted workaround in WebKit/Electron
    // webviews. The textarea is appended off-screen, selected, copied, then removed
    // immediately — no content is persisted or exposed to the DOM.
    const textarea = document.createElement('textarea');
    textarea.value = testCode;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
  };

  return (
    <div className="result-panel result-panel-test">
      {framework && (
        <div className="test-framework-label">
          Framework: <span className="test-framework-name">{framework}</span>
        </div>
      )}

      <pre className="test-code-block">
        <code>{testCode}</code>
      </pre>

      <div className="test-action-row">
        {fileWritten ? (
          <span className="file-written-badge">
            File written to: {writtenPath ?? testFilePath}
          </span>
        ) : (
          <button className="copy-code-btn" onClick={handleCopy}>
            Copy to clipboard
          </button>
        )}
      </div>
    </div>
  );
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
  const [selectedIntent, setSelectedIntent] = useState<IntentOption>('auto');
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

        case 'result':
          if (msg.intent === 'explain') {
            const answer = (msg.result?.answer as string) ?? '';
            setMessages((prev) => [
              ...prev,
              { id: newId(), role: 'assistant', content: answer, isStreaming: false },
            ]);
          } else {
            setMessages((prev) => [
              ...prev,
              {
                id: newId(),
                role: 'assistant',
                content: '',
                isStreaming: false,
                structured: {
                  intent: msg.intent,
                  result: msg.result,
                  has_github_token: msg.has_github_token,
                  file_written: msg.file_written,
                  written_path: msg.written_path,
                },
              },
            ]);
          }
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
    vscode.postMessage({
      type: 'query',
      question,
      intent_hint: selectedIntent !== 'auto' ? selectedIntent : undefined,
    });
  }, [inputValue, isStreaming, addLog, selectedIntent]);

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
          <div className="chat-scroll-area">
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
                    {msg.structured ? (
                      <>
                        <span className={`intent-badge intent-badge-${msg.structured.intent}`}>
                          {msg.structured.intent}
                        </span>
                        {msg.structured.intent === 'debug' && (
                          <DebugPanel
                            result={msg.structured.result}
                            onOpenFile={(filePath, lineStart) =>
                              vscode.postMessage({ type: 'openFile', filePath, lineStart })
                            }
                          />
                        )}
                        {msg.structured.intent === 'review' && (
                          <ReviewPanel
                            result={msg.structured.result}
                            hasGithubToken={msg.structured.has_github_token === true}
                          />
                        )}
                        {msg.structured.intent === 'test' && (
                          <TestPanel
                            result={msg.structured.result}
                            fileWritten={msg.structured.file_written}
                            writtenPath={msg.structured.written_path}
                          />
                        )}
                      </>
                    ) : (
                      <div className={`message-bubble${isLastStreaming ? ' streaming-cursor' : ''}`}>
                        {renderMarkdown(msg.content)}
                      </div>
                    )}
                    {!msg.structured && msg.citations && msg.citations.length > 0 && (
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
          </div>{/* end chat-scroll-area */}

          <div className="intent-selector">
            {INTENT_OPTIONS.map((intent) => (
              <button
                key={intent}
                className={`intent-pill${selectedIntent === intent ? ' active' : ''}`}
                onClick={() => setSelectedIntent(intent)}
                disabled={isStreaming}
                title={INTENT_LABELS[intent]}
              >
                {INTENT_LABELS[intent]}
              </button>
            ))}
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
              {isStreaming ? '…' : INTENT_LABELS[selectedIntent]}
            </button>
          </div>
        </div>
      </div>

      {/* ③ ACTIVITY */}
      <div className="panel-section panel-section-activity">
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
