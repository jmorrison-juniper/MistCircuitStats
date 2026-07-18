---
description: "Task list for feature 002-mistapi-sdk-unification"
---

# Tasks: Unify Mist API Access Under the `mistapi` SDK

**Input**: Design documents from `specs/002-mistapi-sdk-unification/`

**Prerequisites**: plan.md (required), spec.md (required). No `research.md`, `data-model.md`, `contracts/`, or `quickstart.md` are produced for this feature — the design is settled (SDK signatures already verified against installed `mistapi` 0.63.3), no schema change occurs, wire contracts from feature 001 continue to apply, and the manual smoke test in spec § SC-006 is the runbook.

**Tests**: No automated tests are added by this feature. Acceptance is via (a) byte-diff of pre/post JSON responses per spec § SC-002, (b) forced-429 rotation check per endpoint per spec § SC-003, (c) manual dashboard smoke test per spec § SC-006, and (d) SLE `/summary-trend` bucket-cadence spot-check per spec § SC-008. No unit-test scaffolding, no new integration test harness — spec § "Out of Scope" is explicit.

**Organization**: Tasks are grouped by user story. US1 (rate-limit rotation coverage) and US2 (byte-identical response shapes) are both P1 and are accomplished by the SAME code migrations — so the seven implementation tasks are tagged `[US1]` and US2 shows up as a dedicated verification task in the same phase. US3 (documentation tells the truth) is P2 and sequences after the code migration.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files or non-overlapping regions, no dependencies on incomplete tasks)
- **[Story]**: User story mapping — [US1], [US2], [US3]; omitted for Setup/Foundational/Polish
- Every task references an exact file path (absolute where non-obvious) and, where applicable, a function or approximate line range from the plan's SDK Mapping Table

## Path Conventions

Single-file-per-role Flask layout (per plan.md § Project Structure). All code changes land in two existing Python files at repo root plus two docs files. `templates/index.html`, `pyproject.toml`, `requirements.txt`, and `.github/workflows/quality-gates.yml` are on the FR-012 do-not-touch list.

- Backend: `mist_connection.py`, `app.py`
- Docs: `README.md`, `CHANGELOG.md`
- Response-shape contracts (preserved from feature 001, not renegotiated): `specs/001-wan-insights-metrics/contracts/GET_gateway_port_hourly.md`, `specs/001-wan-insights-metrics/contracts/GET_site_application_health.md`

---

## Phase 1: Setup

**Purpose**: Confirm the environment is ready for the migration and the new wrapper method name does not collide.

- [ ] T001 Verify feature branch `002-mistapi-sdk-unification` is checked out and `git status` is clean before editing `mist_connection.py` or `app.py`. Confirm `pip show mistapi` reports `Version: 0.63.3` or newer (per plan.md § Technical Context; `pyproject.toml` and `requirements.txt` are on the FR-012 do-not-touch list, so no bump is expected — this is a read-only verification).
- [ ] T002 Verify no symbol collision for the new wrapper method: `grep -Rn "get_gateway_port_traffic_series" mist_connection.py app.py templates/index.html` MUST return zero hits before T011 introduces the symbol (per plan.md § Known Caveats "`get_gateway_port_traffic_series` symbol name", spec § Edge Cases "`get_gateway_port_traffic_series` name collision").
- [ ] T003 [P] Read plan.md § SDK Mapping Table, § Migration Pattern, and § Known Caveats to Preserve end-to-end so every subsequent migration task lands with the same 429-wrapper idiom (`response = mistapi...`; `if self._handle_rate_limit_response(response): response = mistapi...`; envelope stays `{"success": ..., "rate_limited": ..., "data": ...}`).

**Checkpoint**: Branch and SDK version confirmed. No name collision. Migration pattern memorized.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Capture the pre-migration ground truth so US2 byte-diff verification (T013) has something to compare against. This BLOCKS the code migration because once the migration lands, the pre-migration samples cannot be recovered without a branch revert.

