// === State ===
let currentJobs = [];
let currentOffset = 0;
const PAGE_SIZE = 50;
let selectedJobIds = new Set();
let selectMode = false;

// === View Cleanup Registry ===
const _viewCleanups = [];

function registerViewCleanup(fn) {
    _viewCleanups.push(fn);
}

function cleanupCurrentView() {
    while (_viewCleanups.length) _viewCleanups.pop()();
    if (typeof queueEventSource !== 'undefined' && queueEventSource) {
        queueEventSource.close();
        queueEventSource = null;
    }
}

// === Router ===
function getRoute() {
    const hash = window.location.hash || '#/';
    if (hash.startsWith('#/job/')) {
        const id = hash.slice(6);
        return { view: 'detail', id: parseInt(id, 10) };
    }
    if (hash === '#/stats') return { view: 'stats' };
    if (hash === '#/calendar') return { view: 'calendar' };
    if (hash === '#/pipeline') return { view: 'pipeline' };
    if (hash === '#/queue') return { view: 'queue' };
    if (hash === '#/network') return { view: 'network' };
    if (hash === '#/settings') return { view: 'settings' };
    if (hash === '#/calculator') return { view: 'calculator' };
    return { view: 'feed' };
}

function navigate(hash) {
    window.location.hash = hash;
}

function updateActiveNav() {
    const route = getRoute();
    document.querySelectorAll('.nav-link').forEach(link => {
        const r = link.dataset.route;
        link.classList.toggle('active',
            (r === 'feed' && route.view === 'feed') ||
            (r === 'stats' && route.view === 'stats') ||
            (r === 'calendar' && route.view === 'calendar') ||
            (r === 'pipeline' && route.view === 'pipeline') ||
            (r === 'queue' && route.view === 'queue') ||
            (r === 'network' && route.view === 'network') ||
            (r === 'calculator' && route.view === 'calculator') ||
            (r === 'settings' && route.view === 'settings')
        );
    });
}

async function handleRoute() {
    cleanupCurrentView();
    const route = getRoute();
    updateActiveNav();
    const app = document.getElementById('app');

    if (route.view === 'detail') {
        await renderJobDetail(app, route.id);
    } else if (route.view === 'stats') {
        await renderStats(app);
    } else if (route.view === 'calendar') {
        await renderCalendar(app);
    } else if (route.view === 'pipeline') {
        await renderPipeline(app);
    } else if (route.view === 'queue') {
        await renderQueue(app);
    } else if (route.view === 'network') {
        await renderNetwork(app);
    } else if (route.view === 'settings') {
        await renderSettings(app);
    } else if (route.view === 'calculator') {
        await renderSalaryCalculator(app);
    } else {
        await renderFeed(app);
    }

    app.setAttribute('tabindex', '-1');
    app.focus({ preventScroll: true });
}

// === Filter Persistence & Smart Views ===
const FILTER_IDS = ['filter-search', 'filter-exclude', 'filter-score', 'filter-sort', 'filter-work-type', 'filter-employment', 'filter-location', 'filter-region', 'filter-posted-within', 'filter-clearance'];
const FILTER_STORAGE_KEY = 'careerpulse_filters';
const SMART_VIEWS_KEY = 'careerpulse_saved_views';

function getFilterState() {
    const state = {};
    FILTER_IDS.forEach(id => {
        const el = document.getElementById(id);
        if (el) state[id] = el.value;
    });
    const showStale = document.getElementById('filter-show-stale');
    if (showStale) state['filter-show-stale'] = showStale.checked;
    return state;
}

function applyFilterState(state) {
    FILTER_IDS.forEach(id => {
        const el = document.getElementById(id);
        if (el && state[id] !== undefined) el.value = state[id];
    });
    const showStale = document.getElementById('filter-show-stale');
    if (showStale && state['filter-show-stale'] !== undefined) showStale.checked = state['filter-show-stale'];
}

function saveFilterState() {
    try { localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(getFilterState())); } catch {}
}

