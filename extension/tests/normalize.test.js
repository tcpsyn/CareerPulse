import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'fs';
import { join } from 'path';

// Load and execute the normalize IIFE
function loadNormalize() {
  window.__cpNormalize = undefined;
  const code = readFileSync(join(__dirname, '..', 'normalize.js'), 'utf-8');
  eval(code);
  return window.__cpNormalize;
}

let norm;

beforeEach(() => {
  norm = loadNormalize();
});

// ═══════════════════════════════════════════════════════════════
// State abbreviation normalization
// ═══════════════════════════════════════════════════════════════

describe('normalizeValue — US states', () => {
  it('normalizes abbreviation to full name', () => {
    expect(norm.normalizeValue('NM', norm.US_STATES)).toBe('new mexico');
  });

  it('normalizes full name to canonical', () => {
    expect(norm.normalizeValue('New Mexico', norm.US_STATES)).toBe('new mexico');
  });

  it('normalizes California abbreviation', () => {
    expect(norm.normalizeValue('CA', norm.US_STATES)).toBe('california');
  });

  it('normalizes DC', () => {
    expect(norm.normalizeValue('DC', norm.US_STATES)).toBe('district of columbia');
  });

  it('returns null for unknown value', () => {
    expect(norm.normalizeValue('ZZ', norm.US_STATES)).toBeNull();
  });

  it('returns null for null input', () => {
    expect(norm.normalizeValue(null, norm.US_STATES)).toBeNull();
  });

  it('returns null for empty string', () => {
    expect(norm.normalizeValue('', norm.US_STATES)).toBeNull();
  });
});

// ═══════════════════════════════════════════════════════════════
// areEquivalent — state abbreviations
// ═══════════════════════════════════════════════════════════════

describe('areEquivalent — US states', () => {
  it('NM equals New Mexico', () => {
    expect(norm.areEquivalent('NM', 'New Mexico')).toBe(true);
  });

  it('CA equals California', () => {
    expect(norm.areEquivalent('CA', 'California')).toBe(true);
  });

  it('DC equals District of Columbia', () => {
    expect(norm.areEquivalent('DC', 'District of Columbia')).toBe(true);
  });

  it('NY does not equal New Mexico', () => {
    expect(norm.areEquivalent('NY', 'New Mexico')).toBe(false);
  });

  it('handles case insensitivity', () => {
    expect(norm.areEquivalent('nm', 'NEW MEXICO')).toBe(true);
  });
});

// ═══════════════════════════════════════════════════════════════
// areEquivalent — countries
// ═══════════════════════════════════════════════════════════════

describe('areEquivalent — countries', () => {
  it('US equals United States of America', () => {
    expect(norm.areEquivalent('US', 'United States of America')).toBe(true);
  });

  it('USA equals United States', () => {
    expect(norm.areEquivalent('USA', 'United States')).toBe(true);
  });

  it('UK equals United Kingdom', () => {
    expect(norm.areEquivalent('UK', 'United Kingdom')).toBe(true);
  });

  it('AU equals Australia', () => {
    expect(norm.areEquivalent('AU', 'Australia')).toBe(true);
  });

  it('US does not equal Canada', () => {
    expect(norm.areEquivalent('US', 'Canada')).toBe(false);
  });
});

// ═══════════════════════════════════════════════════════════════
// areEquivalent — degrees
// ═══════════════════════════════════════════════════════════════

describe('areEquivalent — degrees', () => {
  it("B.S. equals Bachelor's", () => {
    expect(norm.areEquivalent('B.S.', "Bachelor's")).toBe(true);
  });

  it('MBA equals Master of Business Administration', () => {
    expect(norm.areEquivalent('MBA', 'Master of Business Administration')).toBe(true);
  });

  it('PhD equals Doctorate', () => {
    expect(norm.areEquivalent('PhD', 'Doctorate')).toBe(true);
  });

  it('JD equals Juris Doctor', () => {
    expect(norm.areEquivalent('JD', 'Juris Doctor')).toBe(true);
  });

  it("Bachelor's does not equal Master's", () => {
    expect(norm.areEquivalent("Bachelor's", "Master's")).toBe(false);
  });
});

