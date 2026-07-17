# Cascade Review Checklist: PR #2 (001-wan-insights-metrics)

**Purpose**: Reviewer gate for Asya (Juniper SE, T-Mobile) + internal engineer before merging the cascade rewrite.
**Created**: 2026-07-17
**Scope**: Validate that specs, contracts, tasks, and customer-facing doc correctly encode the corrected assumptions.

## Per-Port Metrics Source (wan_link_health)

- [ ] CHK001 Do the specs state that per-port jitter/latency/loss are sourced from the native `wan_link_health` insight metric? [Clarity, Spec §FR / research.md]
- [ ] CHK002 Are all references to "peer discovery", "peer fanout", or "peer_paths aggregation" for per-port metrics removed from spec.md, research.md, and data-model.md? [Consistency, Gap]
- [ ] CHK003 Is the requirement that no client-side aggregation is performed on per-port jitter/latency/loss explicitly documented? [Completeness]
- [ ] CHK004 Are the `object_type`, `metric`, and required parameters (device_id/port_id) for `wan_link_health` fully specified for reviewer traceability? [Clarity]
- [ ] CHK005 Are hourly interval and time-range requirements for the per-port endpoint measurable? [Measurability]

## Application Health SLE (First-Class SSR SLE)

- [ ] CHK006 Do the specs explicitly identify Application Health % as a first-class Mist SLE on SSR (not a proxy/substitute)? [Clarity, Spec]
- [ ] CHK007 Are the four SLE endpoints listed verbatim: `/sle/site/{id}/metric/application-health/{summary,summary-trend,impacted-interfaces,threshold}`? [Completeness, contracts/]
- [ ] CHK008 Have all "session-storage notice", "surrogate metric", or "approximation" callouts for Application Health been removed? [Consistency, Gap]
- [ ] CHK009 Is the SSR licensing/entitlement prerequisite documented so Asya can validate T-Mobile coverage? [Assumption, Dependency]
- [ ] CHK010 Are the required `scope`, `scope_id`, and time-range parameters for the SLE calls specified? [Completeness]

## CSV Export Contract (12 Columns)

- [ ] CHK011 Does the CSV contract enumerate exactly 12 columns? [Completeness, contracts/]
- [ ] CHK012 Are `peer_count` and `aggregation_method` explicitly absent from the column list? [Consistency]
- [ ] CHK013 Are column names, order, units, and null semantics specified unambiguously? [Clarity]
- [ ] CHK014 Is the export filename / content-type / row-ordering rule defined? [Completeness]
- [ ] CHK015 Do tasks.md and quickstart.md examples match the 12-column contract? [Consistency]

## SDK Dependency (`mistapi>=0.63.3`)

- [ ] CHK016 Is `mistapi>=0.63.3` pinned in the dependency requirements section? [Completeness, plan.md]
- [ ] CHK017 Do the specs state SDK helpers are preferred, with `requests` fallback only where SDK helpers do not exist? [Clarity]
- [ ] CHK018 Are the specific SDK helper functions used (or the gaps requiring `requests`) enumerated? [Traceability, Gap]
- [ ] CHK019 Is authentication / token-rotation behavior for the fallback path specified consistently with SDK usage? [Consistency]

## Backend Route Contracts

- [ ] CHK020 Is the route `/api/v1/sites/<site_id>/gateways/<device_id>/ports/<port_id>/hourly` documented with method, params, and response shape? [Completeness, contracts/]
- [ ] CHK021 Is `/api/v1/sites/<site_id>/application-health-summary` documented with method, params, and response shape? [Completeness]
- [ ] CHK022 Is `/hourly/export` documented with method, params, and CSV response contract? [Completeness]
- [ ] CHK023 Are path parameter formats (UUID vs port string) unambiguously specified for each route? [Clarity]
- [ ] CHK024 Are error responses (404 missing device/port, 403 unlicensed SLE, 429 rate limit) defined for each route? [Coverage, Edge Case]

## Residual Pre-Cascade Language Sweep

- [ ] CHK025 Are all mentions of "peer_paths per-port aggregation" removed from spec.md, plan.md, research.md, data-model.md, tasks.md, quickstart.md? [Consistency, Gap]
- [ ] CHK026 Are all "fanout across peers" or "peer discovery loop" phrases eliminated? [Consistency]
- [ ] CHK027 Are all references to Application Health as a "substitute", "proxy", or "session-cached" metric removed? [Consistency]
- [ ] CHK028 Are the removed CSV columns (`peer_count`, `aggregation_method`) absent from every doc, sample, and task line? [Consistency]
- [ ] CHK029 Are older `mistapi` version pins (< 0.63.3) removed everywhere? [Consistency]
- [ ] CHK030 Are pre-cascade route names or param shapes absent from tasks.md and quickstart.md? [Consistency]

## Customer Response Doc Alignment (`docs/customer_response_wan_insights.md`)

- [ ] CHK031 Does the customer doc describe per-port metrics as sourced from `wan_link_health` (matching spec)? [Consistency]
- [ ] CHK032 Does the customer doc describe Application Health as a first-class SSR SLE (matching spec)? [Consistency]
- [ ] CHK033 Does the customer doc list the same CSV columns (12, no peer_count/aggregation_method)? [Consistency]
- [ ] CHK034 Does the customer doc reference `mistapi>=0.63.3` and the SDK-first approach? [Consistency]
- [ ] CHK035 Are the backend routes named in the customer doc identical to the contracts? [Consistency]
- [ ] CHK036 Are T-Mobile-specific caveats (SSR licensing, rate limits, token rotation) surfaced for Asya's review? [Completeness]
- [ ] CHK037 Is the customer doc free of pre-cascade language (peer aggregation, proxy Application Health, deprecated columns)? [Consistency]
- [ ] CHK038 Are commitments/deliverables in the customer doc traceable to spec.md requirement IDs? [Traceability]