function loadSavedFilterState() {
    try {
        const raw = localStorage.getItem(FILTER_STORAGE_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch { return null; }
}

let _cachedViews = null;
let _viewsMigrating = false;

async function getSmartViews() {
    if (_cachedViews) return _cachedViews;
    try {
        const data = await api.request('GET', '/api/saved-views');
        _cachedViews = data.views || [];
        if (!_viewsMigrating) {
            try {
                const raw = localStorage.getItem(SMART_VIEWS_KEY);
                if (raw) {
                    _viewsMigrating = true;
                    const localViews = JSON.parse(raw);
                    if (localViews.length > 0) {
                        const existingNames = new Set(_cachedViews.map(v => v.name));
                        for (const lv of localViews) {
                            if (!existingNames.has(lv.name)) {
                                await api.request('POST', '/api/saved-views', { name: lv.name, filters: lv.filters });
                            }
                        }
                        localStorage.removeItem(SMART_VIEWS_KEY);
                        _cachedViews = null;
                        _viewsMigrating = false;
                        return getSmartViews();
                    }
                    _viewsMigrating = false;
                }
            } catch { _viewsMigrating = false; }
        }
        return _cachedViews;
    } catch {
        return [];
    }
}

function invalidateViewsCache() {
    _cachedViews = null;
}

async function renderSmartViewChips(reloadFn) {
    const container = document.getElementById('smart-views');
    if (!container) return;
    const views = await getSmartViews();
    container.innerHTML = views.map(v => `
        <button class="smart-view-chip" data-view-id="${v.id}" title="Apply: ${escapeHtml(v.name)}">
            ${escapeHtml(v.name)}
            <span class="smart-view-delete" data-view-id="${v.id}">&times;</span>
        </button>
    `).join('');

    container.querySelectorAll('.smart-view-chip').forEach(chip => {
        chip.addEventListener('click', (e) => {
            if (e.target.classList.contains('smart-view-delete')) return;
            const viewId = parseInt(chip.dataset.viewId);
            const view = views.find(v => v.id === viewId);
            if (view) {
                applyFilterState(view.filters);
                saveFilterState();
                container.querySelectorAll('.smart-view-chip').forEach(c => c.classList.remove('smart-view-chip-active'));
                chip.classList.add('smart-view-chip-active');
                reloadFn();
            }
        });
    });

    container.querySelectorAll('.smart-view-delete').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const viewId = parseInt(btn.dataset.viewId);
            try {
                await api.request('DELETE', `/api/saved-views/${viewId}`);
                invalidateViewsCache();
                renderSmartViewChips(reloadFn);
            } catch (err) {
                showToast(err.message, 'error');
            }
        });
    });
}

// === Scrape Handler ===
let scrapePollInterval = null;
let currentScrapeTaskId = null;
let stallToastShownForTaskId = null;
let lastScrapeState = null;

const SCRAPE_POLL_MS = 1500;
const STALL_WARN_SEC = 30;
const STALL_CRITICAL_SEC = 120;

function stopScrapePoll() {
    if (scrapePollInterval) { clearInterval(scrapePollInterval); scrapePollInterval = null; }
}

function getScrapeButtons() {
    return [
        document.getElementById('scrape-btn'),
        document.getElementById('stats-scrape-btn'),
    ].filter(Boolean);
}

function phaseLabel(p) {
    const phase = p && p.phase;
    if (phase === 'scraping') {
        const name = p.current || '';
        const progress = `${p.completed || 0}/${p.total || 0}`;
        return name ? `Scraping: ${name} (${progress})` : `Scraping ${progress}`;
    }
    if (phase === 'enriching') return 'Enriching job details\u2026';
    if (phase === 'classifying') return 'Classifying locations\u2026';
    if (phase === 'scoring') {
        const s = (p && p.scoring) || {};
        return `Scoring: ${s.scored || 0}/${s.total || 0}`;
    }
    if (phase === 'done') return 'Done';
    if (phase === 'error') return 'Error';
    return 'Working\u2026';
}