- [ ] T004 Capture pre-migration JSON response fixtures for all 7 migrated endpoints against a live Mist org, one representative sample per endpoint, and save them under a local (git-ignored) directory or an out-of-tree scratch location. The 7 endpoints are: (1) `get_vpn_peer_stats` (via its Flask route), (2) `_insights_gateway_stats` (via the WAN Insights modal for a chosen port + 24h duration), (3) `_insights_device_wan_link_health` (same modal — the jitter/latency/loss chart), (4)–(6) the three branches of `_sle_app_health_get` (Application Health tile: summary-trend, impacted-interfaces, threshold), and (7) `app.py::get_port_traffic` (legacy chart-modal popup, per-second RX/TX). Record the exact request parameters (`site_id`, `gateway_id`/`device_id`, `port_id`, `start`, `end`, `interval`, `duration`) alongside each JSON blob. Also capture one CSV export from `.../hourly/export?duration=24h` for the 12-column byte-diff. These fixtures satisfy the input side of SC-002. Reference: spec § SC-002, spec § User Story 2 § Independent Test.

**Checkpoint**: Pre-migration samples on disk. Code migration can now begin — any regression against these fixtures will be caught in T013.

---

## Phase 3: User Story 1 + User Story 2 — SDK Migration (Priority: P1) MVP

**Goal (US1)**: Every Mist call — including the legacy chart-modal port-traffic route — routes through `MistConnection._handle_rate_limit_response(response)` and inherits the multi-token 60-second per-token cooldown. No 429 exception may surface to the frontend from any of the 7 migrated endpoints.

**Goal (US2)**: Every migrated endpoint returns a JSON envelope (and, for the CSV export, a 12-column layout) that is byte-identical to the pre-migration response modulo timestamps and rate-limit counters. The frontend contract with `templates/index.html` is preserved verbatim.

**Independent Test (US1)**: With 2+ tokens configured, force a 429 on each of the 7 migrated endpoints in turn and confirm a `Switching to token N/M` log line plus a successful retry against the next healthy token. When ALL tokens are cooling down, every migrated endpoint returns `success: true, rate_limited: {tokens_cooling_down: N, retry_after_seconds: X}` with empty data arrays — never HTTP 429 to the frontend.

**Independent Test (US2)**: Replay the T004 pre-migration fixtures against the migrated code and byte-diff the responses. Only timestamps and rate-limit counters may differ; every other byte MUST match. The CSV export must present columns in the exact order `site_name, gateway_name, port_id, hour_epoch, hour_iso, rx_avg_bps, rx_peak_bps, tx_avg_bps, tx_peak_bps, jitter_avg_ms, latency_avg_ms, loss_avg_pct`.

### Implementation for User Story 1 (also delivers User Story 2)

Every task below:
- Uses the SDK invocation + 429-retry idiom in plan.md § Migration Pattern verbatim.
- Preserves the pre-migration return envelope: `{"success": True, "rate_limited": False, "data": <payload>}` on HTTP 200, `{"success": False, "rate_limited": True, "data": None}` when all tokens are cooling down, `{"success": False, "rate_limited": False, "data": None}` on other non-200 statuses (spec § FR-007, plan § Migration Pattern "Invariants").
- Updates the migrated method's docstring to (a) name the SDK function it now calls, and (b) preserve every pre-existing Why-line quirk (device-scoped `wan_link_health`, `/summary-trend` in place of `/summary`, 14-day retention). Google-style Args/Returns/Raises sections stay pydoclint-clean (spec § FR-008).

