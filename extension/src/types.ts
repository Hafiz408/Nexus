// Messages sent FROM extension host TO webview
export type HostToWebviewMessage =
  | { type: 'token'; content: string }
  | { type: 'citations'; citations: Citation[] }
  | { type: 'done'; retrieval_stats: Record<string, unknown> }
  | { type: 'error'; message: string }
  | { type: 'indexStatus'; status: IndexStatus };

// Messages sent FROM webview TO extension host
export type WebviewToHostMessage =
  | { type: 'query'; question: string }
  | { type: 'openFile'; filePath: string; lineStart: number }
  | { type: 'indexWorkspace' }
  | { type: 'clearIndex' };

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
