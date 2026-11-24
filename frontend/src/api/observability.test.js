import { afterEach, describe, expect, it, vi } from 'vitest';
import { prepareRequest, recordResponse } from './observability';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('request correlation and private browser logs', () => {
  it('prepares login requests on HTTP pages without crypto.randomUUID', () => {
    const browserCrypto = globalThis.crypto;
    vi.stubGlobal('crypto', {
      getRandomValues: browserCrypto.getRandomValues.bind(browserCrypto),
    });

    const request = prepareRequest({ url: '/auth/login' });
    const requestId = request.headers['X-Request-ID'];
    expect(requestId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(prepareRequest(request).headers['X-Request-ID']).toBe(requestId);
    expect(prepareRequest({ url: '/auth/refresh' }).headers['X-Request-ID']).not.toBe(requestId);
  });

  it('creates an opaque ID, keeps it on retry, and captures case context', () => {
    const config = prepareRequest({ url: '/agent/investigations', data: { case_id: 'CASE-0001' } });
    const id = config.headers['X-Request-ID'];
    expect(id).toMatch(/^[a-f0-9-]{36}$/);
    expect(prepareRequest(config).headers['X-Request-ID']).toBe(id);
    expect(config.headers['X-Case-ID']).toBe('CASE-0001');
    expect(prepareRequest({ url: '/domain/cases/CASE-0002?secret=private' }).headers['X-Case-ID']).toBe('CASE-0002');
    expect(prepareRequest({ url: '/agent/investigations/INV-TEST/resume' }).headers['X-Investigation-ID']).toBe('INV-TEST');
  });

  it('logs correlation and timing, without URLs, bodies, headers or error messages', () => {
    const output = vi.spyOn(console, 'info').mockImplementation(() => {});
    const config = prepareRequest({ url: '/domain/cases/CASE-0001?email=jane@example.com',
      headers: { Authorization: 'Bearer private-token', 'X-Request-ID': 'browser-request' },
      data: { password: 'secret', customer_comments: 'Jane Doe' } });
    recordResponse(config, { status: 503, headers: { 'x-request-id': 'gateway-request' },
      data: { error: 'Jane Doe' } });
    const line = JSON.parse(output.mock.calls[0][0]);
    expect(line).toMatchObject({ service: 'frontend', request_id: 'gateway-request',
      case_id: 'CASE-0001', status_code: 503 });
    expect(line.duration_ms).toBeGreaterThanOrEqual(0);
    expect(output.mock.calls[0][0]).not.toMatch(/Jane|jane|Bearer|password|secret/);
  });

  it('replaces invalid IDs and reports network errors without private config', () => {
    const output = vi.spyOn(console, 'info').mockImplementation(() => {});
    const config = prepareRequest({ url: '/auth/login', headers: {
      'X-Request-ID': 'Jane Doe', 'X-Case-ID': 'Jane Doe', 'X-Investigation-ID': 'Jane Doe' } });
    recordResponse(config);
    expect(config.headers['X-Request-ID']).not.toBe('Jane Doe');
    expect(config.headers['X-Case-ID']).toBeUndefined();
    expect(config.headers['X-Investigation-ID']).toBeUndefined();
    expect(JSON.parse(output.mock.calls[0][0]).status_code).toBeNull();
    expect(output.mock.calls[0][0]).not.toContain('Jane');
  });
});
