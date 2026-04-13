import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { loadScripts } from './setup.js';

beforeAll(() => {
    document.body.innerHTML = `
        <div id="toast-container"></div>
        <div class="nav-links">
            <a class="nav-link" data-route="feed">Jobs</a>
            <a class="nav-link" data-route="stats">Dashboard</a>
            <a class="nav-link" data-route="pipeline">Pipeline</a>
            <a class="nav-link" data-route="calendar">Calendar</a>
            <a class="nav-link" data-route="queue">Queue</a>
            <a class="nav-link" data-route="network">Network</a>
            <a class="nav-link" data-route="calculator">Calculator</a>
            <a class="nav-link" data-route="settings">Settings</a>
        </div>
        <div id="app"></div>
        <div id="nav-wrapper">
            <button id="scrape-btn">Scrape Now</button>
        </div>
    `;

    loadScripts('utils.js', 'api.js');

    globalThis.renderFeed = async () => {};
    globalThis.renderJobDetail = async () => {};
    globalThis.renderStats = async () => {};
    globalThis.renderPipeline = async () => {};
    globalThis.renderQueue = async () => {};
    globalThis.renderNetwork = async () => {};
    globalThis.renderSettings = async () => {};
    globalThis.renderCalendar = async () => {};
    globalThis.renderSalaryCalculator = async () => {};
    globalThis.enterTriageMode = () => {};
    globalThis.exitTriageMode = () => {};
    globalThis.triageActive = false;
    globalThis.triageJobs = [];
    globalThis.triageIndex = 0;
    globalThis.triageUndoStack = [];

    loadScripts('app.js');
});

beforeEach(() => {
    window.location.hash = '#/';
    stopScrapePoll();
    currentScrapeTaskId = null;
    stallToastShownForTaskId = null;
    lastScrapeState = null;

    document.getElementById('toast-container').innerHTML = '';
    document.getElementById('app-modal')?.remove();
    document.querySelectorAll('.scrape-cancel-link').forEach(el => el.remove());

    const btn = document.getElementById('scrape-btn');
    btn.disabled = false;
    btn.textContent = 'Scrape Now';
    btn.className = '';
});

afterEach(() => {
    stopScrapePoll();
    delete globalThis.fetch;
    vi.restoreAllMocks();
});

describe('phaseLabel', () => {
    it('renders scraper name and progress for scraping phase', () => {
        expect(phaseLabel({ phase: 'scraping', current: 'wellfound', completed: 7, total: 14 }))
            .toBe('Scraping: wellfound (7/14)');
    });

    it('falls back to progress-only when no current scraper', () => {
        expect(phaseLabel({ phase: 'scraping', completed: 0, total: 12 }))
            .toBe('Scraping 0/12');
    });

    it('renders enrichment phase label', () => {
        expect(phaseLabel({ phase: 'enriching' })).toBe('Enriching job details\u2026');
    });

    it('renders classification phase label', () => {
        expect(phaseLabel({ phase: 'classifying' })).toBe('Classifying locations\u2026');
    });

    it('renders scoring progress', () => {
        expect(phaseLabel({ phase: 'scoring', scoring: { scored: 42, total: 120 } }))
            .toBe('Scoring: 42/120');
    });

    it('handles missing scoring object on scoring phase', () => {
        expect(phaseLabel({ phase: 'scoring' })).toBe('Scoring: 0/0');
    });

    it('renders done and error phases', () => {
        expect(phaseLabel({ phase: 'done' })).toBe('Done');
        expect(phaseLabel({ phase: 'error' })).toBe('Error');
    });
});

describe('computeStallSec', () => {
    it('returns 0 when server_now or last_updated_at are missing', () => {
        expect(computeStallSec({})).toBe(0);
        expect(computeStallSec({ server_now: 10 })).toBe(0);
        expect(computeStallSec({ last_updated_at: 10 })).toBe(0);
        expect(computeStallSec(null)).toBe(0);
    });

    it('computes server_now - last_updated_at', () => {
        expect(computeStallSec({ server_now: 100, last_updated_at: 75 })).toBe(25);
    });

    it('clamps negative values to 0', () => {
        expect(computeStallSec({ server_now: 50, last_updated_at: 60 })).toBe(0);
    });

    it('uses server monotonic clock only, ignoring client Date.now', () => {
        const realNow = Date.now();
        // Even if client clock is wildly ahead, stall math must be purely server-based
        expect(computeStallSec({ server_now: 1000, last_updated_at: 990 })).toBe(10);
        expect(Date.now()).toBeGreaterThanOrEqual(realNow);
    });
});

