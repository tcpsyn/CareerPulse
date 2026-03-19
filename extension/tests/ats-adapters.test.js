import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { readFileSync } from 'fs';
import { join } from 'path';

function loadAdapters() {
  window.__cpAtsAdapters = undefined;
  const code = readFileSync(join(__dirname, '..', 'ats-adapters.js'), 'utf-8');
  eval(code);
  return window.__cpAtsAdapters;
}

let adapters;

beforeEach(() => {
  document.body.innerHTML = '';
  adapters = loadAdapters();
});

afterEach(() => {
  document.body.innerHTML = '';
});

// ═══════════════════════════════════════════════════════════════
// Registry
// ═══════════════════════════════════════════════════════════════

describe('adapter registry', () => {
  it('lists all adapter names', () => {
    const names = adapters.listAdapters();
    expect(names).toEqual(['Workday', 'Greenhouse', 'Lever', 'iCIMS', 'Taleo', 'Google Forms']);
  });

  it('has 6 adapters', () => {
    expect(adapters.adapters).toHaveLength(6);
  });

  it('guard against double-load', () => {
    const first = window.__cpAtsAdapters;
    // Load again — should return early since __cpAtsAdapters is already set
    const code = readFileSync(join(__dirname, '..', 'ats-adapters.js'), 'utf-8');
    eval(code);
    expect(window.__cpAtsAdapters).toBe(first);
  });
});

// ═══════════════════════════════════════════════════════════════
// detectATS
// ═══════════════════════════════════════════════════════════════

describe('detectATS', () => {
  it('returns null for unrecognized URL and DOM', () => {
    const result = adapters.detectATS('https://example.com', document);
    expect(result).toBeNull();
  });

  it('detects Workday by URL', () => {
    const result = adapters.detectATS('https://company.myworkdayjobs.com/en-US/careers', document);
    expect(result).not.toBeNull();
    expect(result.name).toBe('Workday');
  });

  it('detects Workday by data-automation-id attribute', () => {
    const div = document.createElement('div');
    div.setAttribute('data-automation-id', 'jobApplicationPage');
    document.body.appendChild(div);
    const result = adapters.detectATS('https://example.com', document);
    expect(result).not.toBeNull();
    expect(result.name).toBe('Workday');
  });

  it('detects Greenhouse by URL', () => {
    const result = adapters.detectATS('https://boards.greenhouse.io/company/jobs/123', document);
    expect(result).not.toBeNull();
    expect(result.name).toBe('Greenhouse');
  });

  it('detects Greenhouse by #app_form', () => {
    const form = document.createElement('form');
    form.id = 'app_form';
    document.body.appendChild(form);
    const result = adapters.detectATS('https://example.com', document);
    expect(result).not.toBeNull();
    expect(result.name).toBe('Greenhouse');
  });

  it('detects Greenhouse by #application_form', () => {
    const form = document.createElement('form');
    form.id = 'application_form';
    document.body.appendChild(form);
    const result = adapters.detectATS('https://example.com', document);
    expect(result).not.toBeNull();
    expect(result.name).toBe('Greenhouse');
  });

  it('detects Greenhouse by job-boards.greenhouse.io URL', () => {
    const result = adapters.detectATS('https://job-boards.greenhouse.io/embed/job_app?for=datadog&token=123', document);
    expect(result).not.toBeNull();
    expect(result.name).toBe('Greenhouse');
  });

  it('detects Greenhouse by #grnhse_app container', () => {
    const div = document.createElement('div');
    div.id = 'grnhse_app';
    document.body.appendChild(div);
    const result = adapters.detectATS('https://careers.example.com/apply', document);
    expect(result).not.toBeNull();
    expect(result.name).toBe('Greenhouse');
  });

  it('detects Lever by URL', () => {
    const result = adapters.detectATS('https://jobs.lever.co/company/position', document);
    expect(result).not.toBeNull();
    expect(result.name).toBe('Lever');
  });

  it('detects iCIMS by URL', () => {
    const result = adapters.detectATS('https://careers-company.icims.com/jobs/1234', document);
    expect(result).not.toBeNull();
    expect(result.name).toBe('iCIMS');
  });

  it('detects iCIMS by #iCIMS_MainWrapper', () => {
    const div = document.createElement('div');
    div.id = 'iCIMS_MainWrapper';
    document.body.appendChild(div);
    const result = adapters.detectATS('https://example.com', document);
    expect(result).not.toBeNull();
    expect(result.name).toBe('iCIMS');
  });

  it('detects Taleo by URL', () => {
    const result = adapters.detectATS('https://company.taleo.net/apply', document);
    expect(result).not.toBeNull();
    expect(result.name).toBe('Taleo');
  });

  it('detects Google Forms by URL', () => {
    const result = adapters.detectATS('https://docs.google.com/forms/d/e/abc123/viewform', document);
    expect(result).not.toBeNull();
    expect(result.name).toBe('Google Forms');
  });
});

