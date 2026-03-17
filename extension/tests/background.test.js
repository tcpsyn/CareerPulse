import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'fs';
import { join } from 'path';

function loadBackground() {
  // Mock all chrome APIs used at top level in background.js
  globalThis.chrome = {
    storage: {
      local: {
        get: vi.fn().mockResolvedValue({ serverUrl: 'http://localhost:8085' }),
      },
    },
    tabs: {
      onRemoved: { addListener: vi.fn() },
      onUpdated: { addListener: vi.fn(), removeListener: vi.fn() },
      query: vi.fn().mockResolvedValue([]),
      create: vi.fn().mockResolvedValue({ id: 1 }),
      sendMessage: vi.fn(),
    },
    commands: {
      onCommand: { addListener: vi.fn() },
    },
    runtime: {
      onMessage: { addListener: vi.fn() },
    },
    downloads: {
      download: vi.fn().mockResolvedValue(undefined),
    },
  };

  globalThis.URL.createObjectURL = vi.fn(() => 'blob:mock');
  globalThis.URL.revokeObjectURL = vi.fn();

  const code = readFileSync(join(__dirname, '..', 'background.js'), 'utf-8');
  // Indirect eval to execute in global scope so function declarations are accessible
  (0, eval)(code);
}

describe('apiFetch timeout', () => {
  let originalFetch;

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    originalFetch = globalThis.fetch;
    loadBackground();
  });

  afterEach(() => {
    vi.useRealTimers();
    globalThis.fetch = originalFetch;
  });

  it('aborts fetch after 50 seconds if backend hangs', async () => {
    // Make fetch hang until abort signal fires
    globalThis.fetch = vi.fn((url, opts) => {
      return new Promise((resolve, reject) => {
        if (opts?.signal) {
          opts.signal.addEventListener('abort', () => {
            reject(new DOMException('The operation was aborted.', 'AbortError'));
          });
        }
      });
    });

    const fetchPromise = globalThis.apiFetch('/api/health').catch(e => e);

    // Advance past the 50s timeout
    await vi.advanceTimersByTimeAsync(51000);

    const error = await fetchPromise;
    expect(error).toBeTruthy();
    expect(error.message).toMatch(/aborted/i);
  });

  it('passes AbortSignal to fetch', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true });

    await globalThis.apiFetch('/api/test');

    const callArgs = globalThis.fetch.mock.calls[0];
    expect(callArgs[1]).toHaveProperty('signal');
    expect(callArgs[1].signal).toBeInstanceOf(AbortSignal);
  });
});