function computeStallSec(p) {
    if (!p || typeof p.server_now !== 'number' || typeof p.last_updated_at !== 'number') return 0;
    return Math.max(0, p.server_now - p.last_updated_at);
}

function setCancelLinkVisible(visible, btn) {
    const parent = btn.parentElement;
    if (!parent) return;
    let link = parent.querySelector('.scrape-cancel-link');
    if (!visible) {
        if (link) link.remove();
        return;
    }
    if (link) return;
    link = document.createElement('a');
    link.className = 'scrape-cancel-link';
    link.href = '#';
    link.textContent = 'Cancel';
    link.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        cancelScrape();
    });
    btn.insertAdjacentElement('afterend', link);
}

function renderScrapeButtonState(p) {
    const btns = getScrapeButtons();
    if (!btns.length) return;

    const stallSec = computeStallSec(p);
    const critical = stallSec > STALL_CRITICAL_SEC;
    const warn = stallSec > STALL_WARN_SEC;

    let label = phaseLabel(p);
    if (warn) {
        const secs = Math.round(stallSec);
        const current = p.current || p.phase || 'working';
        label = `Stalled \u2014 ${current} (${secs}s)`;
    }

    btns.forEach(btn => {
        btn.disabled = true;
        btn.classList.remove('scrape-btn-warn', 'scrape-btn-critical');
        if (critical) btn.classList.add('scrape-btn-critical');
        else if (warn) btn.classList.add('scrape-btn-warn');
        btn.innerHTML = `<span class="spinner"></span> ${escapeHtml(label)}`;
        setCancelLinkVisible(warn, btn);
    });
}

function resetScrapeButtons() {
    getScrapeButtons().forEach(btn => {
        btn.disabled = false;
        btn.classList.remove('scrape-btn-warn', 'scrape-btn-critical');
        btn.textContent = 'Scrape Now';
        setCancelLinkVisible(false, btn);
    });
}

async function pollScrapeOnce() {
    let p;
    try {
        p = await api.getScrapeProgress();
    } catch {
        return;
    }
    lastScrapeState = p;

    if (!p || !p.active) {
        stopScrapePoll();
        resetScrapeButtons();
        currentScrapeTaskId = null;
        if (p && p.phase === 'done') {
            showScrapeSummaryToast(p);
            handleRoute();
        } else if (p && p.phase === 'error') {
            showScrapeErrorToast(p);
        }
        return;
    }

    renderScrapeButtonState(p);

    const stallSec = computeStallSec(p);
    if (stallSec > STALL_CRITICAL_SEC && stallToastShownForTaskId !== p.task_id) {
        stallToastShownForTaskId = p.task_id;
        showToast('Scrape appears stuck \u2014 click Cancel to stop.', 'error');
    }
}

function startScrapePoll(taskId) {
    stopScrapePoll();
    currentScrapeTaskId = taskId || null;
    stallToastShownForTaskId = null;
    pollScrapeOnce();
    scrapePollInterval = setInterval(pollScrapeOnce, SCRAPE_POLL_MS);
}

async function handleScrape() {
    const btns = getScrapeButtons();
    btns.forEach(btn => {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> Starting\u2026';
        setCancelLinkVisible(false, btn);
    });
    try {
        const result = await api.triggerScrape();
        startScrapePoll(result && result.task_id);
    } catch (err) {
        showToast(err.message, 'error');
        resetScrapeButtons();
    }
}

