// When Start refreshes the token first (ui-workflow.md v0.3 "Fresh token before Start")
import { describe, expect, it } from 'vitest';
import { needsRefresh, tokenExpiryMs } from './freshToken';

const NOW = Date.parse('2026-11-19T12:00:00Z');
const minutes = (n) => NOW + n * 60 * 1000;
// A JWT-shaped string with this payload (signature not checked: decode only)
const jwt = (payload) => `h.${btoa(JSON.stringify(payload)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_')}.s`;

describe('needsRefresh', () => {
  it('more than 25 min left → no refresh', () => {
    expect(needsRefresh(minutes(26), NOW)).toBe(false);
  });

  it('less than 25 min left → refresh first', () => {
    expect(needsRefresh(minutes(24), NOW)).toBe(true);
  });

  it('already expired, or unknown → refresh', () => {
    expect(needsRefresh(minutes(-1), NOW)).toBe(true);
    expect(needsRefresh(null, NOW)).toBe(true);
  });
});

describe('tokenExpiryMs', () => {
  it('uses auth.expiresAt when present', () => {
    expect(tokenExpiryMs('anything', '2026-11-19T13:00:00Z')).toBe(minutes(60));
  });

  it('falls back to the JWT exp', () => {
    expect(tokenExpiryMs(jwt({ sub: 'USR-001', exp: minutes(30) / 1000 }), null)).toBe(minutes(30));
  });

  it('not a JWT → unknown', () => {
    expect(tokenExpiryMs('mock.USR-001.123', null)).toBeNull();
    expect(tokenExpiryMs(null, null)).toBeNull();
  });
});