// ═══════════════════════════════════════════════════════════════
// areEquivalent — boolean values
// ═══════════════════════════════════════════════════════════════

describe('areEquivalent — booleans', () => {
  it('yes equals true', () => {
    expect(norm.areEquivalent('yes', 'true')).toBe(true);
  });

  it('Y equals 1', () => {
    expect(norm.areEquivalent('Y', '1')).toBe(true);
  });

  it('no equals false', () => {
    expect(norm.areEquivalent('no', 'false')).toBe(true);
  });

  it('N equals 0', () => {
    expect(norm.areEquivalent('N', '0')).toBe(true);
  });

  it('yes does not equal no', () => {
    expect(norm.areEquivalent('yes', 'no')).toBe(false);
  });
});

// ═══════════════════════════════════════════════════════════════
// areEquivalent — EEO / race-ethnicity
// ═══════════════════════════════════════════════════════════════

describe('areEquivalent — EEO values', () => {
  it('Hispanic or Latino equals Hispanic/Latino', () => {
    expect(norm.areEquivalent('Hispanic or Latino', 'Hispanic/Latino')).toBe(true);
  });

  it('Black or African American equals African American', () => {
    expect(norm.areEquivalent('Black or African American', 'African American')).toBe(true);
  });

  it('Decline to self-identify equals I do not wish to self-identify (race)', () => {
    expect(norm.areEquivalent('Decline to self-identify', 'I do not wish to self-identify')).toBe(true);
  });
});

// ═══════════════════════════════════════════════════════════════
// areEquivalent — gender
// ═══════════════════════════════════════════════════════════════

describe('areEquivalent — gender', () => {
  it('Male equals M', () => {
    expect(norm.areEquivalent('Male', 'M')).toBe(true);
  });

  it('Female equals Woman', () => {
    expect(norm.areEquivalent('Female', 'Woman')).toBe(true);
  });

  it('Non-binary equals Nonbinary', () => {
    expect(norm.areEquivalent('Non-binary', 'Nonbinary')).toBe(true);
  });
});

// ═══════════════════════════════════════════════════════════════
// areEquivalent — disability and veteran
// ═══════════════════════════════════════════════════════════════

describe('areEquivalent — disability status', () => {
  it('Decline to self-identify equals I do not wish to answer', () => {
    expect(norm.areEquivalent('Decline to self-identify', 'I do not wish to answer')).toBe(true);
  });

  it('Yes matches "I have a disability"', () => {
    expect(norm.areEquivalent('Yes', 'I have a disability')).toBe(true);
  });
});

describe('areEquivalent — veteran status', () => {
  it('Protected veteran matches yes', () => {
    expect(norm.areEquivalent('I am a protected veteran', 'Yes')).toBe(true);
  });
});

// ═══════════════════════════════════════════════════════════════
// areEquivalent — null / edge cases
// ═══════════════════════════════════════════════════════════════

describe('areEquivalent — edge cases', () => {
  it('returns false for null inputs', () => {
    expect(norm.areEquivalent(null, 'test')).toBe(false);
    expect(norm.areEquivalent('test', null)).toBe(false);
    expect(norm.areEquivalent(null, null)).toBe(false);
  });

  it('returns true for identical strings', () => {
    expect(norm.areEquivalent('hello', 'hello')).toBe(true);
  });

  it('handles whitespace', () => {
    expect(norm.areEquivalent('  CA  ', 'California')).toBe(true);
  });
});

// ═══════════════════════════════════════════════════════════════
// Phone normalization
// ═══════════════════════════════════════════════════════════════

