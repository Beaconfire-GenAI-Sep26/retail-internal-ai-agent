# Contracts

v0.4 draft, Thu Nov 19, 2026. IDs, enums, shared DTOs, endpoint payloads and errors for Auth, Agent and
Domain. Service boundaries are in [architecture.md](architecture.md). The investigation design is in
[agent-graph.md](agent-graph.md). Domain data names and rules follow C-01.

## Conventions

- **C-01 names are used exactly.** Every ID format, enum name, enum value, table name and column name defined in C-01 appears here as C-01 writes it, for example `daypart`, `error_category`, `evidence_id` and `EV-CLM-000123`.
- **Enum names and values are lowercase `snake_case`.** Enums that B-01 adds follow the same style. DTO interface names are `PascalCase`.
- **Filter and target fields are named after the C-01 column they match**, and take a list. For example, `daypart: ["dinner"]` matches `orders.daypart`. Other lists of IDs use a plural `_ids` name, such as `evidence_ids`.
- **JSON with `snake_case` fields.** Timestamps are stored in UTC (`timestamptz`) and sent as ISO 8601, for example `2026-11-03T23:10:00Z`. Dates are `YYYY-MM-DD`.
- **Paths are service-relative.** Through the gateway, prefix them with `/auth`, `/agent` or `/domain`. Routes under `/internal/` exist only on the Docker network.
- **`daypart`** is computed from the order's local time in the store's `timezone`, with the same boundaries for every store: `breakfast` 05:00–10:59, `lunch` 11:00–15:59, `dinner` 16:00–20:59, and `late_night` 21:00–04:59. It is a meal period, not a staff shift. Linking a daypart pattern to a crew needs the merchant's reply.
- **Days are store-local dates.** Every date that groups or filters orders is the date of the order's `placed_at` in the store's `timezone`. That covers `group_by: "day"`, `daily_claim_rate`, `CaseDetail.daily_rates`, `weekday`, and the `start`, `end` and `split_date` filters. A claim or cancellation counts on its order's date, not on `reported_at` or `canceled_at`. Events use the local date of `started_at`.
- **Order size** is `orders.item_count`, the proxy for multi-bag orders. Grouped results bucket it as `item_count_bucket`: `1-2`, `3-4` or `5+`.
- **Rates are decimals from 0 to 1**, always sent with their numerator and denominator. A rate that can't be supported is `null`, never `0`. Whether a whole result has enough data is defined in [When a result has enough data](#when-a-result-has-enough-data).
- **Missing values are `null`**, not omitted.
- **The investigation window** runs for the 42 days ending on the store-local date of the case's `window_end`, clipped to the start of the store's data. `window_end` may be sent as a UTC timestamp or a date; a timestamp at exactly local midnight ends the window on the day before. `opened_at` is when the monitor ran, which can fall after the store's data ends, so it doesn't anchor the window. A request may give its own dates.
- **Money** is in USD, stored as `numeric(10,2)` and sent as a number.
- **Small lists are not paginated.** Lists return at most 200 items.

### Rate rules

These match C-01 and apply to every Domain number:

| Term                                             | Definition                                                                                                                                                 |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Eligible orders                                  | Orders of the store in the window with `orders.status = "delivered"`. Orders with `status = "canceled"` are excluded because they can't have an M&I claim. |
| Store-attributable claims                        | `mi_claims` rows with `review_label` of `store_fault` or `pending`. Rows labeled `fraud` or `not_store_fault` are disqualified.                            |
| M&I rate                                         | Store-attributable claims divided by eligible orders                                                                                                       |
| Group rate by `item_id`                          | Attributable claims with that `item_id`, divided by eligible orders with an `order_items` row for that item                                                |
| Group rate by modifier                           | Attributable claims whose `modifier_detail` is that modifier, divided by eligible orders whose `order_items.modifiers` contain it                          |
| Group rate by `daypart`, weekday or `item_count` | Attributable claims in the group, divided by eligible orders in the group                                                                                  |
| Cancellation rate                                | `cancellations` rows divided by all placed orders, delivered and canceled                                                                                  |
| Insufficient data                                | A group with fewer than `MIN_GROUP_ORDERS` eligible orders returns `value: null`                                                                           |

