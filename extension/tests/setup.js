// Mock Chrome extension APIs
globalThis.chrome = {
  runtime: {
    sendMessage: vi.fn().mockResolvedValue({ ok: true, data: { mappings: [] } }),
    onMessage: {
      addListener: vi.fn(),
    },
  },
  storage: {
    local: {
      get: vi.fn().mockImplementation((query, callback) => {
        const result = { serverUrl: 'http://localhost:8001', dismissedHosts: [] };
        if (typeof callback === 'function') {
          callback(result);
          return undefined;
        }
        return Promise.resolve(result);
      }),
      set: vi.fn().mockImplementation((data, callback) => {
        if (typeof callback === 'function') {
          callback();
          return undefined;
        }
        return Promise.resolve(undefined);
      }),
    },
  },
};

// Mock CSS.escape (not available in jsdom)
if (!globalThis.CSS) {
  globalThis.CSS = {};
}
if (!CSS.escape) {
  CSS.escape = function (str) {
    return str.replace(/([^\w-])/g, '\\$1');
  };
}

// Enable test exports from content.js
window.__cpAutofillTest = true;
window.__cpAutofillLoaded = false;