// ═══════════════════════════════════════════════════════════════
// Workday adapter
// ═══════════════════════════════════════════════════════════════

describe('Workday adapter', () => {
  let workday;

  beforeEach(() => {
    workday = adapters.adapters.find(a => a.name === 'Workday');
  });

  it('getFieldMap returns mappings for common Workday fields', () => {
    const map = workday.getFieldMap();
    expect(map['[data-automation-id="legalNameSection_firstName"]']).toBe('first_name');
    expect(map['[data-automation-id="legalNameSection_lastName"]']).toBe('last_name');
    expect(map['[data-automation-id="email"]']).toBe('email');
    expect(map['[data-automation-id="phone-number"]']).toBe('phone');
    expect(map['[data-automation-id="countryPhoneCode"]']).toBe('phone_country_code');
    expect(map['[data-automation-id="phone-device-type"]']).toBe('phone_device_type');
  });

  it('getFormRoot returns document', () => {
    expect(workday.getFormRoot(document)).toBe(document);
  });

  it('getNextButton finds bottom-navigation-next-button', () => {
    const btn = document.createElement('button');
    btn.setAttribute('data-automation-id', 'bottom-navigation-next-button');
    document.body.appendChild(btn);
    expect(workday.getNextButton(document)).toBe(btn);
  });

  it('getNextButton returns null when no next button', () => {
    expect(workday.getNextButton(document)).toBeNull();
  });

  it('enhanceExtraction adds atsHint from data-automation-id', () => {
    const input = document.createElement('input');
    input.setAttribute('data-automation-id', 'legalNameSection_firstName');
    input.id = 'wd-first';
    document.body.appendChild(input);

    const fields = [{ selector: '#wd-first', label: '' }];
    const enhanced = workday.enhanceExtraction(fields);
    expect(enhanced[0].atsHint).toBe('legalNameSection_firstName');
  });

  it('getDropdownHandler returns a handler with detect and fill', () => {
    const handler = workday.getDropdownHandler();
    expect(handler).not.toBeNull();
    expect(typeof handler.detect).toBe('function');
    expect(typeof handler.fill).toBe('function');
  });

  it('dropdown handler detects combobox role with data-automation-id', () => {
    const handler = workday.getDropdownHandler();
    const el = document.createElement('div');
    el.setAttribute('data-automation-id', 'stateProvince');
    el.setAttribute('role', 'combobox');
    expect(handler.detect(el)).toBe(true);
  });

  it('dropdown handler does not detect regular elements', () => {
    const handler = workday.getDropdownHandler();
    const el = document.createElement('div');
    expect(handler.detect(el)).toBeFalsy();
  });
});

// ═══════════════════════════════════════════════════════════════
// Greenhouse adapter
// ═══════════════════════════════════════════════════════════════

describe('Greenhouse adapter', () => {
  let greenhouse;

  beforeEach(() => {
    greenhouse = adapters.adapters.find(a => a.name === 'Greenhouse');
  });

  it('getFieldMap includes standard Greenhouse selectors', () => {
    const map = greenhouse.getFieldMap();
    expect(map['#first_name']).toBe('first_name');
    expect(map['#last_name']).toBe('last_name');
    expect(map['#email']).toBe('email');
    expect(map['#phone']).toBe('phone');
    expect(map['#resume_text']).toBe('resume');
  });

  it('getFieldMap includes new React/Remix form selectors', () => {
    const map = greenhouse.getFieldMap();
    expect(map['input[name="first_name"]']).toBe('first_name');
    expect(map['input[name="last_name"]']).toBe('last_name');
    expect(map['input[name="email"]']).toBe('email');
    expect(map['input[name="phone"]']).toBe('phone');
    expect(map['input[name="preferred_name"]']).toBe('preferred_name');
  });

  it('getFormRoot returns #app_form if present', () => {
    const form = document.createElement('form');
    form.id = 'app_form';
    document.body.appendChild(form);
    expect(greenhouse.getFormRoot(document)).toBe(form);
  });

  it('getFormRoot returns #grnhse_app if present', () => {
    const div = document.createElement('div');
    div.id = 'grnhse_app';
    document.body.appendChild(div);
    expect(greenhouse.getFormRoot(document)).toBe(div);
  });

  it('getFormRoot returns first form element as fallback', () => {
    const form = document.createElement('form');
    document.body.appendChild(form);
    expect(greenhouse.getFormRoot(document)).toBe(form);
  });

  it('getFormRoot falls back to document when no form exists', () => {
    expect(greenhouse.getFormRoot(document)).toBe(document);
  });

  it('getNextButton returns null (single-page forms)', () => {
    expect(greenhouse.getNextButton(document)).toBeNull();
  });

  it('getDropdownHandler returns null', () => {
    expect(greenhouse.getDropdownHandler()).toBeNull();
  });

  it('enhanceExtraction tags resume fields', () => {
    const fields = [{ id: 'resume_text', name: 'resume_text' }];
    const enhanced = greenhouse.enhanceExtraction(fields);
    expect(enhanced[0].atsHint).toBe('resume_upload');
  });

  it('enhanceExtraction tags cover letter fields', () => {
    const fields = [{ id: 'cover_letter_text', name: 'cover_letter' }];
    const enhanced = greenhouse.enhanceExtraction(fields);
    expect(enhanced[0].atsHint).toBe('cover_letter');
  });
});

