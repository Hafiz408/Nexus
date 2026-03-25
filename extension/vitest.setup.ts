// extension/vitest.setup.ts
import '@testing-library/jest-dom';
import { vi } from 'vitest';

const mockPostMessage = vi.fn();
const mockGetState = vi.fn(() => undefined);
const mockSetState = vi.fn();

(globalThis as Record<string, unknown>)['acquireVsCodeApi'] = () => ({
  postMessage: mockPostMessage,
  getState: mockGetState,
  setState: mockSetState,
});

// jsdom doesn't implement window.matchMedia — stub it
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Reset all mocks between tests
beforeEach(() => {
  vi.clearAllMocks();
});
