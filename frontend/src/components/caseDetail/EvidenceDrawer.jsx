// [10i] EvidenceDrawer — box 14: the record behind an evidence ID, in a panel on the right
// Opens when any EvidenceLink is clicked (state.evidence.openId). Closes with ✕,
// Esc, a click outside, or leaving the case page (CaseDetail closes it).
//
//   header:   [Claim]  EV-CLM-004410                                  ✕
//             Nov 3, 2026, 7:12 PM CST
//             Ingredient error on Orange Chicken with Extra sauce.
//   details:  one row per attribute, by evidence type
//   quote:    customer comments / merchant reply text — PLAIN TEXT, never HTML
//
// customer_comments and reply text are untrusted (contracts.md). React escapes
// text children, so "<b>Please fix</b>" shows as those characters. Never use
// dangerouslySetInnerHTML here.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useEffect, useRef } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { fetchEvidence } from '../../store/evidence/evidenceThunks';
import { closeEvidence } from '../../store/evidence/evidenceSlice';
import {
  selectOpenEvidenceId,
  selectEvidence,
  selectEvidenceStatus,
  selectEvidenceError,
} from '../../store/evidence/evidenceSelectors';
import Pill from '../common/Pill';
import {
  formatDateTime,
  formatMoney,
  labelOf,
  EVIDENCE_TYPE_LABELS,
  ERROR_CATEGORY_LABELS,
  REVIEW_LABEL_LABELS,
  CANCELLATION_CATEGORY_LABELS,
  EVENT_TYPE_LABELS,
  DAYPART_LABELS,
  REPLY_OUTCOME_LABELS,
} from '../../api/format';


// ═══════════════════════════════════════════════════════════════════
// 2. Rows per evidence type — [label, value] pairs, empty values dropped
// ═══════════════════════════════════════════════════════════════════
// The free text (customer comments, reply text, event description) is not a
// row: it shows below as a quote, so long text has room.
const itemText = (name, id) => (id ? `${name} (${id})` : name);

const rowsFor = (evidence, timeZone) => {
  const a = evidence.attributes ?? {};
  const time = (iso) => formatDateTime(iso, timeZone);

  switch (evidence.type) {
    case 'claim':
      return [
        ['Problem', labelOf(ERROR_CATEGORY_LABELS, a.error_category)],
        ['Item', itemText(a.item_name, a.item_id)],
        ['Modifier', a.modifier_detail],
        ['Order', a.order_id],
        ['Items in order', a.item_count],
        ['Daypart', labelOf(DAYPART_LABELS, a.daypart)],
        ['Charge', a.error_charge != null ? formatMoney(a.error_charge) : null],
        ['Reported', time(a.reported_at)],
        ['Review', a.reviewed_at
          ? `${labelOf(REVIEW_LABEL_LABELS, a.review_label)} · ${time(a.reviewed_at)}`
          : labelOf(REVIEW_LABEL_LABELS, a.review_label)],
        ['Customer', a.customer_ref],
      ];
    case 'cancellation':
      return [
        ['Reason', labelOf(CANCELLATION_CATEGORY_LABELS, a.cancellation_category)],
        ['Item', a.item_id],
        ['Order', a.order_id],
        ['Daypart', labelOf(DAYPART_LABELS, a.daypart)],
        ['Canceled', time(a.canceled_at)],
      ];
    case 'operational_event':
      return [
        ['Event', labelOf(EVENT_TYPE_LABELS, a.event_type)],
        ['Started', time(a.started_at)],
        ['Ended', a.ended_at ? time(a.ended_at) : 'Not ended'],
      ];
    case 'merchant_reply':
      return [
        ['Outcome', labelOf(REPLY_OUTCOME_LABELS, a.outcome)],
        ['Question', a.proposal_id],
        ['Recorded', time(a.recorded_at)],
      ];
    default:
      // A type this UI doesn't know yet: show every attribute as text
      return Object.entries(a).map(([key, value]) => [key, typeof value === 'object' ? JSON.stringify(value) : value]);
  }
};