- [ ] T005 [US1] Migrate `MistConnection.get_vpn_peer_stats` (`mist_connection.py`, approx L899-975) to call `mistapi.api.v1.orgs.stats.searchOrgPeerPathStats(self.apisession, org_id, mac=..., site_id=...)` in place of the current direct-REST call to `POST/GET /api/v1/orgs/{org_id}/stats/vpn_peers/search`. Route the response through `self._handle_rate_limit_response(response)`; on rotation, re-issue the SDK call once against the rotated session. Preserve the existing method's return envelope byte-for-byte. Update the docstring to name `searchOrgPeerPathStats`. Reference: spec § FR-001, plan § SDK Mapping Table row #12, plan § Migration Pattern.
- [ ] T006 [US1] Migrate `MistConnection._insights_gateway_stats` (`mist_connection.py`, approx L981-1033) to call `mistapi.api.v1.sites.insights.getSiteInsightMetricsForGateway(self.apisession, site_id, device_id, metrics=..., port_id=..., start=..., end=..., duration=..., interval=...)` in place of the current direct-REST call to `GET /api/v1/sites/{site_id}/insights/gateway/{device_id}/stats`. Forward `metrics`, `port_id`, `interval`, `start`, `end`, and `duration` with identical semantics. Route through `_handle_rate_limit_response`; retry once on rotation. Preserve `response.data` handoff to the existing downstream parser (`get_gateway_hourly_bandwidth`). Update the docstring to name `getSiteInsightMetricsForGateway` and to record the 14-day 1h-interval retention window. Reference: spec § FR-002, plan § SDK Mapping Table row #13.
- [ ] T007 [US1] Migrate `MistConnection._insights_device_wan_link_health` (`mist_connection.py`, approx L1035-1080) to call `mistapi.api.v1.sites.insights.getSiteInsightMetricsForDevice(self.apisession, site_id, metric="wan_link_health", device_mac=<mac>, port_id=..., start=..., end=..., duration=..., interval=...)` in place of the current direct-REST call to `GET /api/v1/sites/{site_id}/insights/device/{mac}/wan_link_health`. Keep the existing MAC derivation `device_id.replace("-", "")[-12:]` and pass its result as `device_mac`. Route through `_handle_rate_limit_response`; retry once on rotation. The docstring Why-line MUST record the device-scoped quirk verbatim: this endpoint is device-scoped, not gateway-scoped, and MUST target `getSiteInsightMetricsForDevice` with `metric="wan_link_health"` — a future reader must not re-route it through `getSiteInsightMetricsForGateway`. Reference: spec § FR-003, spec § Edge Cases "`wan_link_health` scope quirk", plan § SDK Mapping Table row #14, plan § Known Caveats.
- [ ] T008 [US1] Migrate the `summary-trend` branch of `MistConnection._sle_app_health_get` (`mist_connection.py`, approx L1269-1307) to call `mistapi.api.v1.sites.sle.getSiteSleSummaryTrend(self.apisession, site_id, "site", site_id, "application-health", start=..., end=..., duration=...)` in place of the current direct-REST call to `GET .../application-health/summary-trend`. Do NOT pass `interval=3600` — the SDK function does not accept it and `3600` is the Mist API default (spot-check is queued as T015). Route through `_handle_rate_limit_response`; retry once on rotation. The docstring Why-line MUST preserve verbatim: this method calls `/summary-trend` (via `getSiteSleSummaryTrend`), NOT `/summary` (`getSiteSleSummary`), because the latter returns HTTP 400 on this org. Reference: spec § FR-004, spec § Edge Cases "SLE `/summary-trend` used instead of `/summary`", plan § SDK Mapping Table row #15, plan § Known Caveats.
- [ ] T009 [US1] Migrate the `impacted-interfaces` branch of `MistConnection._sle_app_health_get` (same helper as T008) to call `mistapi.api.v1.sites.sle.listSiteSleImpactedInterfaces(self.apisession, site_id, "site", site_id, "application-health", start=..., end=..., duration=...)` in place of the current direct-REST call to `GET .../application-health/impacted-interfaces`. Route through `_handle_rate_limit_response`; retry once on rotation. Collapse the shared `_sle_app_health_get` `requests.get` into a small dispatch on `sub_path` that picks the right SDK function across T008/T009/T010 (per plan § SDK Mapping Table Notes). Update the docstring to name `listSiteSleImpactedInterfaces` alongside the T008 addition. Reference: spec § FR-004, plan § SDK Mapping Table row #16. Depends on: T008 (same helper method body).
- [ ] T010 [US1] Migrate the `threshold` branch of `MistConnection._sle_app_health_get` (same helper as T008/T009) to call `mistapi.api.v1.sites.sle.getSiteSleThreshold(self.apisession, site_id, "site", site_id, "application-health")` in place of the current direct-REST call to `GET .../application-health/threshold`. Route through `_handle_rate_limit_response`; retry once on rotation. Update the docstring to name `getSiteSleThreshold` alongside the T008/T009 additions. Reference: spec § FR-004, plan § SDK Mapping Table row #17. Depends on: T008, T009 (same helper method body).
- [ ] T011 [US1] Add a new public wrapper method `MistConnection.get_gateway_port_traffic_series(site_id, gateway_id, port_id, start, end, interval)` in `mist_connection.py` that calls `mistapi.api.v1.sites.insights.getSiteInsightMetricsForGateway(self.apisession, site_id, gateway_id, metrics="rx_bps,tx_bps", port_id=port_id, start=start, end=end, interval=interval)` and routes through `_handle_rate_limit_response` with a single retry on rotation. Then reduce `app.py::get_port_traffic` (approx L122-167) to a single call to this new method plus the pre-existing per-second envelope assembly. Remove the inline `import requests`, `unquote`, header/URL/params blocks from the route body. Preserve the response envelope verbatim: `{"success": true, "data": {"timestamps": [...], "rx_bps": [...], "tx_bps": [...]}}` — the templated JS in `templates/index.html` reads exactly these three keys (plan § Response-Shape Contracts). The new method's docstring MUST name `getSiteInsightMetricsForGateway`, note that this is the legacy chart-modal port-traffic path now inside the shared 429 rotation wrapper, and confirm no symbol collision (per T002). Reference: spec § FR-005, plan § SDK Mapping Table row #18, plan § Known Caveats "`get_gateway_port_traffic_series` symbol name".
- [ ] T012 [US1] Drop `import requests` from `mist_connection.py` and from `app.py` if — and only if — no other non-Mist code path in those files still needs it. Verify with `grep -n "\brequests\." mist_connection.py app.py` after T005–T011 land; if any hit remains that is genuinely non-Mist, keep the import and annotate the surviving call with an inline comment naming the non-Mist purpose (per spec § SC-001). Reference: plan § Technical Context "`requests` is being demoted", spec § SC-001. Depends on: T005–T011 all landed.