describe('normalizePhone', () => {
  it('strips formatting from phone number', () => {
    expect(norm.normalizePhone('(555) 123-4567')).toBe('5551234567');
  });

  it('strips dots from phone number', () => {
    expect(norm.normalizePhone('555.123.4567')).toBe('5551234567');
  });

  it('strips country code prefix', () => {
    expect(norm.normalizePhone('+1 555-123-4567')).toBe('15551234567');
  });

  it('returns empty string for null', () => {
    expect(norm.normalizePhone(null)).toBe('');
  });

  it('returns digits from mixed content', () => {
    expect(norm.normalizePhone('call me at 555-1234')).toBe('5551234');
  });
});

// ═══════════════════════════════════════════════════════════════
// Phone formatting
// ═══════════════════════════════════════════════════════════════

describe('formatPhoneLike', () => {
  it('formats with parenthesized area code hint', () => {
    expect(norm.formatPhoneLike('5551234567', '(___) ___-____')).toBe('(555) 123-4567');
  });

  it('formats with dash-separated hint', () => {
    expect(norm.formatPhoneLike('5551234567', 'XXX-XXX-XXXX')).toBe('555-123-4567');
  });

  it('formats with dot-separated hint', () => {
    expect(norm.formatPhoneLike('5551234567', '000.000.0000')).toBe('555.123.4567');
  });

  it('defaults to US format for 10 digits without hint', () => {
    expect(norm.formatPhoneLike('5551234567', null)).toBe('(555) 123-4567');
  });

  it('handles 11-digit number with country code', () => {
    expect(norm.formatPhoneLike('15551234567', null)).toBe('+1 (555) 123-4567');
  });

  it('returns empty string for empty input', () => {
    expect(norm.formatPhoneLike('', null)).toBe('');
  });
});

// ═══════════════════════════════════════════════════════════════
// Field category detection
// ═══════════════════════════════════════════════════════════════

describe('detectFieldCategory', () => {
  it('detects state fields include US_STATES table', () => {
    const tables = norm.detectFieldCategory(['state']);
    expect(tables).toContain(norm.US_STATES);
  });

  it('detects state fields include CA_PROVINCES table', () => {
    const tables = norm.detectFieldCategory(['state']);
    expect(tables).toContain(norm.CA_PROVINCES);
  });

  it('detects country fields include COUNTRIES table', () => {
    const tables = norm.detectFieldCategory(['country']);
    expect(tables).toContain(norm.COUNTRIES);
  });

  it('detects degree fields include DEGREES table', () => {
    const tables = norm.detectFieldCategory(['degree level']);
    expect(tables).toContain(norm.DEGREES);
  });

  it('detects gender fields', () => {
    const tables = norm.detectFieldCategory(['gender']);
    expect(tables).toContain(norm.GENDER);
  });

  it('detects race/ethnicity fields', () => {
    const tables = norm.detectFieldCategory(['race or ethnicity']);
    expect(tables).toContain(norm.RACE_ETHNICITY);
  });

  it('detects disability fields', () => {
    const tables = norm.detectFieldCategory(['disability status']);
    expect(tables).toContain(norm.DISABILITY_STATUS);
  });

  it('detects veteran fields', () => {
    const tables = norm.detectFieldCategory(['veteran status']);
    expect(tables).toContain(norm.VETERAN_STATUS);
  });

  it('detects sponsorship fields', () => {
    const tables = norm.detectFieldCategory(['sponsorship required']);
    expect(tables).toContain(norm.SPONSORSHIP);
  });

  it('returns empty array for unrecognized field', () => {
    const tables = norm.detectFieldCategory({ label: 'favorite color' });
    expect(tables).toHaveLength(0);
  });

  it('returns empty array for null input', () => {
    const tables = norm.detectFieldCategory(null);
    expect(tables).toHaveLength(0);
  });

  it('handles string input', () => {
    const tables = norm.detectFieldCategory('country');
    expect(tables).toContain(norm.COUNTRIES);
  });
});