// ═══════════════════════════════════════════════════════════════
// Lever adapter
// ═══════════════════════════════════════════════════════════════

describe('Lever adapter', () => {
  let lever;

  beforeEach(() => {
    lever = adapters.adapters.find(a => a.name === 'Lever');
  });

  it('matches jobs.lever.co URLs', () => {
    expect(lever.match('https://jobs.lever.co/company/123', document)).toBe(true);
  });

  it('does not match other URLs', () => {
    expect(lever.match('https://example.com', document)).toBe(false);
  });

  it('getFieldMap includes Lever-specific selectors', () => {
    const map = lever.getFieldMap();
    expect(map['input[name="name"]']).toBe('full_name');
    expect(map['input[name="email"]']).toBe('email');
    expect(map['input[name="urls[LinkedIn]"]']).toBe('linkedin_url');
    expect(map['input[name="urls[GitHub]"]']).toBe('github_url');
  });

  it('getFormRoot prefers .application-form', () => {
    const form = document.createElement('div');
    form.className = 'application-form';
    document.body.appendChild(form);
    expect(lever.getFormRoot(document)).toBe(form);
  });

  it('getNextButton returns null', () => {
    expect(lever.getNextButton(document)).toBeNull();
  });

  it('getDropdownHandler returns null', () => {
    expect(lever.getDropdownHandler()).toBeNull();
  });

  it('enhanceExtraction marks Lever custom question fields', () => {
    const fields = [{ name: 'cards[abc123][field]' }];
    const enhanced = lever.enhanceExtraction(fields);
    expect(enhanced[0].atsHint).toBe('lever_custom_question');
  });

  it('enhanceExtraction does not mark regular fields', () => {
    const fields = [{ name: 'email' }];
    const enhanced = lever.enhanceExtraction(fields);
    expect(enhanced[0].atsHint).toBeUndefined();
  });
});

// ═══════════════════════════════════════════════════════════════
// iCIMS adapter
// ═══════════════════════════════════════════════════════════════

describe('iCIMS adapter', () => {
  let icims;

  beforeEach(() => {
    icims = adapters.adapters.find(a => a.name === 'iCIMS');
  });

  it('matches icims.com URLs', () => {
    expect(icims.match('https://careers.icims.com/jobs/1234', document)).toBe(true);
  });

  it('getFieldMap includes standard iCIMS fields', () => {
    const map = icims.getFieldMap();
    expect(map['#firstName']).toBe('first_name');
    expect(map['#lastName']).toBe('last_name');
    expect(map['#email']).toBe('email');
  });

  it('getFormRoot falls back to document when no iCIMS wrapper', () => {
    expect(icims.getFormRoot(document)).toBe(document);
  });

  it('getDropdownHandler returns null', () => {
    expect(icims.getDropdownHandler()).toBeNull();
  });
});

// ═══════════════════════════════════════════════════════════════
// Taleo adapter
// ═══════════════════════════════════════════════════════════════

describe('Taleo adapter', () => {
  let taleo;

  beforeEach(() => {
    taleo = adapters.adapters.find(a => a.name === 'Taleo');
  });

  it('matches taleo.net URLs', () => {
    expect(taleo.match('https://company.taleo.net/careersection/apply', document)).toBe(true);
  });

  it('getFieldMap includes standard Taleo fields', () => {
    const map = taleo.getFieldMap();
    expect(map['#FirstName']).toBe('first_name');
    expect(map['#LastName']).toBe('last_name');
    expect(map['#Email']).toBe('email');
  });

  it('getFormRoot falls back to document', () => {
    expect(taleo.getFormRoot(document)).toBe(document);
  });

  it('getDropdownHandler returns a handler', () => {
    const handler = taleo.getDropdownHandler();
    expect(handler).not.toBeNull();
    expect(typeof handler.detect).toBe('function');
    expect(typeof handler.fill).toBe('function');
  });

  it('dropdown handler detects Taleo-style dropdowns', () => {
    const handler = taleo.getDropdownHandler();
    const el = document.createElement('div');
    el.className = 'taleo-dropdown';
    el.setAttribute('role', 'listbox');
    expect(handler.detect(el)).toBe(true);
  });

  it('dropdown handler does not detect non-Taleo elements', () => {
    const handler = taleo.getDropdownHandler();
    const el = document.createElement('div');
    el.className = 'regular-element';
    expect(handler.detect(el)).toBe(false);
  });
});