async function cancelScrape() {
    try {
        await api.cancelScrape();
        getScrapeButtons().forEach(btn => {
            btn.innerHTML = '<span class="spinner"></span> Cancelling\u2026';
        });
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function showToastWithAction(message, type, actionText, onAction) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type} toast-with-action`;
    const msg = document.createElement('span');
    msg.textContent = message;
    const action = document.createElement('button');
    action.className = 'toast-action-btn';
    action.type = 'button';
    action.textContent = actionText;
    action.addEventListener('click', () => {
        toast.remove();
        try { onAction(); } catch {}
    });
    toast.appendChild(msg);
    toast.appendChild(document.createTextNode(' '));
    toast.appendChild(action);
    container.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('toast-dismiss');
        toast.addEventListener('animationend', () => toast.remove());
    }, 8000);
}

function showScrapeSummaryToast(p) {
    const sources = p.sources || [];
    const ok = sources.filter(s => s.status === 'ok').length;
    const timeout = sources.filter(s => s.status === 'timeout').length;
    const failed = sources.filter(s => s.status === 'failed').length;
    const total = p.total || sources.length;

    let summary = `Scrape complete \u2014 ${p.new_jobs || 0} new jobs. ${ok}/${total} sources ok`;
    if (timeout) summary += `, ${timeout} timeout`;
    if (failed) summary += `, ${failed} failed`;

    showToastWithAction(summary, 'success', 'View details', () => showScrapeDetailsModal(p));
}

function showScrapeErrorToast(p) {
    const first = (p.errors && p.errors[0]) || 'unknown error';
    showToastWithAction(`Scrape failed \u2014 ${first}`, 'error', 'View details', () => showScrapeDetailsModal(p));
}

function sourceStatusBadgeHTML(status) {
    const map = {
        ok: 'score-badge-green',
        failed: 'score-badge-red',
        timeout: 'score-badge-amber',
        skipped: 'score-badge-gray',
        running: 'score-badge-gray',
        pending: 'score-badge-gray',
    };
    const cls = map[status] || 'score-badge-gray';
    return `<span class="score-badge ${cls}">${escapeHtml(status || '')}</span>`;
}

function showScrapeDetailsModal(p) {
    const existing = document.getElementById('app-modal');
    if (existing) existing.remove();

    const sources = p.sources || [];
    const rows = sources.map(s => `
        <tr>
            <td>${escapeHtml(s.name || '')}</td>
            <td>${sourceStatusBadgeHTML(s.status)}</td>
            <td>${s.duration_ms != null ? (s.duration_ms / 1000).toFixed(1) + 's' : '\u2014'}</td>
            <td>${s.listings_found || 0}</td>
            <td>${s.new_jobs || 0}</td>
            <td>${s.error ? escapeHtml(s.error) : '\u2014'}</td>
        </tr>
    `).join('');

    const errorsHtml = (p.errors && p.errors.length)
        ? `<div class="scrape-modal-errors"><strong>Pipeline errors:</strong><ul>${p.errors.map(e => `<li>${escapeHtml(e)}</li>`).join('')}</ul></div>`
        : '';

    const scoring = p.scoring || {};
    const scoringHtml = (scoring.total || scoring.scored || scoring.skipped_reason)
        ? `<div class="scrape-modal-scoring"><strong>Scoring:</strong> ${scoring.skipped_reason ? escapeHtml('skipped \u2014 ' + scoring.skipped_reason) : `${scoring.scored || 0}/${scoring.total || 0}`}</div>`
        : '';

    const modal = document.createElement('div');
    modal.id = 'app-modal';
    modal.innerHTML = `
        <div class="modal-overlay">
            <div class="modal-content modal-wide" role="dialog" aria-modal="true" aria-labelledby="scrape-modal-title">
                <div class="scrape-modal-header">
                    <h3 id="scrape-modal-title" class="modal-title">Scrape Details</h3>
                    <button class="btn btn-ghost btn-sm" id="scrape-modal-close" type="button">Close</button>
                </div>
                <div class="scrape-modal-summary">
                    Phase: <strong>${escapeHtml(p.phase || '')}</strong> \u2014 ${p.new_jobs || 0} new jobs
                </div>
                ${scoringHtml}
                <table class="scrape-sources-table">
                    <thead>
                        <tr><th>Source</th><th>Status</th><th>Duration</th><th>Listings</th><th>New</th><th>Error</th></tr>
                    </thead>
                    <tbody>${rows || '<tr><td colspan="6">No sources recorded.</td></tr>'}</tbody>
                </table>
                ${errorsHtml}
            </div>
        </div>
    `;
    document.body.appendChild(modal);

    modal.querySelector('#scrape-modal-close').addEventListener('click', () => modal.remove());
    modal.querySelector('.modal-overlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) modal.remove();
    });
    modal.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { e.stopPropagation(); modal.remove(); }
    });
}

async function initScrapeResume() {
    try {
        const p = await api.getScrapeProgress();
        if (p && p.active) {
            startScrapePoll(p.task_id);
        }
    } catch {}
}

// === Theme Toggle ===
function initTheme() {
    const saved = localStorage.getItem('jf_theme');
    if (saved) {
        document.documentElement.setAttribute('data-theme', saved);
    } else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
        document.documentElement.setAttribute('data-theme', 'dark');
    }
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('jf_theme', next);
}

// === Keyboard Shortcuts ===
let focusedJobIndex = -1;

const SHORTCUTS = {
    'j': { desc: 'Next job', action: () => navigateJob(1) },
    'k': { desc: 'Previous job', action: () => navigateJob(-1) },
    'o': { desc: 'Open job listing', action: openCurrentJob },
    'd': { desc: 'Dismiss job', action: dismissCurrentJob },
    'p': { desc: 'Prepare application', action: prepareCurrentJob },
    's': { desc: 'Scrape now', action: handleScrape },
    '/': { desc: 'Focus search', action: focusSearch },
    't': { desc: 'Triage mode', action: enterTriageMode },
    '?': { desc: 'Show shortcuts', action: toggleShortcutsHelp },
    'Escape': { desc: 'Close / Go back', action: goBack },
};

document.addEventListener('keydown', (e) => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;

    // Triage mode key bindings
    if (triageActive) {
        if (e.key === 'ArrowRight') { e.preventDefault(); triageKeep(); return; }
        if (e.key === 'ArrowLeft') { e.preventDefault(); triageDismiss(); return; }
        if (e.key === 'ArrowDown') { e.preventDefault(); triageSkip(); return; }
        if (e.key === 'z') { e.preventDefault(); triageUndo(); return; }
        if (e.key === 'Enter') {
            e.preventDefault();
            const job = triageJobs[triageIndex];
            if (job) navigate(`#/job/${job.id}`);
            return;
        }
        if (e.key === 'Escape') { e.preventDefault(); exitTriageMode(); return; }
        return;
    }

    if (e.key === 'Enter' && focusedJobIndex >= 0) {
        const cards = document.querySelectorAll('.job-card');
        if (cards[focusedJobIndex]) cards[focusedJobIndex].click();
        return;
    }

    const key = e.key;
    const shortcut = SHORTCUTS[key];
    if (shortcut) {
        e.preventDefault();
        shortcut.action();
    }
});

