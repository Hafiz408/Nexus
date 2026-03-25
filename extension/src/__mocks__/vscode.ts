// extension/src/__mocks__/vscode.ts
import { vi } from 'vitest';

export const mockDecorationType = {
  dispose: vi.fn(),
  key: 'mock-decoration',
};

export const createTextEditorDecorationType = vi.fn(() => mockDecorationType);

export class Position {
  constructor(public line: number, public character: number) {}
}

export class Range {
  constructor(public start: Position, public end: Position) {}
}

export class Uri {
  static file = vi.fn((p: string) => ({ fsPath: p, toString: () => p }));
  fsPath = '';
}

export class ThemeColor {
  constructor(public id: string) {}
}

export class RelativePattern {
  constructor(public base: unknown, public pattern: string) {}
}

export const mockEditor = {
  document: { uri: { fsPath: '/mock/file.ts' } },
  setDecorations: vi.fn(),
};

export const mockWatcher = {
  onDidChange: vi.fn(),
  onDidCreate: vi.fn(),
  dispose: vi.fn(),
};

export const window = {
  createTextEditorDecorationType,
  showTextDocument: vi.fn(async () => mockEditor),
  visibleTextEditors: [mockEditor],
  showInformationMessage: vi.fn(),
  showErrorMessage: vi.fn(),
};

export const workspace = {
  openTextDocument: vi.fn(async () => ({ uri: { fsPath: '/mock/file.ts' } })),
  createFileSystemWatcher: vi.fn(() => mockWatcher),
  workspaceFolders: [{ uri: { fsPath: '/mock/workspace' }, name: 'mock', index: 0 }],
  getConfiguration: vi.fn(() => ({
    get: vi.fn((_key: string, def: unknown) => def),
  })),
};
