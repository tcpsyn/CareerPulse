import { chromium } from 'playwright';
import path from 'path';
import { fileURLToPath } from 'url';
import { mkdir } from 'fs/promises';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const extensionPath = path.resolve(__dirname, 'extension');
const userDataDir = path.resolve(__dirname, '.playwright-profile');
const screenshotDir = path.resolve(__dirname, 'screenshots', 'workday-test');
const CDP_PORT = 9222;

await mkdir(screenshotDir, { recursive: true });

// ─── Connect or launch ──────────────────────────────────────────

let context;
let reconnected = false;

try {
  // Try connecting to an already-running browser with CDP
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${CDP_PORT}`);
  context = browser.contexts()[0];
  if (!context) throw new Error('No browser context found on CDP');
  reconnected = true;
  console.log('Reconnected to existing browser via CDP');
} catch {
  // Launch fresh with persistent profile + extension
  console.log('No running browser found, launching fresh...');
  context = await chromium.launchPersistentContext(userDataDir, {
    headless: false,
    args: [
      `--disable-extensions-except=${extensionPath}`,
      `--load-extension=${extensionPath}`,
      `--remote-debugging-port=${CDP_PORT}`,
      '--start-maximized',
    ],
    viewport: null,
  });
  console.log(`Launched browser with CDP on port ${CDP_PORT}`);
  console.log(`User data dir: ${userDataDir}`);
}

// ─── Helpers ────────────────────────────────────────────────────

function getPage() {
  // Return the first non-extension page, or any page
  const pages = context.pages();
  return pages.find(p => !p.url().startsWith('chrome-extension://')) || pages[0];
}

function delay(ms) {
  return new Promise(r => setTimeout(r, ms));
}

function timestamp() {
  return new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
}

// ─── Screenshot ─────────────────────────────────────────────────

async function screenshot(label = 'form') {
  const page = getPage();
  const filename = `${timestamp()}_${label}.png`;
  const filepath = path.join(screenshotDir, filename);
  await page.screenshot({ path: filepath, fullPage: false });
  console.log(`Screenshot: ${filepath}`);
  return filepath;
}

async function screenshotFullPage(label = 'form-full') {
  const page = getPage();
  const filename = `${timestamp()}_${label}.png`;
  const filepath = path.join(screenshotDir, filename);
  await page.screenshot({ path: filepath, fullPage: true });
  console.log(`Full-page screenshot: ${filepath}`);
  return filepath;
}

async function screenshotElement(selector, label = 'element') {
  const page = getPage();
  const el = await page.$(selector);
  if (!el) {
    console.log(`Element not found: ${selector}`);
    return null;
  }
  const filename = `${timestamp()}_${label}.png`;
  const filepath = path.join(screenshotDir, filename);
  await el.screenshot({ path: filepath });
  console.log(`Element screenshot: ${filepath}`);
  return filepath;
}

// ─── Extension autofill trigger ─────────────────────────────────

async function triggerAutofill(jobId = null) {
  const page = getPage();
  console.log(`Triggering autofill on: ${page.url()}`);

  // Send the startFill message to content script via page evaluate
  const result = await page.evaluate(async (jid) => {
    return new Promise((resolve) => {
      // The content script listens for chrome.runtime messages,
      // but we can also call the exposed function directly
      if (window.__cpAutofillLoaded && window.__cpAutofill?.startFillFlow) {
        window.__cpAutofill.startFillFlow()
          .then(() => resolve({ ok: true, method: 'direct' }))
          .catch(e => resolve({ ok: false, error: e.message, method: 'direct' }));
        return;
      }
      // Fallback: dispatch via chrome.runtime.sendMessage from content script context
      // We can trigger it by sending a message to the content script
      chrome.runtime.sendMessage(
        { type: 'startFill', jobId: jid },
        (resp) => resolve(resp || { ok: false, error: 'no response' })
      );
    });
  }, jobId);

  console.log('Autofill result:', JSON.stringify(result));
  return result;
}

// Alternative: use the keyboard shortcut to trigger autofill
async function triggerAutofillViaShortcut() {
  const page = getPage();
  console.log('Triggering autofill via Cmd+Shift+F shortcut...');
  await page.keyboard.press('Meta+Shift+F');
  await delay(1000);
  return { ok: true, method: 'shortcut' };
}

// Trigger autofill by injecting a message dispatch into the page
async function triggerAutofillViaMessage() {
  const page = getPage();
  console.log('Triggering autofill via chrome.runtime message...');

  // Use chrome.scripting API workaround: inject into page to message content script
  const result = await page.evaluate(async () => {
    return new Promise((resolve) => {
      // Content script exposes the handler via chrome.runtime.onMessage
      // We can trigger it by dispatching a custom event or calling exposed globals
      const event = new CustomEvent('cp-autofill-trigger', { detail: { type: 'startFill' } });
      document.dispatchEvent(event);

      // Also try the direct approach if __cpAutofill is exposed
      if (window.__cpAutofill?.startFillFlow) {
        window.__cpAutofill.startFillFlow()
          .then(() => resolve({ ok: true, method: 'exposed-global' }))
          .catch(e => resolve({ ok: false, error: e.message }));
      } else {
        // Wait a moment then check state
        setTimeout(() => resolve({ ok: true, method: 'event-dispatch' }), 500);
      }
    });
  });

  console.log('Autofill result:', JSON.stringify(result));
  return result;
}

// ─── Wait for autofill completion ───────────────────────────────

async function waitForAutofillDone(timeoutMs = 120000) {
  const page = getPage();
  const start = Date.now();
  console.log('Waiting for autofill to complete...');

  while (Date.now() - start < timeoutMs) {
    const state = await page.evaluate(() => {
      // Check for the overlay status element
      const overlay = document.querySelector('[class*="cp-autofill"], [class*="cp-overlay"]');
      const overlayText = overlay?.textContent || '';

      // Check for done/error indicators
      const isDone = overlayText.includes('Done') || overlayText.includes('Filled');
      const isError = overlayText.includes('Error') || overlayText.includes('Failed');
      const isAnalyzing = overlayText.includes('Analyzing') || overlayText.includes('Scanning');
      const isFilling = overlayText.includes('Filling') || overlayText.includes('field');

      return {
        overlayText: overlayText.slice(0, 200),
        isDone,
        isError,
        isAnalyzing,
        isFilling,
        hasOverlay: !!overlay,
      };
    });

    if (state.isDone || state.isError) {
      console.log(`Autofill finished: ${state.overlayText}`);
      return state;
    }

    if (state.isAnalyzing || state.isFilling) {
      process.stdout.write(`\r  Status: ${state.overlayText.slice(0, 80)}...`);
    }

    await delay(1000);
  }

  console.log('\nAutofill timed out');
  return { timedOut: true };
}

// ─── Form state capture ─────────────────────────────────────────

async function captureFormState() {
  const page = getPage();
  return page.evaluate(() => {
    const fields = [];
    // Collect all input/select/textarea values
    for (const el of document.querySelectorAll('input, select, textarea')) {
      const label = el.getAttribute('aria-label')
        || el.closest('label')?.textContent?.trim()
        || el.getAttribute('data-automation-id')
        || el.name
        || el.id
        || '';
      fields.push({
        tag: el.tagName.toLowerCase(),
        type: el.type || '',
        label: label.slice(0, 80),
        value: el.value?.slice(0, 200) || '',
        selector: el.getAttribute('data-automation-id')
          ? `[data-automation-id="${el.getAttribute('data-automation-id')}"]`
          : (el.id ? `#${el.id}` : ''),
      });
    }
    return fields.filter(f => f.label || f.value);
  });
}