// ═══════════════════════════════════════════════════════════════
// Google Forms adapter
// ═══════════════════════════════════════════════════════════════

describe('Google Forms adapter', () => {
  let googleForms;

  beforeEach(() => {
    googleForms = adapters.adapters.find(a => a.name === 'Google Forms');
  });

  it('matches docs.google.com/forms URLs', () => {
    expect(googleForms.match('https://docs.google.com/forms/d/e/abc123/viewform')).toBe(true);
  });

  it('does not match other Google URLs', () => {
    expect(googleForms.match('https://docs.google.com/spreadsheets/d/abc')).toBe(false);
  });

  it('getFieldMap returns empty (dynamic IDs)', () => {
    const map = googleForms.getFieldMap();
    expect(Object.keys(map)).toHaveLength(0);
  });

  it('getFormRoot prefers [role="form"]', () => {
    const form = document.createElement('div');
    form.setAttribute('role', 'form');
    document.body.appendChild(form);
    expect(googleForms.getFormRoot(document)).toBe(form);
  });

  it('getFormRoot falls back to <form>', () => {
    const form = document.createElement('form');
    document.body.appendChild(form);
    expect(googleForms.getFormRoot(document)).toBe(form);
  });

  it('getExtraFields extracts text input from question blocks', () => {
    const block = document.createElement('div');
    block.setAttribute('data-params', 'test');
    const heading = document.createElement('div');
    heading.setAttribute('role', 'heading');
    heading.textContent = 'Your Name';
    block.appendChild(heading);
    const input = document.createElement('input');
    input.type = 'text';
    input.id = 'gf-name';
    block.appendChild(input);
    document.body.appendChild(block);

    const fields = googleForms.getExtraFields(document);
    expect(fields.length).toBeGreaterThanOrEqual(1);
    expect(fields[0].label).toBe('Your Name');
    expect(fields[0].type).toBe('text');
  });

  it('getExtraFields extracts radio groups', () => {
    const block = document.createElement('div');
    block.id = 'q-radio';
    block.setAttribute('data-params', 'test');
    const heading = document.createElement('div');
    heading.setAttribute('role', 'heading');
    heading.textContent = 'Preferred Contact';
    block.appendChild(heading);
    const radio1 = document.createElement('div');
    radio1.setAttribute('role', 'radio');
    radio1.setAttribute('aria-label', 'Email');
    block.appendChild(radio1);
    const radio2 = document.createElement('div');
    radio2.setAttribute('role', 'radio');
    radio2.setAttribute('aria-label', 'Phone');
    block.appendChild(radio2);
    document.body.appendChild(block);

    const fields = googleForms.getExtraFields(document);
    const radioField = fields.find(f => f.type === 'radio');
    expect(radioField).toBeDefined();
    expect(radioField.label).toBe('Preferred Contact');
    expect(radioField.options).toHaveLength(2);
  });

  it('getExtraFields extracts checkbox groups', () => {
    const block = document.createElement('div');
    block.id = 'q-cb';
    block.setAttribute('data-params', 'test');
    const heading = document.createElement('div');
    heading.setAttribute('role', 'heading');
    heading.textContent = 'Skills';
    block.appendChild(heading);
    const cb1 = document.createElement('div');
    cb1.setAttribute('role', 'checkbox');
    cb1.setAttribute('aria-label', 'JavaScript');
    block.appendChild(cb1);
    const cb2 = document.createElement('div');
    cb2.setAttribute('role', 'checkbox');
    cb2.setAttribute('aria-label', 'Python');
    block.appendChild(cb2);
    document.body.appendChild(block);

    const fields = googleForms.getExtraFields(document);
    const cbField = fields.find(f => f.type === 'checkbox');
    expect(cbField).toBeDefined();
    expect(cbField.label).toBe('Skills');
    expect(cbField.options).toHaveLength(2);
  });

  it('getExtraFields skips blocks without headings', () => {
    const block = document.createElement('div');
    block.setAttribute('data-params', 'test');
    const input = document.createElement('input');
    input.type = 'text';
    block.appendChild(input);
    document.body.appendChild(block);

    const fields = googleForms.getExtraFields(document);
    expect(fields).toHaveLength(0);
  });
});
