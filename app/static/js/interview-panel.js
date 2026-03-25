// === Interview Detail Panel (Slide-Out Drawer) ===

function openInterviewPanel(roundId, jobId) {
    closeInterviewPanel();

    const backdrop = document.createElement('div');
    backdrop.id = 'interview-panel';
    backdrop.innerHTML = `
        <div class="interview-drawer-backdrop"></div>
        <div class="interview-drawer" role="dialog" aria-modal="true" aria-labelledby="iv-panel-title">
            <div class="interview-drawer-header">
                <h2 id="iv-panel-title">Interview Detail</h2>
                <button class="interview-drawer-close" id="iv-panel-close" aria-label="Close">&times;</button>
            </div>
            <div class="interview-drawer-body interview-drawer-body-single">
                <div class="interview-drawer-content" id="iv-panel-left">
                    <div class="loading-container"><div class="spinner"></div></div>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(backdrop);
    document.body.style.overflow = 'hidden';

    // Animate in
    requestAnimationFrame(() => {
        backdrop.querySelector('.interview-drawer-backdrop').classList.add('active');
        backdrop.querySelector('.interview-drawer').classList.add('open');
    });

    // Close handlers
    const close = () => closeInterviewPanel();
    backdrop.querySelector('.interview-drawer-backdrop').addEventListener('click', close);
    backdrop.querySelector('#iv-panel-close').addEventListener('click', close);
    backdrop.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') close();
        // Focus trap
        if (e.key === 'Tab') {
            const focusable = backdrop.querySelectorAll('button, input, select, textarea, a[href]');
            if (focusable.length === 0) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
    });

    // Focus the close button
    backdrop.querySelector('#iv-panel-close').focus();

    // Load data
    loadInterviewPanelData(backdrop, roundId, jobId);
}

async function loadInterviewPanelData(backdrop, roundId, jobId) {
    const panel = backdrop.querySelector('#iv-panel-left');

    try {
        const [roundsData, job] = await Promise.all([
            api.getInterviews(jobId),
            api.getJob(jobId)
        ]);

        const rounds = roundsData.rounds || [];
        const round = rounds.find(r => r.id === roundId) || rounds[0];

        if (!round) {
            panel.innerHTML = `<div class="empty-state empty-state-compact"><div class="empty-state-title">Interview not found</div></div>`;
            return;
        }

        renderInterviewPanelLeft(panel, round, job);
    } catch (err) {
        panel.innerHTML = `<div class="empty-state empty-state-compact"><div class="empty-state-title">Failed to load</div><div class="empty-state-desc">${escapeHtml(err.message)}</div></div>`;
    }
}

function renderInterviewPanelLeft(panel, round, job) {
    const statusColors = {
        scheduled: 'var(--accent)',
        completed: 'var(--score-green)',
        cancelled: 'var(--danger)'
    };
    const statusColor = statusColors[round.status] || 'var(--text-secondary)';

    const formatPanelDate = (isoStr) => {
        if (!isoStr) return 'Not scheduled';
        return new Date(isoStr).toLocaleDateString('en-US', {
            weekday: 'short', month: 'short', day: 'numeric', year: 'numeric'
        });
    };

    const formatPanelTime = (isoStr, durationMin) => {
        if (!isoStr) return '';
        const start = new Date(isoStr);
        const end = new Date(start.getTime() + (durationMin || 60) * 60000);
        const fmt = d => d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
        return `${fmt(start)} — ${fmt(end)}`;
    };

    const isUrl = (str) => /^https?:\/\//.test(str || '');

    panel.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:16px">
            <span class="round-badge">Round ${round.round_number}${round.label ? ' — ' + escapeHtml(round.label) : ''}</span>
            <span class="interview-status-badge" data-status="${round.status}" style="background:${statusColor}18;color:${statusColor}">${round.status}</span>
        </div>

        <div style="margin-bottom:20px">
            <div style="font-size:1.125rem;font-weight:700;color:var(--text-primary)">${escapeHtml(job.title)}</div>
            <div style="font-size:0.875rem;color:var(--text-secondary)">${escapeHtml(job.company)}</div>
        </div>

        <div class="interview-details-grid">
            ${round.scheduled_at ? `
                <span class="detail-label">Date</span>
                <span class="detail-value">${formatPanelDate(round.scheduled_at)}</span>
                <span class="detail-label">Time</span>
                <span class="detail-value">${formatPanelTime(round.scheduled_at, round.duration_min)}</span>
            ` : ''}
            ${round.duration_min ? `
                <span class="detail-label">Duration</span>
                <span class="detail-value">${round.duration_min} min</span>
            ` : ''}
            ${round.interviewer_name ? `
                <span class="detail-label">Interviewer</span>
                <span class="detail-value">${escapeHtml(round.interviewer_name)}${round.interviewer_title ? `, ${escapeHtml(round.interviewer_title)}` : ''}</span>
            ` : ''}
            ${round.location ? `
                <span class="detail-label">Location</span>
                <span class="detail-value">${isUrl(round.location) ? `<a href="${sanitizeUrl(round.location)}" target="_blank" rel="noopener noreferrer" style="color:var(--accent)">${escapeHtml(round.location)}</a>` : escapeHtml(round.location)}</span>
            ` : ''}
        </div>

        ${round.notes ? `
            <div style="margin-top:16px">
                <div style="font-size:0.8125rem;font-weight:500;color:var(--text-tertiary);margin-bottom:4px">Notes</div>
                <div style="font-size:0.875rem;color:var(--text-secondary);white-space:pre-line;background:var(--bg-surface-secondary);padding:12px;border-radius:var(--radius-sm);max-height:120px;overflow-y:auto">${escapeHtml(round.notes)}</div>
            </div>
        ` : ''}

        ${round.status === 'scheduled' ? `
            <div style="display:flex;gap:8px;margin-top:20px">
                <button class="btn btn-primary btn-sm" id="iv-panel-complete">Mark Complete</button>
                <button class="btn btn-secondary btn-sm" id="iv-panel-cancel-round">Cancel Round</button>
            </div>
        ` : ''}

        <div style="margin-top:24px;padding-top:16px;border-top:1px solid var(--border)">
            <a href="#/job/${job.id}" class="iv-panel-job-link" id="iv-panel-view-job" style="color:var(--accent);font-size:0.875rem;font-weight:500">View Full Job Detail &rarr;</a>
        </div>
    `;

    // Wire status buttons
    const completeBtn = panel.querySelector('#iv-panel-complete');
    if (completeBtn) {
        completeBtn.addEventListener('click', async () => {
            completeBtn.disabled = true;
            completeBtn.innerHTML = '<span class="spinner"></span>';
            try {
                await api.updateInterview(round.id, { status: 'completed' });
                showToast('Marked complete', 'success');
                loadInterviewPanelData(panel.closest('#interview-panel'), round.id, round.job_id);
            } catch (err) {
                showToast(err.message, 'error');
                completeBtn.disabled = false;
                completeBtn.textContent = 'Mark Complete';
            }
        });
    }

    const cancelBtn = panel.querySelector('#iv-panel-cancel-round');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', async () => {
            cancelBtn.disabled = true;
            try {
                await api.updateInterview(round.id, { status: 'cancelled' });
                showToast('Interview cancelled', 'success');
                loadInterviewPanelData(panel.closest('#interview-panel'), round.id, round.job_id);
            } catch (err) {
                showToast(err.message, 'error');
                cancelBtn.disabled = false;
                cancelBtn.textContent = 'Cancel Round';
            }
        });
    }

    // View job link closes drawer
    const viewJobLink = panel.querySelector('#iv-panel-view-job');
    if (viewJobLink) {
        viewJobLink.addEventListener('click', () => closeInterviewPanel());
    }
}

function closeInterviewPanel() {
    const existing = document.getElementById('interview-panel');
    if (!existing) return;

    const drawer = existing.querySelector('.interview-drawer');
    const backdrop = existing.querySelector('.interview-drawer-backdrop');

    if (drawer) drawer.classList.remove('open');
    if (backdrop) backdrop.classList.remove('active');

    document.body.style.overflow = '';

    setTimeout(() => existing.remove(), 260);
}
