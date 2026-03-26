// Messages sent FROM extension host TO webview
export type HostToWebviewMessage =
  | { type: 'token'; content: string }
  | { type: 'citations'; citations: Citation[] }
  | { type: 'done'; retrieval_stats: Record<string, unknown> }
  | { type: 'error'; message: string }
  | { type: 'indexStatus'; status: IndexStatus }
  | { type: 'reindexState'; reindex_required: boolean; never_indexed: boolean }
  | { type: 'configStatus'; chat_provider: string; chat_model: string; embedding_provider: string; embedding_model: string }
  | {
      type: 'result';
      intent: string;
      result: Record<string, unknown>;
      has_github_token?: boolean;
      file_written?: boolean;
      written_path?: string | null;
    };

// Messages sent FROM webview TO extension host
export type WebviewToHostMessage =
  | {
      type: 'query';
      question: string;
      intent_hint?: string;
      target_node_id?: string;
      selected_file?: string;
      selected_range?: [number, number];
      repo_root?: string;
    }
  | { type: 'openFile'; filePath: string; lineStart: number }
  | { type: 'indexWorkspace' }
  | { type: 'clearIndex' }
  | { type: 'configureKeys' }
  | {
      type: 'postReviewToPR';
      findings: Array<Record<string, unknown>>;
      repo: string;
      pr_number: number;
      commit_sha: string;
    };

export interface Citation {
  node_id: string;
  file_path: string;
  line_start: number;
  line_end: number;
  name: string;
  type: string;
}

export interface IndexStatus {
  status: 'pending' | 'running' | 'complete' | 'failed' | 'not_indexed';
  nodes_indexed?: number;
  edges_indexed?: number;
  files_processed?: number;
  error?: string | null;
}