describe('renderScrapeButtonState', () => {
    it('shows phase label without warn/critical class when fresh', () => {
        renderScrapeButtonState({
            active: true, phase: 'scraping', current: 'wellfound',
            completed: 3, total: 10,
            server_now: 100, last_updated_at: 95,
            task_id: 't1',
        });
        const btn = document.getElementById('scrape-btn');
        expect(btn.disabled).toBe(true);
        expect(btn.innerHTML).toContain('Scraping: wellfound (3/10)');
        expect(btn.classList.contains('scrape-btn-warn')).toBe(false);
        expect(btn.classList.contains('scrape-btn-critical')).toBe(false);
        expect(document.querySelector('.scrape-cancel-link')).toBeNull();
    });

    it('adds warn class and cancel link above 30s stall', () => {
        renderScrapeButtonState({
            active: true, phase: 'scraping', current: 'wellfound',
            completed: 3, total: 10,
            server_now: 100, last_updated_at: 60,
            task_id: 't2',
        });
        const btn = document.getElementById('scrape-btn');
        expect(btn.classList.contains('scrape-btn-warn')).toBe(true);
        expect(btn.classList.contains('scrape-btn-critical')).toBe(false);
        expect(btn.innerHTML).toContain('Stalled');
        expect(document.querySelector('.scrape-cancel-link')).not.toBeNull();
    });

    it('adds critical class above 120s stall', () => {
        renderScrapeButtonState({
            active: true, phase: 'scraping', current: 'dice',
            completed: 5, total: 10,
            server_now: 200, last_updated_at: 60,
            task_id: 't3',
        });
        const btn = document.getElementById('scrape-btn');
        expect(btn.classList.contains('scrape-btn-critical')).toBe(true);
        expect(document.querySelector('.scrape-cancel-link')).not.toBeNull();
    });
});

describe('handleScrape', () => {
    it('handles 202 started response and starts polling with task_id', async () => {
        let progressCalls = 0;
        globalThis.fetch = vi.fn(async (url, opts) => {
            if (url === '/api/scrape' && opts?.method === 'POST') {
                return {
                    ok: true, status: 202,
                    json: async () => ({ task_id: 'abc', status: 'started' }),
                };
            }
            if (url === '/api/scrape/progress') {
                progressCalls += 1;
                return {
                    ok: true, status: 200,
                    json: async () => ({
                        active: true, phase: 'scraping', task_id: 'abc',
                        completed: 0, total: 5, current: null,
                        server_now: 100, last_updated_at: 100,
                        sources: [], scoring: { scored: 0, total: 0, skipped_reason: null },
                        errors: [],
                    }),
                };
            }
            return { ok: false, status: 404, json: async () => ({}) };
        });

        await handleScrape();
        expect(currentScrapeTaskId).toBe('abc');
        expect(scrapePollInterval).not.toBeNull();
        expect(document.getElementById('toast-container').children.length).toBe(0);

        stopScrapePoll();
    });

    it('handles 409 already_running silently and polls with returned task_id', async () => {
        globalThis.fetch = vi.fn(async (url, opts) => {
            if (url === '/api/scrape' && opts?.method === 'POST') {
                return {
                    ok: false, status: 409,
                    json: async () => ({ error: 'scrape_already_running', task_id: 'xyz' }),
                };
            }
            if (url === '/api/scrape/progress') {
                return {
                    ok: true, status: 200,
                    json: async () => ({
                        active: true, phase: 'scraping', task_id: 'xyz',
                        completed: 1, total: 5, current: 'dice',
                        server_now: 100, last_updated_at: 100,
                        sources: [], scoring: {}, errors: [],
                    }),
                };
            }
            return { ok: false, status: 404, json: async () => ({}) };
        });

        await handleScrape();
        expect(currentScrapeTaskId).toBe('xyz');
        // Silent: no error toast surfaced
        const errorToasts = document.querySelectorAll('.toast-error');
        expect(errorToasts.length).toBe(0);
        stopScrapePoll();
    });

    it('shows error toast and resets button when trigger throws', async () => {
        globalThis.fetch = vi.fn(async (url, opts) => {
            if (url === '/api/scrape' && opts?.method === 'POST') {
                return {
                    ok: false, status: 500,
                    json: async () => ({ detail: 'Internal error' }),
                };
            }
            return { ok: false, status: 404, json: async () => ({}) };
        });

        await handleScrape();
        expect(currentScrapeTaskId).toBeNull();
        expect(scrapePollInterval).toBeNull();
        const errorToasts = document.querySelectorAll('.toast-error');
        expect(errorToasts.length).toBe(1);
        const btn = document.getElementById('scrape-btn');
        expect(btn.disabled).toBe(false);
        expect(btn.textContent).toBe('Scrape Now');
    });
});