// The free text to quote, with a line saying whose words they are
const quoteFor = (evidence) => {
  const a = evidence.attributes ?? {};
  if (evidence.type === 'claim' && a.customer_comments) {
    return { label: 'Customer comments · not verified', text: a.customer_comments };
  }
  if (evidence.type === 'merchant_reply' && a.text) {
    return { label: 'Merchant reply · not verified', text: a.text };
  }
  if (evidence.type === 'operational_event' && a.description) {
    return { label: 'Description', text: a.description };
  }
  return null;
};


// ═══════════════════════════════════════════════════════════════════
// 3. EvidenceDrawer component
// ═══════════════════════════════════════════════════════════════════
// timeZone: the case's store timezone (CaseDetail.store.timezone)
const EvidenceDrawer = ({ timeZone }) => {
  const dispatch = useDispatch();
  const openId = useSelector(selectOpenEvidenceId);
  const evidence = useSelector((state) => selectEvidence(state, openId));
  const status = useSelector((state) => selectEvidenceStatus(state, openId));
  const error = useSelector((state) => selectEvidenceError(state, openId));
  const closeRef = useRef(null);

  // ── 3a. Fetch the record when the drawer opens (skipped if cached) ──
  useEffect(() => {
    if (openId) dispatch(fetchEvidence(openId));
  }, [dispatch, openId]);

  // ── 3b. Esc closes · focus moves into the drawer, then back on close ──
  const isOpen = Boolean(openId);
  useEffect(() => {
    if (!isOpen) return undefined;
    const opener = document.activeElement;
    closeRef.current?.focus();
    const onKey = (e) => {
      if (e.key === 'Escape') dispatch(closeEvidence());
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      // Back to the evidence link that opened it, if it is still on the page
      if (opener instanceof HTMLElement && document.contains(opener)) opener.focus();
    };
  }, [dispatch, isOpen]);

  if (!openId) return null;

  // ── 3c. Body: loading · error + retry · the record ───────────────
  let body;
  if (status === 'failed') {
    body = (
      <div className='error' role='alert'>
        <p>{error}</p>
        <button type='button' onClick={() => dispatch(fetchEvidence(openId))}>Retry</button>
      </div>
    );
  } else if (!evidence) {
    body = <p className='muted'>Loading evidence…</p>;
  } else {
    const rows = rowsFor(evidence, timeZone).filter(([, value]) => value != null && value !== '');
    const quote = quoteFor(evidence);
    body = (
      <>
        <p className='muted'>{formatDateTime(evidence.occurred_at, timeZone)}</p>
        <p className='evidence-summary'>{evidence.summary}</p>
        <dl className='evidence-attrs'>
          {rows.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        {quote && (
          <figure className='evidence-quote'>
            <figcaption>{quote.label}</figcaption>
            {/* Plain text on purpose: untrusted customer / merchant words */}
            <blockquote>{quote.text}</blockquote>
          </figure>
        )}
      </>
    );
  }

  // ── 3d. Drawer + backdrop ────────────────────────────────────────
  return (
    <>
      <div className='drawer-backdrop' onClick={() => dispatch(closeEvidence())} aria-hidden='true' />
      <aside className='drawer' role='dialog' aria-modal='true' aria-labelledby='evidence-drawer-title'>
        <header className='drawer-head'>
          <div>
            {evidence && <Pill tone='accent'>{labelOf(EVIDENCE_TYPE_LABELS, evidence.type)}</Pill>}
            <h2 id='evidence-drawer-title'>{openId}</h2>
          </div>
          <button
            ref={closeRef}
            type='button'
            className='drawer-close'
            onClick={() => dispatch(closeEvidence())}
            aria-label='Close evidence'
          >
            ✕
          </button>
        </header>
        {body}
      </aside>
    </>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default EvidenceDrawer;