// ─── Capture autofill overlay/results ───────────────────────────

async function captureOverlayState() {
  const page = getPage();
  return page.evaluate(() => {
    const overlay = document.querySelector('[class*="cp-overlay"], [class*="cp-autofill"]');
    if (!overlay) return { visible: false };

    const rows = [];
    for (const row of overlay.querySelectorAll('[class*="row"], [class*="field"], tr, li')) {
      rows.push(row.textContent?.trim().slice(0, 200));
    }

    return {
      visible: true,
      text: overlay.textContent?.trim().slice(0, 2000),
      rows,
      classList: [...overlay.classList],
    };
  });
}

// ─── Console log capture ────────────────────────────────────────

const consoleLogs = [];

function startConsoleCapture() {
  const page = getPage();
  page.on('console', msg => {
    const text = msg.text();
    if (text.includes('cp-autofill') || text.includes('CareerPulse') || text.includes('[CP]')) {
      consoleLogs.push({ type: msg.type(), text, time: new Date().toISOString() });
    }
  });
  console.log('Console capture started (filtering for CP messages)');
}

function getConsoleLogs() {
  return [...consoleLogs];
}

// ─── Full test flow ─────────────────────────────────────────────

async function runFullTest(options = {}) {
  const { jobId = null, useShortcut = false } = options;

  console.log('\n═══ Starting full autofill test ═══');
  console.log(`Page: ${getPage().url()}`);

  // 1. Screenshot before
  console.log('\n1. Capturing pre-fill state...');
  const preScreenshot = await screenshot('01-pre-fill');
  const preFields = await captureFormState();
  console.log(`   Found ${preFields.length} form fields`);

  // 2. Start console capture
  startConsoleCapture();

  // 3. Trigger autofill
  console.log('\n2. Triggering autofill...');
  let triggerResult;
  if (useShortcut) {
    triggerResult = await triggerAutofillViaShortcut();
  } else {
    triggerResult = await triggerAutofill(jobId);
  }
  await delay(2000);
  await screenshot('02-autofill-started');

  // 4. Wait for completion
  console.log('\n3. Waiting for completion...');
  const doneState = await waitForAutofillDone();
  await delay(1000);

  // 5. Screenshot after
  console.log('\n4. Capturing post-fill state...');
  const postScreenshot = await screenshot('03-post-fill');
  const postFields = await captureFormState();
  const overlayState = await captureOverlayState();

  // 6. Diff
  console.log('\n5. Field changes:');
  const changes = [];
  for (const post of postFields) {
    const pre = preFields.find(f => f.selector === post.selector && f.label === post.label);
    if (pre && pre.value !== post.value) {
      changes.push({ label: post.label, before: pre.value, after: post.value });
      console.log(`   ${post.label}: "${pre.value}" → "${post.value}"`);
    } else if (!pre && post.value) {
      changes.push({ label: post.label, before: '', after: post.value });
      console.log(`   ${post.label}: (new) "${post.value}"`);
    }
  }

  if (changes.length === 0) {
    console.log('   No field changes detected');
  }

  // 7. Summary
  const logs = getConsoleLogs();
  console.log(`\n═══ Test complete ═══`);
  console.log(`Fields changed: ${changes.length}/${postFields.length}`);
  console.log(`Console logs captured: ${logs.length}`);
  console.log(`Screenshots: ${screenshotDir}`);

  return {
    preScreenshot,
    postScreenshot,
    preFields,
    postFields,
    changes,
    overlayState,
    triggerResult,
    doneState,
    consoleLogs: logs,
  };
}