function navigateJob(delta) {
    const cards = document.querySelectorAll('.job-card');
    if (!cards.length) return;
    cards.forEach(c => c.classList.remove('job-card-focused'));
    focusedJobIndex = Math.max(0, Math.min(cards.length - 1, focusedJobIndex + delta));
    const card = cards[focusedJobIndex];
    card.classList.add('job-card-focused');
    card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function openCurrentJob() {
    const openLink = document.querySelector('a[target="_blank"][href^="http"]');
    if (openLink) window.open(openLink.href, '_blank');
}

function dismissCurrentJob() {
    const cards = document.querySelectorAll('.job-card');
    if (focusedJobIndex >= 0 && focusedJobIndex < cards.length) {
        const dismissBtn = cards[focusedJobIndex].querySelector('.dismiss-btn');
        if (dismissBtn) dismissBtn.click();
    }
}

function prepareCurrentJob() {
    const prepareBtn = document.getElementById('prepare-btn');
    if (prepareBtn && !prepareBtn.disabled) prepareBtn.click();
}

function focusSearch() {
    const searchInput = document.querySelector('.search-input');
    if (searchInput) searchInput.focus();
}

function goBack() {
    const modal = document.getElementById('shortcuts-modal');
    if (modal) { modal.remove(); return; }

    const appModal = document.getElementById('app-modal');
    if (appModal) { appModal.remove(); return; }

    if (notifDropdownOpen) {
        closeNotifDropdown();
        return;
    }

    if (window.location.hash.startsWith('#/job/')) {
        window.location.hash = '#/';
    }
}

function toggleShortcutsHelp() {
    let modal = document.getElementById('shortcuts-modal');
    if (modal) { modal.remove(); return; }
    modal = document.createElement('div');
    modal.id = 'shortcuts-modal';
    modal.innerHTML = `
        <div class="modal-overlay" onclick="document.getElementById('shortcuts-modal').remove()">
            <div class="modal-content" onclick="event.stopPropagation()">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
                    <h2 style="font-size:1.125rem;font-weight:700;margin:0">Keyboard Shortcuts</h2>
                    <button class="btn btn-ghost btn-sm" onclick="document.getElementById('shortcuts-modal').remove()">Close</button>
                </div>
                <div class="shortcuts-grid">
                    ${Object.entries(SHORTCUTS).map(([key, {desc}]) =>
                        `<div class="shortcut-key"><kbd>${key === ' ' ? 'Space' : key}</kbd></div><div class="shortcut-desc">${desc}</div>`
                    ).join('')}
                    <div class="shortcut-key"><kbd>Enter</kbd></div><div class="shortcut-desc">Open focused job</div>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
}

// === Init ===
// === Reminder Actions (global for onclick handlers) ===
window.completeReminder = async function(id) {
    try {
        await api.request('POST', `/api/reminders/${id}/complete`);
        showToast('Reminder completed', 'success');
        handleRoute();
    } catch (err) { showToast(err.message, 'error'); }
};
window.dismissReminder = async function(id) {
    try {
        await api.request('POST', `/api/reminders/${id}/dismiss`);
        showToast('Reminder dismissed', 'success');
        handleRoute();
    } catch (err) { showToast(err.message, 'error'); }
};

// === Notifications ===
let notifDropdownOpen = false;

async function updateNotifBadge() {
    try {
        const data = await api.getNotifications();
        const badge = document.getElementById('notif-badge');
        if (badge) {
            badge.textContent = data.unread_count;
            badge.style.display = data.unread_count > 0 ? '' : 'none';
        }
    } catch {}
}

function renderNotifDropdown(notifications) {
    const dropdown = document.getElementById('notif-dropdown');
    if (!dropdown) return;

    if (notifications.length === 0) {
        dropdown.innerHTML = `<div class="notif-empty">No notifications</div>`;
        return;
    }

    dropdown.innerHTML = `
        <div class="notif-header">
            <span style="font-weight:600;font-size:0.875rem">Notifications</span>
            <button class="btn btn-ghost btn-sm" id="notif-read-all">Mark all read</button>
        </div>
        <div class="notif-list">
            ${notifications.slice(0, 20).map(n => `
                <div class="notif-item ${n.read ? '' : 'notif-unread'}" data-notif-id="${n.id}" data-job-id="${n.job_id}">
                    <div class="notif-item-title">${escapeHtml(n.title)}</div>
                    <div class="notif-item-message">${escapeHtml(n.message)}</div>
                </div>
            `).join('')}
        </div>
    `;

    document.getElementById('notif-read-all')?.addEventListener('click', async (e) => {
        e.stopPropagation();
        await api.markAllNotificationsRead();
        updateNotifBadge();
        dropdown.querySelectorAll('.notif-unread').forEach(el => el.classList.remove('notif-unread'));
    });

    dropdown.querySelectorAll('.notif-item').forEach(item => {
        item.addEventListener('click', async () => {
            const notifId = item.dataset.notifId;
            const jobId = item.dataset.jobId;
            await api.markNotificationRead(notifId);
            item.classList.remove('notif-unread');
            updateNotifBadge();
            dropdown.style.display = 'none';
            notifDropdownOpen = false;
            navigate(`#/job/${jobId}`);
        });
    });
}