// ═══════════════════════════════════════════════════════════════
// normalizedMatch
// ═══════════════════════════════════════════════════════════════

describe('normalizedMatch', () => {
  it('matches "New Mexico" against options containing "NM"', () => {
    const options = ['CA', 'NM', 'NY'];
    const idx = norm.normalizedMatch(options, 'New Mexico', [norm.US_STATES]);
    expect(idx).toBe(1);
  });

  it('matches "NM" against options containing "New Mexico"', () => {
    const options = ['California', 'New Mexico', 'New York'];
    const idx = norm.normalizedMatch(options, 'NM', [norm.US_STATES]);
    expect(idx).toBe(1);
  });

  it('matches boolean "yes" against "true"', () => {
    const options = ['true', 'false'];
    const idx = norm.normalizedMatch(options, 'yes', [norm.BOOLEAN_YES_NO]);
    expect(idx).toBe(0);
  });

  it('matches boolean "no" against "false"', () => {
    const options = ['true', 'false'];
    const idx = norm.normalizedMatch(options, 'no', [norm.BOOLEAN_YES_NO]);
    expect(idx).toBe(1);
  });

  it('matches "US" against "United States of America"', () => {
    const options = ['Canada', 'United States of America', 'Mexico'];
    const idx = norm.normalizedMatch(options, 'US', [norm.COUNTRIES]);
    expect(idx).toBe(1);
  });

  it('matches "PhD" against "Doctorate"', () => {
    const options = ["Bachelor's", "Master's", 'Doctorate'];
    const idx = norm.normalizedMatch(options, 'PhD', [norm.DEGREES]);
    expect(idx).toBe(2);
  });

  it('returns -1 for no match', () => {
    const options = ['CA', 'NM', 'NY'];
    const idx = norm.normalizedMatch(options, 'France', [norm.US_STATES]);
    expect(idx).toBe(-1);
  });

  it('returns -1 for empty options', () => {
    expect(norm.normalizedMatch([], 'test')).toBe(-1);
  });

  it('returns -1 for null target', () => {
    expect(norm.normalizedMatch(['a', 'b'], null)).toBe(-1);
  });

  it('uses all tables when none specified', () => {
    const options = ['New Mexico', 'California'];
    const idx = norm.normalizedMatch(options, 'NM');
    expect(idx).toBe(0);
  });

  it('matches via substring containment as fallback', () => {
    const options = ['Bachelor of Science in Computer Science', 'Master of Arts'];
    const idx = norm.normalizedMatch(options, 'bachelor', [norm.DEGREES]);
    expect(idx).toBe(0);
  });
});

// ═══════════════════════════════════════════════════════════════
// Canadian provinces
// ═══════════════════════════════════════════════════════════════

describe('areEquivalent — Canadian provinces', () => {
  it('BC equals British Columbia', () => {
    expect(norm.areEquivalent('BC', 'British Columbia')).toBe(true);
  });

  it('ON equals Ontario', () => {
    expect(norm.areEquivalent('ON', 'Ontario')).toBe(true);
  });
});

// ═══════════════════════════════════════════════════════════════
// Work authorization and sponsorship
// ═══════════════════════════════════════════════════════════════

describe('areEquivalent — work authorization', () => {
  it('Authorized matches Yes', () => {
    expect(norm.areEquivalent('Authorized', 'Yes')).toBe(true);
  });

  it('Green Card matches Permanent Resident', () => {
    expect(norm.areEquivalent('Green Card', 'Permanent Resident')).toBe(true);
  });
});

describe('areEquivalent — sponsorship', () => {
  it('Yes matches "Will require sponsorship"', () => {
    expect(norm.areEquivalent('Yes', 'Will require sponsorship')).toBe(true);
  });

  it('No matches "Do not require sponsorship"', () => {
    expect(norm.areEquivalent('No', 'Do not require sponsorship')).toBe(true);
  });
});