// ─── Export API ──────────────────────────────────────────────────

const api = {
  context,
  getPage,
  screenshot,
  screenshotFullPage,
  screenshotElement,
  triggerAutofill,
  triggerAutofillViaShortcut,
  triggerAutofillViaMessage,
  waitForAutofillDone,
  captureFormState,
  captureOverlayState,
  startConsoleCapture,
  getConsoleLogs,
  runFullTest,
  delay,
};

// Make available as global for REPL usage
globalThis.cp = api;

// ─── CLI mode ───────────────────────────────────────────────────

const cmd = process.argv[2];

if (cmd === 'screenshot') {
  const label = process.argv[3] || 'manual';
  await screenshot(label);
} else if (cmd === 'full-screenshot') {
  const label = process.argv[3] || 'manual-full';
  await screenshotFullPage(label);
} else if (cmd === 'fill') {
  const jobId = process.argv[3] || null;
  await triggerAutofill(jobId);
  await waitForAutofillDone();
  await screenshot('post-fill');
} else if (cmd === 'shortcut') {
  await triggerAutofillViaShortcut();
  await waitForAutofillDone();
  await screenshot('post-shortcut');
} else if (cmd === 'test') {
  const result = await runFullTest({ useShortcut: process.argv[3] === '--shortcut' });
  console.log('\nResult JSON:');
  console.log(JSON.stringify(result, null, 2));
} else if (cmd === 'fields') {
  const fields = await captureFormState();
  console.log(JSON.stringify(fields, null, 2));
} else if (cmd === 'overlay') {
  const state = await captureOverlayState();
  console.log(JSON.stringify(state, null, 2));
} else if (cmd === 'watch') {
  // Keep alive + periodic screenshots
  const intervalSec = parseInt(process.argv[3]) || 10;
  console.log(`Watching form state every ${intervalSec}s. Ctrl+C to stop.`);
  let i = 0;
  while (true) {
    await delay(intervalSec * 1000);
    i++;
    await screenshot(`watch-${String(i).padStart(3, '0')}`);
    const fields = await captureFormState();
    const filled = fields.filter(f => f.value).length;
    console.log(`  ${filled}/${fields.length} fields have values`);
  }
} else {
  // Interactive: print usage and keep alive
  console.log(`
╔══════════════════════════════════════════════════╗
║  CareerPulse Workday Autofill Test Harness       ║
╠══════════════════════════════════════════════════╣
║  CLI commands:                                   ║
║    node workday-test.mjs screenshot [label]      ║
║    node workday-test.mjs full-screenshot [label] ║
║    node workday-test.mjs fill [jobId]            ║
║    node workday-test.mjs shortcut                ║
║    node workday-test.mjs test [--shortcut]       ║
║    node workday-test.mjs fields                  ║
║    node workday-test.mjs overlay                 ║
║    node workday-test.mjs watch [intervalSec]     ║
╠══════════════════════════════════════════════════╣
║  Running with no command = keep browser alive    ║
║  ${reconnected ? 'RECONNECTED to existing browser' : `LAUNCHED new browser (CDP port ${CDP_PORT})`}           ║
║  Extension loaded from: ./extension/             ║
║  Screenshots saved to: screenshots/workday-test/ ║
╚══════════════════════════════════════════════════╝
`);

  if (!reconnected) {
    console.log('Navigate to a Workday application form, then run:');
    console.log('  node workday-test.mjs test');
  }

  // Keep alive until killed
  await new Promise(() => {});
}