describe('initScrapeResume', () => {
    it('binds polling when an active scrape is already in progress', async () => {
        globalThis.fetch = vi.fn(async (url) => {
            if (url === '/api/scrape/progress') {
                return {
                    ok: true, status: 200,
                    json: async () => ({
                        active: true, phase: 'scoring', task_id: 'resume-1',
                        completed: 5, total: 5,
                        server_now: 100, last_updated_at: 100,
                        sources: [], scoring: { scored: 3, total: 10 },
                        errors: [],
                    }),
                };
            }
            return { ok: false, status: 404, json: async () => ({}) };
        });

        await initScrapeResume();
        expect(currentScrapeTaskId).toBe('resume-1');
        expect(scrapePollInterval).not.toBeNull();
        stopScrapePoll();
    });

    it('is a no-op when no active scrape', async () => {
        globalThis.fetch = vi.fn(async () => ({
            ok: true, status: 200,
            json: async () => ({ active: false, phase: 'done' }),
        }));

        await initScrapeResume();
        expect(currentScrapeTaskId).toBeNull();
        expect(scrapePollInterval).toBeNull();
    });

    it('swallows network errors quietly', async () => {
        globalThis.fetch = vi.fn(async () => { throw new Error('network down'); });
        await initScrapeResume();
        expect(currentScrapeTaskId).toBeNull();
    });
});

describe('showScrapeSummaryToast', () => {
    it('renders summary with source counts and a View details action', () => {
        showScrapeSummaryToast({
            phase: 'done', new_jobs: 4, total: 3,
            sources: [
                { name: 'a', status: 'ok' },
                { name: 'b', status: 'ok' },
                { name: 'c', status: 'timeout' },
            ],
        });
        const toast = document.querySelector('.toast');
        expect(toast).not.toBeNull();
        expect(toast.textContent).toContain('Scrape complete');
        expect(toast.textContent).toContain('4 new jobs');
        expect(toast.textContent).toContain('2/3 sources ok');
        expect(toast.textContent).toContain('1 timeout');
        const action = toast.querySelector('.toast-action-btn');
        expect(action).not.toBeNull();
        expect(action.textContent).toBe('View details');
    });

    it('clicking View details opens the scrape modal', () => {
        showScrapeSummaryToast({
            phase: 'done', new_jobs: 2, total: 1,
            sources: [{ name: 'a', status: 'ok' }],
        });
        document.querySelector('.toast-action-btn').click();
        expect(document.getElementById('app-modal')).not.toBeNull();
    });
});

describe('showScrapeErrorToast', () => {
    it('renders an error toast with first error message', () => {
        showScrapeErrorToast({
            phase: 'error',
            errors: ['Cancelled by user'],
            sources: [],
        });
        const toast = document.querySelector('.toast-error');
        expect(toast).not.toBeNull();
        expect(toast.textContent).toContain('Scrape failed');
        expect(toast.textContent).toContain('Cancelled by user');
    });
});

describe('showScrapeDetailsModal', () => {
    it('renders a row per source with status, duration and error', () => {
        showScrapeDetailsModal({
            phase: 'done', new_jobs: 2,
            sources: [
                { name: 'dice', status: 'ok', duration_ms: 1234, listings_found: 50, new_jobs: 2, error: null },
                { name: 'wellfound', status: 'timeout', duration_ms: 120000, listings_found: 0, new_jobs: 0, error: 'exceeded 120s' },
            ],
            errors: [],
            scoring: { scored: 2, total: 2, skipped_reason: null },
        });
        const modal = document.getElementById('app-modal');
        expect(modal).not.toBeNull();
        const rows = modal.querySelectorAll('tbody tr');
        expect(rows.length).toBe(2);
        expect(rows[0].textContent).toContain('dice');
        expect(rows[0].textContent).toContain('1.2s');
        expect(rows[1].textContent).toContain('wellfound');
        expect(rows[1].textContent).toContain('exceeded 120s');
        expect(modal.textContent).toContain('Scrape Details');
    });

    it('shows pipeline errors block when errors are present', () => {
        showScrapeDetailsModal({
            phase: 'error', new_jobs: 0,
            sources: [],
            errors: ['scraping phase timed out'],
            scoring: {},
        });
        const modal = document.getElementById('app-modal');
        expect(modal.querySelector('.scrape-modal-errors')).not.toBeNull();
        expect(modal.textContent).toContain('scraping phase timed out');
    });

    it('close button removes the modal', () => {
        showScrapeDetailsModal({ phase: 'done', new_jobs: 0, sources: [], errors: [], scoring: {} });
        document.getElementById('scrape-modal-close').click();
        expect(document.getElementById('app-modal')).toBeNull();
    });
});

describe('stall toast dedupe', () => {
    it('shows the stall toast at most once per task_id', async () => {
        const state = {
            active: true, phase: 'scraping', task_id: 'stuck-1',
            completed: 1, total: 5, current: 'dice',
            server_now: 200, last_updated_at: 60,
            sources: [], scoring: {}, errors: [],
        };
        globalThis.fetch = vi.fn(async () => ({
            ok: true, status: 200, json: async () => state,
        }));

        await pollScrapeOnce();
        await pollScrapeOnce();
        await pollScrapeOnce();

        const toasts = document.querySelectorAll('.toast');
        expect(toasts.length).toBe(1);
        expect(toasts[0].textContent).toContain('Scrape appears stuck');
    });
});
