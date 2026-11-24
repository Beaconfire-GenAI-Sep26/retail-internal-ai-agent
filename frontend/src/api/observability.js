// Log only correlation and transport facts. Never serialize Axios errors/configs,
// payloads, tokens, user identities or URLs (queries can contain private data).
import { newUuid } from '../utils/uuid';

const requestIdPattern = /^[A-Za-z0-9._-]{1,128}$/;
const caseIdPattern = /^CASE-\d{4,}$/;
const investigationIdPattern = /^INV-[A-Za-z0-9-]{1,64}$/;

export function prepareRequest(config) {
  config.headers ??= {};
  const existing = config.headers.get?.('X-Request-ID') ?? config.headers['X-Request-ID'];
  config.headers['X-Request-ID'] = requestIdPattern.test(existing ?? '')
    ? existing : newUuid();
  const path = (config.url ?? '').split('?')[0];
  const caseId = path.match(/\/cases\/(CASE-\d{4,})(?:\/|$)/)?.[1]
    ?? (typeof config.data === 'object' ? config.data?.case_id : null)
    ?? config.params?.case_id ?? config.headers['X-Case-ID'];
  const investigationId = path.match(/\/investigations\/(INV-[A-Za-z0-9-]{1,64})(?:\/|$)/)?.[1];
  if (caseIdPattern.test(caseId ?? '')) config.headers['X-Case-ID'] = caseId;
  else delete config.headers['X-Case-ID'];
  if (investigationIdPattern.test(investigationId ?? '')) config.headers['X-Investigation-ID'] = investigationId;
  else delete config.headers['X-Investigation-ID'];
  config._observability = { started: performance.now() };
  return config;
}

export function recordResponse(config, response) {
  if (!config?._observability) return;
  const echoed = response?.headers?.['x-request-id'];
  console.info(JSON.stringify({
    service: 'frontend', event: 'http.request',
    request_id: requestIdPattern.test(echoed ?? '') ? echoed : config.headers['X-Request-ID'],
    case_id: config.headers['X-Case-ID'] ?? null,
    investigation_id: config.headers['X-Investigation-ID'] ?? null,
    status_code: response?.status ?? null,
    duration_ms: Math.round(performance.now() - config._observability.started),
  }));
}