async function toggleNotifDropdown() {
    const dropdown = document.getElementById('notif-dropdown');
    const btn = document.getElementById('notif-btn');
    if (!dropdown) return;
    notifDropdownOpen = !notifDropdownOpen;
    btn?.setAttribute('aria-expanded', String(notifDropdownOpen));
    if (notifDropdownOpen) {
        dropdown.style.display = 'block';
        try {
            const data = await api.getNotifications();
            renderNotifDropdown(data.notifications);
        } catch {}
    } else {
        dropdown.style.display = 'none';
    }
}

function closeNotifDropdown() {
    if (!notifDropdownOpen) return;
    document.getElementById('notif-dropdown').style.display = 'none';
    notifDropdownOpen = false;
    const btn = document.getElementById('notif-btn');
    btn?.setAttribute('aria-expanded', 'false');
    btn?.focus();
}

let _notifEventSource = null;
let _notifSSERetries = 0;
const _NOTIF_SSE_MAX_RETRIES = 5;

function initNotificationSSE() {
    if (_notifEventSource) { _notifEventSource.close(); _notifEventSource = null; }
    _notifEventSource = new EventSource('/api/notifications/stream');
    _notifEventSource.onmessage = (event) => {
        try {
            _notifSSERetries = 0;
            const notif = JSON.parse(event.data);
            showToast(`${notif.title}: ${notif.message}`, 'info');
            updateNotifBadge();
        } catch {}
    };
    _notifEventSource.onerror = () => {
        _notifEventSource.close();
        _notifEventSource = null;
        _notifSSERetries++;
        if (_notifSSERetries <= _NOTIF_SSE_MAX_RETRIES) {
            const delay = Math.min(30000 * Math.pow(2, _notifSSERetries - 1), 300000);
            setTimeout(initNotificationSSE, delay);
        }
    };
}

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    if (!isOnboardingDone()) {
        showOnboardingWizard();
    }
    updateSetupIndicator();
    handleRoute();

    window.addEventListener('hashchange', handleRoute);
    document.getElementById('scrape-btn').addEventListener('click', handleScrape);
    document.getElementById('theme-toggle').addEventListener('click', toggleTheme);
    document.getElementById('notif-btn').addEventListener('click', toggleNotifDropdown);

    // === Hamburger Menu ===
    const hamburger = document.getElementById('nav-hamburger');
    const navLinks = document.querySelector('.nav-links');
    const drawerOverlay = document.getElementById('nav-drawer-overlay');

    function openDrawer() {
        navLinks.classList.add('nav-drawer-open');
        drawerOverlay.classList.add('active');
        hamburger.setAttribute('aria-expanded', 'true');
    }

    function closeDrawer() {
        navLinks.classList.remove('nav-drawer-open');
        drawerOverlay.classList.remove('active');
        hamburger.setAttribute('aria-expanded', 'false');
    }

    function toggleDrawer() {
        if (navLinks.classList.contains('nav-drawer-open')) {
            closeDrawer();
        } else {
            openDrawer();
        }
    }

    hamburger.addEventListener('click', toggleDrawer);
    drawerOverlay.addEventListener('click', closeDrawer);

    navLinks.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', closeDrawer);
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && navLinks.classList.contains('nav-drawer-open')) {
            closeDrawer();
            hamburger.focus();
        }
    });

    // Close dropdown on outside click
    document.addEventListener('click', (e) => {
        if (notifDropdownOpen && !e.target.closest('.notif-btn') && !e.target.closest('.notif-dropdown')) {
            closeNotifDropdown();
        }
    });

    updateNotifBadge();
    initNotificationSSE();
    initScrapeResume();
});
