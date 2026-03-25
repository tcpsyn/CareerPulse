// === API Client ===
const api = {
    async request(method, path, body = null) {
        const opts = { method, headers: {} };
        if (body) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
        const res = await fetch(path, opts);
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || `Request failed: ${res.status}`);
        }
        return res.json();
    },

    getJobs(params = {}) {
        const qs = new URLSearchParams();
        Object.entries(params).forEach(([k, v]) => {
            if (v !== null && v !== undefined && v !== '') qs.set(k, v);
        });
        return this.request('GET', `/api/jobs?${qs}`);
    },

    getJob(id) {
        return this.request('GET', `/api/jobs/${id}`);
    },

    getStats() {
        return this.request('GET', '/api/stats');
    },

    dismissJob(id) {
        return this.request('POST', `/api/jobs/${id}/dismiss`);
    },

    getNotifications(unread = false) {
        return this.request('GET', `/api/notifications?unread=${unread}`);
    },

    markNotificationRead(id) {
        return this.request('POST', `/api/notifications/${id}/read`);
    },

    markAllNotificationsRead() {
        return this.request('POST', '/api/notifications/read-all');
    },

    prepareApplication(id, resumeId = null) {
        const body = resumeId ? { resume_id: resumeId } : null;
        return this.request('POST', `/api/jobs/${id}/prepare`, body);
    },

    updateApplication(id, status, notes = '') {
        const qs = new URLSearchParams({ status, notes });
        return this.request('POST', `/api/jobs/${id}/application?${qs}`);
    },

    triggerScrape() {
        return this.request('POST', '/api/scrape');
    },

    draftEmail(id) {
        return this.request('POST', `/api/jobs/${id}/email`);
    },

    generateCoverLetter(id) {
        return this.request('POST', `/api/jobs/${id}/generate-cover-letter`);
    },

    addEvent(id, detail) {
        return this.request('POST', `/api/jobs/${id}/events`, { detail });
    },

    getSearchConfig() {
        return this.request('GET', '/api/search-config');
    },

    updateSearchTerms(terms) {
        return this.request('POST', '/api/search-config/terms', { search_terms: terms });
    },

    async uploadResume(file) {
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch('/api/resume/upload', { method: 'POST', body: formData });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || `Upload failed: ${res.status}`);
        }
        return res.json();
    },

    getAISettings() {
        return this.request('GET', '/api/ai-settings');
    },

    updateAISettings(settings) {
        return this.request('POST', '/api/ai-settings', settings);
    },

    testAIConnection(settings) {
        return this.request('POST', '/api/ai-settings/test', settings);
    },

    getOllamaModels(baseUrl) {
        const qs = new URLSearchParams({ base_url: baseUrl || 'http://localhost:11434' });
        return this.request('GET', `/api/ai-settings/models?${qs}`);
    },

    // === Interview Rounds ===

    getInterviews(jobId) {
        return this.request('GET', `/api/jobs/${jobId}/interviews`);
    },

    createInterview(jobId, data) {
        return this.request('POST', `/api/jobs/${jobId}/interviews`, data);
    },

    updateInterview(id, data) {
        return this.request('PUT', `/api/interviews/${id}`, data);
    },

    deleteInterview(id) {
        return this.request('DELETE', `/api/interviews/${id}`);
    },

    promoteInterviewer(interviewId, contactData) {
        return this.request('POST', `/api/interviews/${interviewId}/promote-interviewer`, contactData);
    },

    // === Calendar ===

    getCalendarEvents(params = {}) {
        const qs = new URLSearchParams();
        Object.entries(params).forEach(([k, v]) => {
            if (v !== null && v !== undefined && v !== '') qs.set(k, v);
        });
        return this.request('GET', `/api/calendar?${qs}`);
    },

    getIcalToken() {
        return this.request('GET', '/api/calendar/ical-token');
    },

    regenerateIcalToken() {
        return this.request('POST', '/api/calendar/ical-token');
    },

    // === External Jobs ===

    saveExternalJob(data) {
        return this.request('POST', '/api/jobs/save-external', data);
    },
};