When claims are grouped by `item_id`, rows with a null `item_id` fall into the group `item_id=unknown`.
When claims are grouped by `modifier`, claims with a null `modifier_detail` form no group and are left out of
`evidence_ids`. They still count in the filter's totals, so `claim_share` is taken over all attributable claims and
lift (see [Evidence ID ordering](#evidence-id-ordering)) stays the group's rate divided by the filter's rate. A note
gives their count, for example `"435 of 557 claims have no modifier_detail"`.
Pending claims are counted, and every `ToolResult` reports how many of its claims are still pending.

### When a result has enough data

`ToolResult.data_sufficient` describes the whole result. A single group below `MIN_GROUP_ORDERS` gets
`value: null` but doesn't by itself make the result insufficient.

| Tool | `data_sufficient` is true when |
|---|---|
| `compare_periods` | The target's after period and both control periods each have at least `MIN_GROUP_ORDERS` eligible orders. An empty target before period returns `rate_before: null` with a note. |
| `claim_breakdown`, `cancellation_breakdown` | The filter has at least `MIN_GROUP_ORDERS` eligible orders, or placed orders for cancellations |
| `store_overview`, `fraud_signals` | The window has at least `MIN_GROUP_ORDERS` eligible orders |
| `event_log`, `sample_evidence` | Always true. They return records, not rates. |

## Headers

| Header                        | Sent by         | Required                                                | Meaning                                                                        |
| ----------------------------- | --------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `Authorization: Bearer <jwt>` | frontend, agent | Every route except login and health                     | User identity. The agent forwards the user's token unchanged.                  |
| `X-Request-ID`                | gateway, agent  | Set by the gateway if absent                            | Correlates logs and traces. Every response echoes it.                          |
| `X-Investigation-ID`          | agent           | On agent-to-Domain calls                                | Links Domain logs and audit to the investigation                               |
| `X-Service-Token`             | agent           | On `/internal/` routes                                  | Must equal `INTERNAL_SERVICE_TOKEN`                                            |
| `Idempotency-Key`             | frontend        | On decision, reply, resume, monitor run and recheck run | A UUID per user action. A repeat returns the first result and changes nothing. |

## IDs

Readable strings with an uppercase type prefix, so a person or the agent can tell what an ID points to.
Seed data uses stable IDs from `SEED = 24`.

| Thing                        | Format and example                                   | Field                                   | Issued by      | Source                         |
| ---------------------------- | ---------------------------------------------------- | --------------------------------------- | -------------- | ------------------------------ |
| Store                        | `STORE-<letter>`, `STORE-A`                          | `store_id`                              | domain seed    | C-01                           |
| Menu item                    | `ITEM-<store>-<nnn>`, `ITEM-A-007`                   | `item_id`                               | domain seed    | C-01                           |
| Order                        | `ORD-<6 digits>`, `ORD-000123`                       | `order_id`                              | domain seed    | C-01                           |
| M&I claim (evidence)         | `EV-CLM-<6 digits>`, `EV-CLM-000123`                 | `evidence_id`                           | domain seed    | C-01                           |
| Cancellation (evidence)      | `EV-CXL-<6 digits>`, `EV-CXL-000045`                 | `evidence_id`                           | domain seed    | C-01                           |
| Operational event (evidence) | `EV-EVT-<6 digits>`, `EV-EVT-000010`                 | `evidence_id`                           | domain seed    | C-01                           |
| Case                         | `CASE-<4 digits>`, `CASE-0001`                       | `case_id`                               | domain         | C-01                           |
| Golden scenario (hidden)     | `GS-<2 digits>`, `GS-01`                             | `scenario_id`                           | eval only      | C-01. Never sent to the agent. |
| Merchant reply (evidence)    | `EV-RPL-<6 digits>`, `EV-RPL-000001`                 | `evidence_id`                           | domain         | B-01, for C-04                 |
| Proposal                     | `PROP-<4 digits>`, `PROP-0001`                       | `proposal_id`                           | domain         | B-01                           |
| Dispatch, recheck, audit     | `DSP-<6 digits>`, `RCK-<4 digits>`, `AUD-<6 digits>` | `dispatch_id`, `recheck_id`, `audit_id` | domain         | B-01                           |
| User                         | `USR-<3 digits>`, `USR-001`                          | `user_id`                               | auth           | B-01                           |
| Investigation                | `INV-<ULID>`, `INV-01JD3K9Q8F2M`                     | `investigation_id`                      | agent          | B-01                           |
| Check, hypothesis            | `CHK-<ULID>`, `HYP-<ULID>`                           | `check_id`, `hypothesis_id`             | agent          | B-01                           |
| Catalog action               | snake case, `fix_modifier_mapping`                   | `action_id`                             | domain catalog | B-01                           |

A claim's `evidence_id` is its primary key, so a claim has no separate claim ID. Modifiers have no IDs
and are referenced by their menu name, as in `menu_items.available_modifiers`, `order_items.modifiers`
and `mi_claims.modifier_detail`.

## Enums

```ts
// From C-01: names and values exactly as C-01 defines them.
type error_category =
  | "missing_item"
  | "incorrect_item"
  | "ingredient_error"
  | "wrong_order";
type review_label = "store_fault" | "not_store_fault" | "fraud" | "pending";
type cancellation_category =
  | "item_out_of_stock"
  | "too_busy"
  | "menu_data_mismatch"
  | "pos_technical_error"
  | "other";
type daypart = "breakfast" | "lunch" | "dinner" | "late_night";
type event_type = "menu_change" | "pos_change" | "store_downtime" | "promotion";
// C-01 orders.status takes "delivered" or "canceled".

// Named after C-01's case_status. C-01 currently gives it the six investigation_status
// values. These business values are proposed instead; see "Status model".
type case_status =
  | "open"
  | "investigating"
  | "awaiting_decision"
  | "awaiting_merchant"
  | "action_dispatched"
  | "closed"
  | "paused"
  | "reopened"
  | "analyst_review";

// Named after C-01's eval.golden_scenarios.cause_category, so labels compare directly.
type cause_category =
  | "pos_modifier_mapping"
  | "menu_change"
  | "packing"
  | "inventory"
  | "dasher_handoff"
  | "fraud_cluster"
  | "other";

// Defined by B-01.
type role = "viewer" | "loe_analyst";
type investigation_status =
  | "running"
  | "awaiting_approval"
  | "awaiting_merchant"
  | "completed"
  | "unsure"
  | "failed";
type evidence_type =
  | "claim"
  | "cancellation"
  | "operational_event"
  | "merchant_reply";
type item_count_bucket = "1-2" | "3-4" | "5+";
type proposal_kind = "merchant_question" | "intervention" | "handoff";
type proposal_status = "pending" | "approved" | "rejected";
type dispatch_status = "dispatched" | "failed";
type recheck_status =
  | "scheduled"
  | "improved"
  | "not_improved"
  | "insufficient_data";
type hypothesis_status = "open" | "supported" | "ruled_out" | "inconclusive";
type confidence = "low" | "medium" | "high";
type check_kind = "explore" | "test" | "challenge";
type owner_team =
  | "merchant"
  | "pos_team"
  | "menu_team"
  | "dasher_ops"
  | "fraud_review"
  | "analyst";
type tool_name =
  | "store_overview"
  | "event_log"
  | "claim_breakdown"
  | "compare_periods"
  | "sample_evidence"
  | "cancellation_breakdown"
  | "fraud_signals"
  | "merchant_replies"
  | "action_catalog";
```

`dasher_handoff` stays a valid `cause_category`, but C-01 has no Dasher data. Platform data can't test
it, so it is settled through a merchant question or left inconclusive. See [agent-graph.md](agent-graph.md).

## Status model

Two kinds of status are tracked separately, as the sprint plan requires. The agent owns
`investigation_status`. The Domain Service owns `case_status` and the proposal, dispatch and recheck
statuses.

**Needs a C-01 change.** C-01 defines `case_status` with the six `investigation_status` values. Those
values describe one investigation. A case exists before any investigation starts, and a reopened case
has two investigations, so `case_status` needs the business values above. The enum name and the
`cases.status` column stay as C-01 defines them, and only the values change. The `cases` table is still
empty, so the change is cheapest before C-02 starts filling it.

| `investigation_status` | Meaning                                                                       |
| ---------------------- | ----------------------------------------------------------------------------- |
| `running`              | The graph is working                                                          |
| `awaiting_approval`    | Paused until an analyst decides a merchant question                           |
| `awaiting_merchant`    | Paused until a reply or `no_reply` is recorded                                |
| `completed`            | A supported diagnosis was returned. Its recommendation is a pending proposal. |
| `unsure`               | The evidence can't support a cause. Checks tried and gaps are listed.         |
| `failed`               | Operational error. `error` explains it, and the analyst may start again.      |

Domain sets `cases.status`, a `case_status`, from these events:

| Event                                             | `case_status`                 |
| ------------------------------------------------- | ----------------------------- |
| Monitor opens the case                            | `open`                        |
| Investigation reports `running`                   | `investigating`               |
| Merchant question proposed, pending decision      | `awaiting_decision`           |
| Question approved and dispatched                  | `awaiting_merchant`           |
| Question rejected, so the investigation continues | `investigating`               |
| Investigation `completed`, recommendation pending | `awaiting_decision`           |
| Investigation `unsure`                            | `analyst_review`              |
| Investigation `failed`                            | `open`, with `last_error` set |
| Recommendation rejected                           | `analyst_review`              |
| Recommendation approved and dispatched            | `action_dispatched`           |
| Recheck `improved`                                | `closed`                      |
| Recheck `insufficient_data`                       | `paused`                      |
| Recheck `not_improved`, first time                | `reopened`                    |
| Recheck `not_improved`, second time               | `analyst_review`              |

## Shared DTOs

### Auth

```ts
interface LoginRequest {
  username: string;
  password: string;
}

interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  expires_at: string;
  user: User;
}

interface User {
  user_id: string; // USR-001
  display_name: string;
  role: role;
  store_ids: string[]; // ["STORE-A", "STORE-B"]
}
```

### Stores, cases and evidence

```ts
interface StoreSummary {
  // columns of C-01 stores
  store_id: string;
  name: string;
  city: string;
  timezone: string; // IANA name, e.g. "America/New_York"
  cuisine: string;
}

interface MenuItem {
  // columns of C-01 menu_items
  item_id: string; // ITEM-A-007
  store_id: string;
  name: string;
  category: string;
  price: number; // USD, numeric(10,2)
  available_modifiers: string[]; // modifier names, e.g. ["Extra sauce"]
}

interface CaseSummary {
  // columns of C-01 cases, plus the marked additions
  case_id: string; // CASE-0001
  store_id: string;
  store_name: string; // stores.name
  status: case_status;
  trigger_rule: "over_goal" | "spike_vs_baseline"; // values owned by C-02
  window_start: string; // the 7-day trigger window
  window_end: string;
  mi_rate: number;
  baseline_rate: number;
  eligible_orders: number;
  attributable_claims: number; // addition: numerator of mi_rate
  goal_rate: number; // addition: MONITOR_GOAL_RATE at open time
  opened_at: string;
  updated_at: string;
  active_investigation_id: string | null; // addition, C-02/C-03
  reopen_count: 0 | 1; // addition, C-04
  last_error: string | null; // addition
}

interface CaseDetail extends CaseSummary {
  store: StoreSummary;
  daily_rates: {
    date: string;
    rate: number | null;
    claims: number;
    eligible_orders: number;
  }[];
  investigation_ids: string[]; // newest first
  proposals: Proposal[];
  rechecks: Recheck[];
}

interface Evidence {
  evidence_id: string; // EV-CLM-, EV-CXL-, EV-EVT- or EV-RPL-
  type: evidence_type;
  store_id: string;
  occurred_at: string; // copy of reported_at, canceled_at, started_at or recorded_at
  summary: string; // one line written by Domain
  attributes:
    | ClaimAttributes
    | CancellationAttributes
    | EventAttributes
    | ReplyAttributes;
}

interface ClaimAttributes {
  // C-01 mi_claims, plus three columns joined from orders
  order_id: string;
  item_id: string | null;
  item_name: string;
  error_category: error_category;
  modifier_detail: string | null;
  customer_comments: string | null; // untrusted customer text
  error_charge: number;
  reported_at: string;
  review_label: review_label;
  reviewed_at: string | null; // null while pending
  daypart: daypart; // from orders
  item_count: number; // from orders
  customer_ref: string; // from orders; synthetic, never a name or address
}

interface CancellationAttributes {
  // C-01 cancellations, plus daypart from orders
  order_id: string;
  item_id: string | null; // the out-of-stock item, when known
  cancellation_category: cancellation_category;
  canceled_at: string;
  daypart: daypart;
}

interface EventAttributes {
  // C-01 operational_events
  event_type: event_type;
  started_at: string;
  ended_at: string | null;
  description: string; // free text; the only link from an event to items
}

interface ReplyAttributes {
  // C-04 merchant replies
  proposal_id: string;
  outcome: "replied" | "no_reply";
  text: string | null; // untrusted merchant text
  recorded_at: string;
}

interface EvidenceResolveRequest {
  store_id: string;
  evidence_ids: string[];
}
interface EvidenceResolveResponse {
  valid: string[];
  invalid: { evidence_id: string; reason: "not_found" | "other_store" }[];
}
```

`customer_comments` and reply `text` are untrusted. They are passed to the model as quoted data, never
as instructions.

### Diagnostics, Agent-to-Domain reads

```ts
interface ClaimFilter {
  start: string; // date
  end: string; // date, inclusive
  item_id?: string[];
  modifiers?: string[]; // menu names, e.g. ["Extra sauce"]
  daypart?: daypart[];
  weekday?: number[]; // 0 = Monday, store local time
  item_count_min?: number;
  item_count_max?: number;
  error_category?: error_category[];
  review_label?: review_label[]; // default ["store_fault", "pending"]
}

type ClaimScope = Omit<ClaimFilter, "start" | "end">;

interface CancellationFilter {
  start: string;
  end: string;
  item_id?: string[];
  daypart?: daypart[];
  weekday?: number[];
  cancellation_category?: cancellation_category[];
}

interface ClaimBreakdownRequest {
  filter: ClaimFilter;
  group_by:
    | "item_id"
    | "modifier"
    | "daypart"
    | "weekday"
    | "item_count"
    | "error_category"
    | "review_label"
    | "day";
}

interface ComparePeriodsRequest {
  split_date: string; // first day of the "after" period
  days_before: number; // 1 to 28
  days_after: number; // 1 to 28
  target: ClaimScope;
  control: ClaimScope | null; // null: the same store, every order outside the target
}

interface EvidenceSampleRequest {
  evidence_type: "claim" | "cancellation";
  filter: ClaimFilter | CancellationFilter; // matching evidence_type
  limit: number; // 1 to 10
}

interface CancellationBreakdownRequest {
  filter: CancellationFilter;
  group_by: "cancellation_category" | "item_id" | "daypart" | "weekday" | "day";
}

interface ToolResult {
  tool: tool_name;
  store_id: string;
  window: { start: string; end: string };
  eligible_orders: number;
  pending_claims: number; // pending claims inside the counted claims
  data_sufficient: boolean; // see "When a result has enough data"
  headline: string; // deterministic one-line finding, written by Domain
  metrics: Metric[];
  evidence_ids: string[]; // every record behind the metrics; ordered as in "Evidence ID ordering" below
  evidence: Evidence[]; // filled only by sample_evidence and event_log
  notes: string[]; // e.g. "3 claims excluded: review_label fraud"
}

interface Metric {
  name: string; // one of the names in "Metric names" below
  group: string | null; // "modifier=Extra sauce", "daypart=dinner", "item_count=5+", "item_id=ITEM-A-007", "target", "control"
  value: number | null;
  numerator: number | null;
  denominator: number | null;
  unit: "rate" | "share" | "count";
}

interface ActionCatalogEntry {
  action_id: string;
  kind: "intervention" | "handoff";
  owner_team: owner_team;
  title: string;
  applies_to: cause_category[];
  default_recheck_days: number;
}
```

Grouping by `modifier` uses `mi_claims.modifier_detail` for claims and `order_items.modifiers` for the
order denominator. Grouping by `item_count` returns `item_count_bucket` groups.

### Evidence ID ordering

A check can return hundreds of evidence IDs, and the agent shows the model only the first 20. So the
Domain Service returns `ToolResult.evidence_ids` sorted with the most useful records first. The sort
uses only the numbers of the query itself, and the Domain Service never knows the agent's hypotheses.
The same query always returns the same order.

Every list is sorted by these keys, in order:

1. **Groups with enough data first.** Records from groups with at least `MIN_GROUP_ORDERS` eligible orders come before records from smaller groups. A tiny group can show a huge lift by chance, and this keeps it from filling the top of the list.
2. **Group statistic, highest first.** Groups are ranked by the tool's own statistic in the table below.
3. **Time.** Within a group, records are sorted by their timestamp, newest first. `event_log` is the exception and lists oldest first.
4. **`evidence_id`, ascending,** to break any remaining tie.

Results without groups skip steps 1 and 2.

| Tool | Group statistic, step 2 | Timestamp, step 3 |
|---|---|---|
| `store_overview` | No groups | `reported_at`, newest first |
| `claim_breakdown` | Lift: `claim_share` divided by `order_share` | `reported_at`, newest first |
| `compare_periods` | Fixed order: the `target` after `split_date`, then the `target` before it, then the `control` | `reported_at`, newest first |
| `cancellation_breakdown` | `cancellation_rate` | `canceled_at`, newest first |
| `fraud_signals` | `claim_count` per flagged `customer_ref` | `reported_at`, newest first |
| `event_log` | No groups | `started_at`, oldest first |
| `sample_evidence` | No groups | `reported_at` or `canceled_at`, newest first, at most `limit` records |

**Lift** is a group's share of claims divided by its share of orders. A lift above 1 means the group has
more than its fair share of claims.

**Example**, with illustrative numbers. STORE-A runs `claim_breakdown` grouped by `modifier`.
`Extra sauce` appears on 6% of eligible orders but carries 41% of attributable claims, a lift of about 6.8.
That is the highest of any group with enough orders, so its claims come first, newest first. The first
20 IDs the model sees are `Extra sauce` claims, which are the ones it needs to cite.

### Metric names

Every `Metric` uses one of these names, so the agent's prompt can rely on them. A rate is `null` when
its group has fewer than `MIN_GROUP_ORDERS` eligible orders.

| Tool | Metric `name` | `group` | `unit` | Meaning |
|---|---|---|---|---|
| `store_overview` | `claim_rate` | `null` | `rate` | Attributable claims divided by eligible orders in the window |
| `store_overview` | `claim_count` | `review_label=<value>`, all four labels | `count` | Claims per label, including the excluded `fraud` and `not_store_fault` claims |
| `store_overview` | `claim_count` | `error_category=<value>` | `count` | Attributable claims per error category |
| `store_overview` | `daily_claim_rate` | `day=<YYYY-MM-DD>` | `rate` | The rate for each day in the window |
| `claim_breakdown` | `claim_rate` | `<group_by>=<value>`, such as `modifier=Extra sauce` | `rate` | The group's attributable claims divided by its eligible orders |
| `claim_breakdown` | `claim_share` | same | `share` | The group's share of all attributable claims in the filter |
| `claim_breakdown` | `order_share` | same | `share` | The group's share of all eligible orders in the filter |
| `compare_periods` | `rate_before`, `rate_after` | `target` or `control` | `rate` | The rate in the period before and after `split_date` |
| `cancellation_breakdown` | `cancellation_rate` | `<group_by>=<value>` | `rate` | The group's cancellations divided by its placed orders |
| `cancellation_breakdown` | `cancellation_count` | same | `count` | The group's cancellations |
| `fraud_signals` | `claim_count` | `customer_ref=<ref>`, flagged refs only | `count` | Pending claims from one `customer_ref`. A ref is flagged only when it has at least `FRAUD_MIN_PENDING_CLAIMS` (default 4) pending claims in the window |

`event_log` and `sample_evidence` return no metrics. Their records come in `ToolResult.evidence`.

### Investigations, UI-facing

```ts
interface StartInvestigationRequest {
  case_id: string;
  reopen_of: string | null;
}

interface InvestigationView {
  investigation_id: string;
  case_id: string;
  store_id: string;
  status: investigation_status;
  started_by: string;
  started_at: string;
  updated_at: string;
  step_count: number;
  max_steps: number;
  reopen_of: string | null;
  hypotheses: Hypothesis[];
  checks: CheckSummary[]; // oldest first
  pending_proposal_id: string | null;
  result: InvestigationResult | null;
  error: { code: string; message: string } | null;
}

interface Hypothesis {
  hypothesis_id: string;
  cause_category: cause_category;
  statement: string; // specific when cause_category is "other"
  status: hypothesis_status;
  rationale: string;
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  check_ids: string[];
}

interface Expectation {
  hypothesis_id: string;
  if_true: string;
  if_false: string;
}

interface CheckSummary {
  check_id: string;
  kind: check_kind;
  tool: tool_name;
  purpose: string;
  discriminates: string[]; // hypothesis IDs
  expectations: Expectation[];
  challenges: string | null; // hypothesis ID for a challenge check
  matched: Record<string, "if_true" | "if_false" | "neither">;
  headline: string;
  data_sufficient: boolean;
  evidence_ids: string[];
  at: string;
}

interface Target {
  // fields named after the C-01 columns they match
  item_id: string[];
  modifiers: string[];
  daypart: daypart[];
  item_count_min: number | null;
}

interface InvestigationResult {
  outcome: "diagnosis" | "unsure";
  cause_category: cause_category | null;
  cause_started_at: string | null; // date the agent estimates the rise began
  confidence: confidence;
  summary: string;
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  ruled_out: {
    cause_category: cause_category;
    reason: string;
    evidence_ids: string[];
    check_ids: string[];
  }[];
  evidence_gaps: string[];
  checks_tried: string[];
  challenge_check_ids: string[];
  unverified_reply_claims: string[];
  recommendation: Recommendation | null;
  proposal_id: string | null;
}

interface Recommendation {
  kind: "intervention" | "handoff";
  action_id: string;
  owner_team: owner_team;
  rationale: string;
  target: Target;
  recheck_after_days: number;
}
```

A ruling can cite a check rather than records. A flat result, such as lunch orders showing no rise, has
no claim rows behind it, so `check_ids` carries the proof.

### Proposals, decisions, replies and rechecks

```ts
interface Proposal {
  proposal_id: string; // PROP-0001
  case_id: string;
  investigation_id: string;
  kind: proposal_kind;
  version: number;
  status: proposal_status;
  content: MerchantQuestionContent | ActionContent;
  evidence_ids: string[];
  created_at: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  dispatch: Dispatch | null;
}

interface MerchantQuestionContent {
  question_text: string;
  why_asked: string;
}

interface ActionContent {
  action_id: string;
  owner_team: owner_team;
  title: string;
  instructions: string;
  rationale: string;
  target: Target;
  recheck_after_days: number;
}

interface ProposalCreate {
  // internal route, agent only
  investigation_id: string;
  kind: proposal_kind;
  content: MerchantQuestionContent | ActionContent;
  evidence_ids: string[];
}

interface ProposalEdit {
  content: MerchantQuestionContent | ActionContent;
}

interface DecisionRequest {
  version: number;
  decision: "approve" | "reject";
  note: string | null;
}

interface Dispatch {
  dispatch_id: string;
  status: dispatch_status;
  channel: "mock_merchant" | "mock_team_queue";
  owner_team: owner_team;
  dispatched_at: string;
}

interface MerchantReplyCreate {
  outcome: "replied" | "no_reply";
  text: string | null; // required when outcome is "replied"
}

interface MerchantReply {
  evidence_id: string; // EV-RPL-000001
  proposal_id: string;
  outcome: "replied" | "no_reply";
  text: string | null;
  recorded_by: string;
  recorded_at: string;
}

interface Recheck {
  recheck_id: string;
  case_id: string;
  proposal_id: string;
  scheduled_for: string;
  status: recheck_status;
  target: Target;
  before: RateWindow;
  after: RateWindow | null;
  control: RateWindow | null;
  data_sufficient: boolean | null;
  ran_at: string | null;
}

interface RateWindow {
  start: string;
  end: string;
  claims: number;
  eligible_orders: number;
  rate: number | null;
}

interface InvestigationStatusUpdate {
  // internal route, agent only
  investigation_id: string;
  status: investigation_status;
  error_code: string | null;
}

interface AuditEntry {
  audit_id: string;
  case_id: string;
  actor_id: string; // a user_id, or "svc_agent" / "svc_monitor"
  actor_role: role | "service";
  action: string; // e.g. "proposal.created", "proposal.approved", "dispatch.sent"
  proposal_id: string | null;
  version: number | null;
  request_id: string;
  at: string;
}
```

## Golden Dataset labels

The B-05 runner compares each investigation with its row in C-01's `eval.golden_scenarios`. The agent
never sees these rows.

| `eval.golden_scenarios` column | Compared with                                    | How                                                                               |
| ------------------------------ | ------------------------------------------------ | --------------------------------------------------------------------------------- |
| `scenario_id`                  | —                                                | Identifies the scenario in the scorecard                                          |
| `store_id`                     | `InvestigationView.store_id`                     | Joins the run to its scenario                                                     |
| `split`                        | —                                                | `dev` scenarios are used for tuning. `holdout` scenarios are reported separately. |
| `cause_category`               | `InvestigationResult.cause_category`             | Exact match                                                                       |
| `true_cause`                   | `InvestigationResult.summary`                    | Reviewed by a person                                                              |
| `cause_started_at`             | `InvestigationResult.cause_started_at`           | Within a tolerance set in the runner                                              |
| `expected_outcome`             | `InvestigationResult.outcome`, or no case opened | Exact match                                                                       |
| `expected_owner`               | `Recommendation.owner_team`                      | Exact match                                                                       |
| `expected_action`              | `Recommendation.action_id`                       | Exact match                                                                       |
| `key_evidence`                 | `supporting_evidence_ids`                        | Share of key evidence cited                                                       |
| `distractors`                  | `ruled_out` and `contradicting_evidence_ids`     | Each distractor ruled out or explained                                            |
| `notes`                        | —                                                | Not scored                                                                        |

## Endpoints

"Analyst" means `role == "loe_analyst"`. Every route that touches a store also checks that the store is in
the token's `store_ids`.

### Auth Service

| Method and path             | Who      | Request        | Response                   | Errors                         |
| --------------------------- | -------- | -------------- | -------------------------- | ------------------------------ |
| `POST /login`               | anyone   | `LoginRequest` | 200 `LoginResponse`        | 401 `INVALID_CREDENTIALS`, 422 |
| `GET /me`                   | any user | —              | 200 `User`                 | 401                            |
| `GET /health`, `GET /ready` | anyone   | —              | 200, or 503 when not ready | —                              |

### Agent Service

| Method and path                                  | Who             | Request                       | Response                                      | Errors                                                                          |
| ------------------------------------------------ | --------------- | ----------------------------- | --------------------------------------------- | ------------------------------------------------------------------------------- |
| `POST /investigations`                           | analyst         | `StartInvestigationRequest`   | 202 `InvestigationView` with status `running` | 403, 404 `CASE_NOT_FOUND`, 409 `INVESTIGATION_ACTIVE`, 409 `REOPEN_NOT_ALLOWED` |
| `GET /investigations/{investigation_id}`         | viewer, analyst | —                             | 200 `InvestigationView`                       | 403, 404                                                                        |
| `GET /investigations?case_id=`                   | viewer, analyst | —                             | 200 `InvestigationView[]`, newest first       | 403                                                                             |
| `POST /investigations/{investigation_id}/resume` | analyst         | empty body, `Idempotency-Key` | 202 `InvestigationView`                       | 403, 404, 409 `INVESTIGATION_FINISHED`                                          |

The graph runs in the background. While the status is `running`, the frontend polls
`GET /investigations/{id}` every 2 seconds.

### Domain Service, public through the gateway

Diagnostics that take filters use `POST` with a JSON body, because the filters hold lists. They are
read-only and never change data.

| Method and path                                                     | Who                    | Request                                                 | Response                                                                                | Errors                                                                 |
| ------------------------------------------------------------------- | ---------------------- | ------------------------------------------------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `GET /cases?status=&store_id=`                                      | viewer, analyst        | —                                                       | 200 `CaseSummary[]`, permitted stores only                                              | 401                                                                    |
| `GET /cases/{case_id}`                                              | viewer, analyst        | —                                                       | 200 `CaseDetail`                                                                        | 403, 404                                                               |
| `GET /cases/{case_id}/audit`                                        | viewer, analyst        | —                                                       | 200 `AuditEntry[]`                                                                      | 403, 404                                                               |
| `GET /cases/{case_id}/merchant-replies`                             | viewer, analyst, agent | —                                                       | 200 `MerchantReply[]`                                                                   | 403, 404                                                               |
| `GET /cases/{case_id}/rechecks`                                     | viewer, analyst        | —                                                       | 200 `Recheck[]`                                                                         | 403, 404                                                               |
| `POST /monitor/run`                                                 | analyst                | `{ "as_of": "2026-11-15" }` or empty, `Idempotency-Key` | 200 `{ run_id, evaluated_store_ids, opened_case_ids, skipped: [{ store_id, reason }] }` | 403                                                                    |
| `GET /stores/{store_id}`                                            | viewer, analyst, agent | —                                                       | 200 `StoreSummary`                                                                      | 403, 404                                                               |
| `GET /stores/{store_id}/menu` | viewer, analyst, agent | — | 200 `MenuItem[]`, the store's menu with each item's `available_modifiers` | 403, 404 |
| `GET /stores/{store_id}/overview?start=&end=`                       | viewer, analyst, agent | —                                                       | 200 `ToolResult`                                                                        | 403, 422                                                               |
| `GET /stores/{store_id}/diagnostics/events?start=&end=&event_type=` | viewer, analyst, agent | —                                                       | 200 `ToolResult` with `evidence` filled                                                 | 403, 422                                                               |
| `POST /stores/{store_id}/diagnostics/claim-breakdown`               | viewer, analyst, agent | `ClaimBreakdownRequest`                                 | 200 `ToolResult`                                                                        | 403, 422                                                               |
| `POST /stores/{store_id}/diagnostics/compare-periods`               | viewer, analyst, agent | `ComparePeriodsRequest`                                 | 200 `ToolResult` with `target` and `control` groups                                     | 403, 422                                                               |
| `POST /stores/{store_id}/diagnostics/evidence-sample`               | viewer, analyst, agent | `EvidenceSampleRequest`                                 | 200 `ToolResult` with `evidence` filled                                                 | 403, 422                                                               |
| `POST /stores/{store_id}/diagnostics/cancellation-breakdown`        | viewer, analyst, agent | `CancellationBreakdownRequest`                          | 200 `ToolResult`                                                                        | 403, 422                                                               |
| `GET /stores/{store_id}/diagnostics/fraud-signals?start=&end=`      | viewer, analyst, agent | —                                                       | 200 `ToolResult`                                                                        | 403, 422                                                               |
| `GET /catalog/actions`                                              | any user, agent        | —                                                       | 200 `ActionCatalogEntry[]`                                                              | 401                                                                    |
| `GET /evidence/{evidence_id}`                                       | viewer, analyst, agent | —                                                       | 200 `Evidence`                                                                          | 403, 404                                                               |
| `POST /evidence/resolve`                                            | agent                  | `EvidenceResolveRequest`                                | 200 `EvidenceResolveResponse`                                                           | 403                                                                    |
| `GET /proposals/{proposal_id}`                                      | viewer, analyst, agent | —                                                       | 200 `Proposal`                                                                          | 403, 404                                                               |
| `POST /proposals/{proposal_id}/versions`                            | analyst                | `ProposalEdit`                                          | 201 `Proposal` with the next version                                                    | 403, 409 `ALREADY_DECIDED`                                             |
| `POST /proposals/{proposal_id}/decision`                            | analyst                | `DecisionRequest`, `Idempotency-Key`                    | 200 `Proposal`, with `dispatch` set on approve                                          | 403, 409 `STALE_VERSION`, 409 `ALREADY_DECIDED`, 502 `DISPATCH_FAILED` |
| `POST /proposals/{proposal_id}/merchant-reply`                      | analyst                | `MerchantReplyCreate`, `Idempotency-Key`                | 201 `MerchantReply`                                                                     | 403, 409 `NOT_DISPATCHED`, 409 `REPLY_EXISTS`, 422                     |
| `POST /rechecks/{recheck_id}/run`                                   | analyst                | empty, `Idempotency-Key`                                | 200 `Recheck`                                                                           | 403, 409 `RECHECK_ALREADY_RUN`                                         |

No Domain route ever reads the `eval` schema.

Decision rules: approving checks the role, the store grant, `status == "pending"`, and that `version`
equals the current version. It then writes the audit entry and the mock dispatch in one transaction. An
approved `intervention` or `handoff` also schedules a recheck for `dispatched_at + recheck_after_days`.

### Domain Service, internal only

Unreachable through the gateway. Requires `X-Service-Token` and the forwarded user JWT.

| Method and path                               | Who   | Request                     | Response                                    | Errors                                                                    |
| --------------------------------------------- | ----- | --------------------------- | ------------------------------------------- | ------------------------------------------------------------------------- |
| `POST /internal/cases/{case_id}/proposals`    | agent | `ProposalCreate`            | 201 `Proposal`, status `pending`, version 1 | 403, 409 `PROPOSAL_PENDING`, 422 `INVALID_EVIDENCE`, 422 `UNKNOWN_ACTION` |
| `PUT /internal/cases/{case_id}/investigation` | agent | `InvestigationStatusUpdate` | 200 `CaseSummary`                           | 403, 404                                                                  |

These are the agent's only writes.

## Examples

The IDs in these examples are illustrative. Real evidence IDs come from the seeded data.

Group STORE-A's claims by modifier:

```http
POST /domain/stores/STORE-A/diagnostics/claim-breakdown
Authorization: Bearer eyJ...
X-Investigation-ID: INV-01JD3K9Q8F2M
Content-Type: application/json

{ "filter": { "start": "2026-10-05", "end": "2026-11-15" }, "group_by": "modifier" }
```

A completed STORE-A investigation, trimmed to the result:

```json
{
  "status": "completed",
  "result": {
    "outcome": "diagnosis",
    "cause_category": "pos_modifier_mapping",
    "cause_started_at": "2026-10-30",
    "confidence": "high",
    "summary": "Since Oct 30, about 1 in 5 orders with the Extra sauce modifier got an incorrect_item or ingredient_error claim. Orders without it stayed near the store's normal rate.",
    "supporting_evidence_ids": [
      "EV-EVT-000031",
      "EV-CLM-004410",
      "EV-CLM-004417"
    ],
    "contradicting_evidence_ids": [],
    "ruled_out": [
      {
        "cause_category": "inventory",
        "reason": "item_out_of_stock cancellations ran Oct 24-26 and ended before the claim rise.",
        "evidence_ids": ["EV-CXL-000045"],
        "check_ids": ["CHK-01JD3KA2"]
      }
    ],
    "evidence_gaps": [],
    "checks_tried": [
      "CHK-01JD3K9X",
      "CHK-01JD3KA0",
      "CHK-01JD3KA2",
      "CHK-01JD3KA5"
    ],
    "challenge_check_ids": ["CHK-01JD3KA5"],
    "unverified_reply_claims": [],
    "recommendation": {
      "kind": "handoff",
      "action_id": "fix_modifier_mapping",
      "owner_team": "pos_team",
      "rationale": "The claim rise starts with the Oct 30 menu_change and is limited to orders with Extra sauce.",
      "target": {
        "item_id": [],
        "modifiers": ["Extra sauce"],
        "daypart": [],
        "item_count_min": null
      },
      "recheck_after_days": 14
    },
    "proposal_id": "PROP-0001"
  }
}
```

Approve that proposal:

```http
POST /domain/proposals/PROP-0001/decision
Authorization: Bearer eyJ...
Idempotency-Key: 6f1c2a1e-8a1f-4b9e-9b7e-2f1f0d1c3a55
Content-Type: application/json

{ "version": 1, "decision": "approve", "note": null }
```

## Errors

Every error uses one envelope, including FastAPI's validation errors:

```json
{
  "error": {
    "code": "STALE_VERSION",
    "message": "Proposal PROP-0001 is at version 2. Review the latest version before deciding.",
    "details": { "current_version": 2 },
    "request_id": "b7c1f0e2a9d34c1e"
  }
}
```

| HTTP | Code                                 | When                                                                                                                    |
| ---- | ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| 401  | `UNAUTHENTICATED`                    | Token missing, malformed or expired                                                                                     |
| 401  | `INVALID_CREDENTIALS`                | Wrong username or password                                                                                              |
| 403  | `FORBIDDEN`                          | The role can't do this                                                                                                  |
| 403  | `STORE_NOT_PERMITTED`                | The store isn't in the token's grants                                                                                   |
| 403  | `SERVICE_TOKEN_INVALID`              | Internal route called without a valid service token                                                                     |
| 404  | `NOT_FOUND`, `CASE_NOT_FOUND`        | No such resource, or not visible to this user                                                                           |
| 409  | `INVESTIGATION_ACTIVE`               | The case already has a running or paused investigation                                                                  |
| 409  | `INVESTIGATION_FINISHED`             | Resume on a completed, unsure or failed investigation                                                                   |
| 409  | `REOPEN_NOT_ALLOWED`                 | `reopen_of` set but the case isn't `reopened`, or it was already reopened once                                          |
| 409  | `PROPOSAL_PENDING`                   | The case already has a pending proposal                                                                                 |
| 409  | `STALE_VERSION`                      | The decision names an old version                                                                                       |
| 409  | `ALREADY_DECIDED`                    | Proposal already approved or rejected with a different decision                                                         |
| 409  | `NOT_DISPATCHED`, `REPLY_EXISTS`     | Reply to an undispatched question, or a second reply                                                                    |
| 409  | `RECHECK_ALREADY_RUN`                | The recheck already has a result                                                                                        |
| 422  | `VALIDATION_ERROR`                   | Body or query fails validation, including an unknown `item_id`, modifier, `daypart`, or a date outside the store's data |
| 422  | `INVALID_EVIDENCE`, `UNKNOWN_ACTION` | Proposal cites unresolvable evidence or an action outside the catalog                                                   |
| 502  | `DISPATCH_FAILED`                    | Mock dispatch failed. The proposal stays `pending`.                                                                     |
| 503  | `UPSTREAM_UNAVAILABLE`               | A called service or the model is unreachable                                                                            |
| 500  | `INTERNAL`                           | Anything else. Details are logged, not returned.                                                                        |

Hiding other stores' cases returns 404 rather than 403 on single-resource reads, so IDs from other stores
can't be probed. List endpoints simply leave them out.

### Investigation error codes

`InvestigationView.error.code`, and `InvestigationStatusUpdate.error_code` when the status is `failed`,
take one of these values:

| Code | When |
|---|---|
| `UPSTREAM_UNAVAILABLE` | Domain or the model was unreachable after retries |
| `UNAUTHENTICATED` | Domain rejected the forwarded token during the run |
| `DOMAIN_REJECTED` | Domain refused a call the run depends on, other than a 422 on a check |
| `MODEL_REFUSED` | The model declined the turn, after the fallback model |
| `MODEL_TRUNCATED` | A turn hit `max_tokens` twice |
| `RUN_TIMEOUT` | The run passed `AGENT_RUN_TIMEOUT_SECONDS` |
| `AGENT_RESTARTED` | The Agent Service restarted while the run was active |
| `INTERNAL` | Anything else. Details are logged, not returned. |

A Domain 422 on a diagnostic check doesn't fail the run. The check is recorded as an insufficient result
with Domain's message, and the step counts.

## Idempotency

- **Same key, same result.** A repeat with an `Idempotency-Key` already seen returns the stored response and writes nothing.
- **Same decision, same result.** Approving an already-approved version returns 200 with the existing proposal and never dispatches twice.
- **One open case per alert.** The monitor never opens a second open case for a store that already has one.
- **One reply per question.** A second reply returns 409 `REPLY_EXISTS` and doesn't resume anything.

## Open questions for sign-off

1. **The agent's two internal writes** are creating a draft proposal and reporting its status. Quang should approve this as the boundary rule.
2. **Polling every 2 seconds** instead of server-sent events.
3. **`confidence` as `low`, `medium` or `high`** instead of a number.
4. **Monitor thresholds.** C-01 tunes the seed so the problem stores cross "a 7-day rate above 5% with at least 100 eligible orders", while the borderline stores don't. C-02 owns the final values.
5. **A 42-day window and two merchant questions per run.**