### Verification for User Story 2

- [ ] T013 [US2] Byte-diff every migrated endpoint's post-migration response against the T004 pre-migration fixture. Replay each captured request against the migrated code and compare JSON responses key-by-key and value-by-value. Timestamps and rate-limit counters are allowed to differ; every other byte MUST match. Also replay the captured CSV export at `.../hourly/export?duration=24h` and confirm the 12-column layout in this exact order: `site_name, gateway_name, port_id, hour_epoch, hour_iso, rx_avg_bps, rx_peak_bps, tx_avg_bps, tx_peak_bps, jitter_avg_ms, latency_avg_ms, loss_avg_pct`. Any diff outside the whitelisted fields blocks release. Record the outcome (one bullet per endpoint) in the PR description. Reference: spec § FR-011, spec § SC-002, spec § User Story 2 § Acceptance Scenarios 2 and 4. Depends on: T004 (fixtures), T005–T011 (migration complete).

### Verification for User Story 1

- [ ] T014 [US1] Forced-429 rotation smoke test: with 2 or more Mist API tokens configured, force a 429 response against each of the 7 migrated endpoints in turn (e.g. by exhausting token #1 or by using an invalidated token). Confirm for each endpoint that (a) a `Switching to token N/M` log line is emitted, (b) the retry against token #2 succeeds, and (c) the HTTP response to the frontend is `success: true` — never HTTP 429. Then force all tokens into cooldown simultaneously and confirm every endpoint returns `success: true, rate_limited: {tokens_cooling_down: N, retry_after_seconds: X}` with empty data arrays. Record one bullet per endpoint in the PR description. Reference: spec § FR-006, spec § FR-007, spec § SC-003, spec § SC-004, spec § User Story 1 § Acceptance Scenarios. Depends on: T005–T011.
- [ ] T015 [US1] SLE `/summary-trend` bucket-cadence spot-check: on a live site that reports `application-health`, capture the pre-migration `/summary-trend` payload with `interval=3600` and the post-migration `getSiteSleSummaryTrend` payload without the `interval` argument for the same time window. Confirm the returned bucket cadence (hour boundaries) is unchanged. If the cadence differs, the T008 migration MUST be reverted and a follow-up filed. Record the outcome (pre/post bucket count, first/last hour epoch) in the PR description. Reference: spec § FR-013, spec § SC-008, spec § Edge Cases "`getSiteSleSummaryTrend` `interval` parameter drop", plan § Known Caveats. Depends on: T008.

**Checkpoint**: All 7 direct-REST call sites now route through the SDK and through `_handle_rate_limit_response`. The response shapes served to `templates/index.html` are byte-identical (modulo timestamps and rate-limit counters). Forced-429 rotation is observable end-to-end. The SLE bucket cadence is confirmed unchanged. The MVP scope for this feature is complete; US3 (documentation) is the remaining P2 work.

---

## Phase 4: User Story 3 — Documentation Tells the Truth (Priority: P2)

**Goal**: Collapse the README/architecture story from "two ways to talk to Mist" to a single SDK path. Add an `[Unreleased] → Changed` entry to `CHANGELOG.md` naming the unification and explicitly noting that the legacy chart-modal port-traffic route now benefits from shared token rotation. Prove via grep that zero Mist-directed `requests.get` calls remain in the codebase.

**Independent Test**: `grep -Rn "requests\.get" mist_connection.py app.py` returns zero Mist-directed hits (any survivors are non-Mist and clearly annotated). `grep -Rn "Direct REST endpoints" README.md` returns zero hits. The Architecture section describes a single SDK path — no "two ways" framing. `CHANGELOG.md` has an entry under `[Unreleased] → Changed` naming the unification.

### Implementation for User Story 3

- [ ] T016 [P] [US3] Rewrite the Mist-API sections of `README.md`: (a) remove the "Direct REST endpoints" subheading entirely, (b) merge its rows into a single flat "Mist API Endpoints" list (all rows now describe SDK-backed endpoints), (c) rewrite the Architecture section to describe a single SDK path — no "two ways" framing, no bifurcated call graph, no reference to inline `requests.get`. Every row in the merged list MUST name the SDK function that serves it. Reference: spec § FR-009, spec § User Story 3 § Acceptance Scenarios 1 and 2.
- [ ] T017 [P] [US3] Add an entry to `CHANGELOG.md` under `[Unreleased] → Changed` naming the unification. The entry MUST explicitly state that the legacy chart-modal port-traffic route (`app.py::get_port_traffic`) is no longer an inline `requests.get` and now benefits from the shared multi-token 60-second per-token 429 rotation via `MistConnection._handle_rate_limit_response`. Reference: spec § FR-010, spec § User Story 3 § Acceptance Scenario 3.
- [ ] T018 [US3] Docs-and-search verification: run `grep -Rn "requests\.get" mist_connection.py app.py` and confirm zero Mist-directed hits (annotate any non-Mist survivors inline in the source per T012). Run `grep -Rn "Direct REST endpoints" README.md` and confirm zero hits. Run `grep -Rn "two ways" README.md` and confirm no "two ways to talk to Mist" framing survives in the Architecture section. Confirm the `[Unreleased] → Changed` entry from T017 is at the top of `CHANGELOG.md`. Record the four grep outputs (all expected empty except the CHANGELOG confirmation) in the PR description. Reference: spec § SC-001, spec § SC-007, spec § User Story 3 § Independent Test. Depends on: T012 (import drop), T016 (README rewrite), T017 (CHANGELOG entry).

**Checkpoint**: An engineer reading `README.md` sees a single SDK path with a single flat endpoint list. `CHANGELOG.md` records the unification. `grep` confirms zero Mist-directed `requests.get` calls remain.

---

## Phase 5: Polish — Docstring Audit, Quality Gates, Smoke Test

**Purpose**: Consolidated verification that (a) every migrated docstring meets the FR-008 bar, (b) all 8 CI quality gates pass, and (c) the manual dashboard smoke test passes end to end against a live Mist org.

- [ ] T019 Docstring audit on the 6 migrated methods and 1 new method (`get_vpn_peer_stats`, `_insights_gateway_stats`, `_insights_device_wan_link_health`, `_sle_app_health_get`, and the new `get_gateway_port_traffic_series`; the SLE helper covers T008/T009/T010 in one body). For each method, confirm the docstring: (a) names the SDK function(s) it now calls, (b) preserves every pre-existing Why-line quirk verbatim — device-scoped `wan_link_health`, `/summary-trend` in place of `/summary`, 14-day 1h-interval retention, (c) uses Google-style `Args:`, `Returns:`, and (where applicable) `Raises:` sections that pass `pydoclint --style=google`. Reference: spec § FR-008, `~/.claude/DOCS.md` docstring policy. Depends on: T005–T011.
- [ ] T020 Run the 8 CI quality gates locally and confirm all pass on the migrated branch: `ruff`, `black --check`, `bandit`, `pip-audit`, `radon cc --max-average B` (CC ≤ 15), `vulture --min-confidence 90`, `interrogate` (≥ 90% docstring coverage), `pydoclint --style=google`. Fix any regressions before opening the PR. Reference: spec § SC-005, plan § Constitution Check row "Docstring quality". Depends on: T005–T019.
- [ ] T021 End-to-end manual smoke test against a live Mist org (per spec § SC-006): (a) dashboard loads the gateway list without error; (b) clicking a WAN Insights port opens the modal and renders RX/TX/jitter/latency/loss across all 5 duration presets (1h, 6h, 24h, 3d, 7d); (c) the click-a-cell chart popup on the main gateway table still renders per-second RX/TX; (d) CSV export via `.../hourly/export?duration=24h` returns the canonical 12-column layout in the documented order (matches T013). Record pass/fail per bullet in the PR description. Reference: spec § SC-006, spec § User Story 2 § Acceptance Scenarios. Depends on: T005–T020.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start with T001–T003.
- **Foundational (Phase 2)**: Depends on Setup. T004 MUST land before the code migration begins, otherwise the pre-migration fixtures cannot be re-captured for T013 byte-diff.
- **User Story 1 + US2 Verification (Phase 3)**: Depends on Phase 2 (T004 fixtures). This is the load-bearing phase; T005–T011 do the migration, T013 verifies US2, T014/T015 verify US1.
- **User Story 3 (Phase 4)**: Depends on Phase 3 code being final (T005–T011). T016/T017 can start in parallel with each other. T018 (grep verification) needs T012, T016, T017 all landed.
- **Polish (Phase 5)**: Depends on all prior phases. T019 docstring audit needs T005–T011; T020 quality gates need everything landed; T021 smoke test needs T020 clean.

### User Story Dependencies

- **US1 (P1)**: Independent of US3. Delivered by T005–T012 (migration) plus T014/T015 (verification).
- **US2 (P1)**: Co-priority with US1 and delivered by the SAME code changes — the migration is byte-identical modulo timestamps by construction. Verification is T013.
- **US3 (P2)**: Documentation. Sequences after US1/US2 because the docs claim ("only one SDK path") only becomes true once the code migration lands.

### Within Each User Story

- No test-first sequencing (no automated tests are in scope).
- Per-method: SDK call swap → route through `_handle_rate_limit_response` → docstring update → commit.
- Commit after each task or logical group.
- The three SLE branches (T008, T009, T010) touch the same helper body (`_sle_app_health_get`) — treat as one editing session, in the order T008 → T009 → T010, then commit.

### Parallel Opportunities

Explicit `[P]` markers indicate independent files or independent DOM regions:

- **Setup**: T003 [P] (spec/plan re-read) runs alongside T001 / T002 (env verification).
- **Foundational**: T004 is single-owner (one engineer runs the live-org capture).
- **Phase 3**: T005, T006, T007, T011 all edit `mist_connection.py` in non-overlapping regions plus (for T011) a section of `app.py`. Treat them as sequential editor sessions rather than truly parallel — no `[P]` marker. T008/T009/T010 must be sequential because they share `_sle_app_health_get`.
- **Verification**: T013 (US2 byte-diff), T014 (US1 forced-429), T015 (SLE cadence spot-check) all read the migrated code from Phase 3 and can be run by three different engineers in parallel once T005–T011 are merged — but no `[P]` marker is applied because each requires live-org access and coordination.
- **Docs**: T016 [P] (README rewrite) and T017 [P] (CHANGELOG entry) are independent files and can run concurrently.
- **Polish**: T019 (docstring audit) can start as soon as T005–T011 are merged, in parallel with T016/T017 if staffed.

---

## Parallel Example: User Story 3 (P2) documentation

```bash
# After T005–T012 are merged, these two documentation tasks can proceed in parallel:
Task T016 [P] [US3] Rewrite README.md — remove "Direct REST endpoints" subheading; single flat SDK list
Task T017 [P] [US3] Add [Unreleased] → Changed entry to CHANGELOG.md naming the unification
# T018 (grep verification) then confirms both have landed.
```

---

## Implementation Strategy

### MVP First (User Story 1 + User Story 2 only)

1. Phase 1 (Setup) → Phase 2 (Foundational: T004 fixture capture) → Phase 3 (T005–T012 migration + T013/T014/T015 verification).
2. STOP and validate against spec § SC-002, SC-003, SC-004, SC-008 on a live Mist org.
3. Ship if leadership approves the P1-only slice: rate-limit rotation coverage plus byte-identical response shapes is a complete, independently valuable increment — the documentation cleanup is P2 and can follow.

### Incremental Delivery

1. Setup + Foundational → foundation ready and pre-migration fixtures on disk.
2. Add US1 + US2 → validate byte-diff + forced-429 rotation + SLE cadence → deploy (MVP).
3. Add US3 → validate grep-based docs check → deploy.
4. T020 quality-gate verification is a hard gate for every deploy.
5. T021 smoke test is a hard gate for every deploy.

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together (T004 fixture capture is a single-owner task).
2. Once Foundational is done:
   - Developer A: T005, T006, T007 (three independent method migrations in `mist_connection.py`) sequentially, then T011 (new wrapper + `app.py` route reduction).
   - Developer B: T008 → T009 → T010 (the SLE helper trio, one editing session).
   - Developer A or B: T012 (import drop) after all migrations land.
3. Three developers can run T013 / T014 / T015 in parallel once T005–T011 are merged.
4. Developer C: US3 docs (T016 [P] + T017 [P]) starts as soon as T012 lands, followed by T018 grep verification.
5. Any developer: T019 → T020 → T021 polish sequence gates the merge.

---

## Notes

- Every migrated Mist call funnels through the existing multi-token 429 wrapper on `MistConnection`. T014 is the explicit smoke-test checkpoint that enforces this end-to-end; T029 from feature 001 established the code-review pattern that this feature reuses.
- No new file is created by this feature. Every change is in `mist_connection.py`, `app.py`, `README.md`, or `CHANGELOG.md`. `templates/index.html`, `pyproject.toml`, `requirements.txt`, and `.github/workflows/quality-gates.yml` are on the FR-012 do-not-touch list.
- No new caches are introduced. `MistConnection`'s in-memory caches are unchanged (plan § Technical Context).
- The `/summary-trend`-instead-of-`/summary` workaround and the device-scoped `wan_link_health` quirk are Why-line load-bearing — the docstring audit (T019) is the final check that they survive the migration verbatim.
- CSV column order is FIXED at exactly 12 columns in the documented order. T013 byte-diff and T021 smoke test both re-verify this.
- All docstring changes MUST comply with `~/.claude/DOCS.md` (≥90% coverage via `interrogate`, Google-style sections via `pydoclint`). This is enforced automatically by T020.
