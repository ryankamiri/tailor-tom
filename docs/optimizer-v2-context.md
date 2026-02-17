# TailorTom Optimizer V2 Context (Canonical)

## Purpose
This is the canonical context document for migrating TailorTom from Optimizer V1 to Optimizer V2.

This file exists to prevent context loss across agents and to explicitly capture where implementation
intentionally diverged from earlier planning language. It should be treated as the most up-to-date
product + architecture context for V2 optimizer work.

If a plan, ticket, or old comment conflicts with this file, this file is the source of truth.

---

## Why V2 Exists
V1 already has strong infrastructure and operational behavior:
1. Postgres as source of truth for jobs.
2. Celery worker execution with Redis as broker/cache.
3. Compile-and-verify safeguards for LaTeX layout constraints.
4. Correct ownership/cancel/delete behaviors in job APIs.

But V1 has clear quality/UX gaps:
1. Limited explainability ("why no changes?" is unclear).
2. Overly repetitive rewrite style (for example repeated leading verbs).
3. No first-class deterministic ATS scoring before/after optimization.
4. No robust user-visible optimization rationale artifact.
5. Token/cost controls are under-specified at optimizer-policy level.

V2 is intended to fix these gaps while preserving V1’s reliable execution and data architecture.

---

## Locked V2 Product Decisions
These decisions are considered settled unless explicitly changed in a future ticket.

1. Rollout mode: hard cutover.
2. Historical V1 compatibility: not required.
3. Existing V1 jobs: allowed to be deleted during migration reset.
4. Scoring approach: LLM-as-ATS primary scorer for baseline, per-pass, and final acceptance (Ticket 8.2). Static ATS module deprecated (reference only). Deterministic acceptance rule unchanged (`delta >= min_score_delta_to_accept`).
5. Optimization profile: economy mode by default.
6. Storage preference: expanded explicit columns for core V2 artifacts.
7. DOCX optimizer redesign: out of scope for this V2 optimizer migration.
8. No separate V2 on/off feature flag required for cutover.

---

## Current Architecture Context (What V2 Builds On)

### Backend execution path
1. `POST /api/optimize` creates DB job.
2. Worker receives `job_id`.
3. Worker loads job data from Postgres.
4. Optimizer runs and returns result.
5. Worker writes terminal state + result back to DB.
6. Redis cache-aside keys are invalidated on writes.

### Data and ownership model
1. Jobs are user-owned and DB-backed.
2. Job list/detail fetches are ownership-enforced.
3. Cancellation semantics are distinct from failure.
4. Job deletion semantics are explicit (`404/409/204` behavior).

### Frontend model
1. Jobs are API-backed, not localStorage-backed.
2. Token auth remains the only local-storage concern.
3. Job detail can render completed/failed/cancelled states.

---

## V2 Technical Intent (High-Level)
V2 optimizer should follow this shape:

1. Build deterministic resume representation (bullet-level constraints and structure).
2. Build deterministic job-description profile (weighted terms/themes).
3. Compute ATS score baseline (before optimization).
4. Select high-impact bullets under economy constraints.
5. Generate limited LLM candidates.
6. Rank candidates using deterministic criteria.
7. Apply coherence/factual checks.
8. Compile and verify layout constraints.
9. Compute ATS score final (after optimization).
10. Persist score delta + explanation artifacts to DB.
11. Expose analysis payload to frontend.

---

## Canonical V2 Job-Level Data Shape
The `jobs` table should include V2 analysis fields as explicit columns:

1. `optimizer_version`
2. `ats_score_before`
3. `ats_score_after`
4. `ats_score_delta`
5. `category_breakdown_before_text`
6. `category_breakdown_after_text`
7. `unchanged_reasons_text`
8. `coherence_warnings_text`
9. `optimization_explanation`
10. `optimization_warnings_text`
11. `llm_prompt_tokens`
12. `llm_completion_tokens`
13. `llm_estimated_cost_usd`

Guidance:
1. Core analysis data should remain in explicit columns.
2. JSONB may still be used in future tickets for complex trace payloads if strictly needed.
3. Column-first modeling is preferred for current V2 scope.

---

## Canonical Deviations from Original Ticket-1 Plan
The following are intentional and should be treated as accepted implementation decisions.

### 1. Naming convention deviation (no V2 prefix)
Original plan language proposed names like `V2_*` / `v2_*`.
Implemented names are neutral:
1. Config uses `economy_top_k`, `candidates_per_bullet`, `min_score_delta_to_accept`.
2. Constants use `ECONOMY_TOP_K`, `CANDIDATES_PER_BULLET`, `MIN_SCORE_DELTA_TO_ACCEPT`.

Implication:
Do not reintroduce `V2_` prefixes unless explicitly requested in a dedicated refactor.

### 2. Single economy K deviation
Original plan referenced separate knobs for:
1. rewrite target K
2. retry candidate K

Implemented:
1. Single `economy_top_k`/`ECONOMY_TOP_K` (default 8) reused for both concerns.

Implication:
Downstream tickets should assume one K knob unless product requests split control.

### 3. Token budget knob deviation
Original plan referenced separate:
1. per-job token cap
2. monthly token budget config

Implemented:
1. Reuse existing `max_tokens` model setting for token-limiting behavior.
2. No dedicated monthly token budget key exists yet.

Implication:
If monthly budget controls are required later, add them in a dedicated ticket with clear runtime enforcement policy.

### 4. V2 enable-flag deviation
Original plan mentioned a possible `V2_ENABLED` placeholder.
Implemented:
1. No such flag is present.
2. This matches hard-cutover policy.

Implication:
Do not assume runtime toggling capability exists.

### 5. constants.py overwrite incident and correction
What happened:
1. Initial update accidentally removed existing user limit/validation constants.
2. This was corrected.

Current expected state:
1. Existing validation/job-limit constants remain:
   - `DAILY_JOB_LIMIT`
   - `USER_SETTINGS_*` bounds
2. New economy optimizer knobs also exist alongside them.

Implication:
Future edits to `constants.py` must preserve both legacy validation constants and optimizer policy constants.

---

## Canonical Config/Constant Semantics (Current)

### Config (`tailor_tom/config.py`)
1. `economy_top_k`: top-K bullets considered in economy mode.
2. `candidates_per_bullet`: how many candidates the LLM generates per bullet per pass (min 1, max 6, default 2). This is the cap.
3. `min_score_delta_to_accept`: minimum score improvement threshold.
4. `max_tokens`: existing model response token limit (currently serving as token-budget control anchor).

### Constants (`tailor_tom/constants.py`)
1. Existing user settings bounds remain authoritative for profile/job validation.
2. `DAILY_JOB_LIMIT` remains authoritative for daily limit policies.
3. `ECONOMY_TOP_K`, `MIN_SCORE_DELTA_TO_ACCEPT` are optimizer policy defaults.
4. `CANDIDATES_PER_BULLET`: default for candidates per bullet when config is not set (default 2).

---

## Candidate-Centric Terminology (Ticket 3)

V2 optimizer uses **candidate-centric** language and control:

1. **Bullets and candidates**
   - **k** = number of selected bullets (from impact selector; capped by `economy_top_k`).
   - **n** = candidates per bullet = `candidates_per_bullet` (config/constant). How many candidates the LLM generates per bullet.
   - In one pass, target candidate count = **k × n**.

2. **Control**
   - **max_iterations** (user): number of **passes** (how many times we run generation per job).
   - **candidates_per_bullet** (config): how many candidates the LLM generates **per bullet** per pass (the cap).

3. **Outputs**
   - One selected candidate per bullet (or “unchanged” with reason).
   - Rejection reasons, coherence warnings, factual warnings, token usage, and estimated cost are carried in the decision bundle for DB and API compatibility.

---

## Factual and Coherence Policy (Ticket 3)

1. **Factual guard (hybrid)**
   - **Static gate (always)**: numeric anchor preservation, entity anchor preservation, key technical token retention, directional contradiction heuristics. Fails are rejected.
   - **LLM factual adjudication (conditional)**: only for borderline cases where the static gate marks “uncertain” (e.g. many new entities). Outputs pass/fail and short reason.

2. **Coherence review (conditional)**
   - Run only on: (a) top-ranked candidate per bullet, and/or (b) when risk heuristics trigger (e.g. heavy rewrite, uncommon phrase combinations, keyword-stuffing signals).
   - Do not coherence-check every candidate (cost/latency control).

### Ticket 8: Factual Guard False-Positive Reduction (Implemented)
- Entity anchors use precomputed IR anchors and exclude sentence-initial action verb stems (e.g. Built, Deployed, Led). Technical token comparison uses punctuation-aware normalization (e.g. loading/error, loading-error, loading error match). Numeric and directional checks unchanged.

### Ticket 8: Apply-Stage No-Op Classification (Implemented)
- **Problem**: Apply-stage showed many "apply failures" that were often no-op replacements (candidate LaTeX equal to original) or snippet mismatch, inflating failure counts and obscuring real issues.
- **Change**: Distinguish **no-op** (replacement equals original after normalizing LaTeX commands) from **snippet_not_found** (snippet not in current LaTeX) and **validate_reject** (length/constraint failure).
- **Implementation**: `latex_rewrite.is_noop_replacement(bullet, replacement_latex)`; `build_decision_bundle(..., original_latex_by_bullet)` marks no-op selections as unchanged with reason `"no-op (replacement same as original)"` and clears `selected_latex`. Orchestrator apply loop counts `noop_unchanged`, `snippet_not_found`, `validate_failures`, `applied_count`; debug log uses these instead of a single "apply_failures".
- **Result**: `apply_failures` no longer includes no-ops; applied-count metrics reflect real text modifications.

### Ticket 8: Ranking Calibration (Implemented)
- **Problem**: Soft-gain normalization added +0.5 to keyword/role-theme gain so unchanged candidates received artificial mid scores; restyle-only candidates could rank above ATS-improving ones.
- **Change**: (1) Remove inflation: keyword and role-theme gain use raw gain in [0, 1] (zero gain → 0). (2) Restyle-only penalty: if both keyword gain and role-theme gain are ≤ 0, subtract 0.08 from composite so candidates with no measurable JD/theme improvement rank lower. (3) Tie-break: prefer candidates with measurable JD-term gain (`keyword_gain > 0.01`) then fewer warnings, then lower expansion, then candidate_id.
- **Result**: Top-ranked candidates are more likely to improve ATS categories; fewer passes end with negative or flat ATS transitions.

### Ticket 8: Acceptance Stage Transparency (Implemented)
- **Policy**: Strict non-regression (`delta >= 0.0`) unchanged.
- **Revert explanation**: When revert triggers, `acceptance_warning` is set to a clear message: "Strict non-regression: best attempted edits did not improve ATS score (delta below threshold). Original kept; work was attempted but reverted so output shows no effective changes." Persisted in `optimization_warnings_text` and included in `optimization_explanation` so user-facing analysis shows that work was attempted but reverted, without implying system failure.

---

## Ticket 8.1: ATS Quality Recovery Under Strict Non-Regression (Implemented)

Strict acceptance revert (`delta >= 0.0`) remains **locked**. This ticket improves pre-acceptance quality so more jobs yield positive ATS deltas without changing when we revert.

### Gain-first ranking
- **Constants**: `MIN_GAIN_FOR_PRIORITY` (0.01), `STYLE_ONLY_PENALTY` (0.15), `NOOP_TEXT_PENALTY` (0.35) in `optimizer_v2/constants.py`.
- **CandidateScore**: Added `gain_eligible` (keyword_gain + role_theme_gain >= MIN_GAIN_FOR_PRIORITY) and `combined_gain` for tie-breaking.
- **Ranking**: Style-only candidates (zero keyword and zero theme gain) get a stronger penalty. Candidates whose rewritten_text is equivalent to original (no-op at text level) get a no-op penalty so they only win if no other valid candidate exists. Sort order: gain_eligible first, then higher combined_gain, then composite score, then fewer warnings, expansion, candidate_id.
- **Effect**: Top candidate per bullet is more likely to contribute ATS improvements instead of phrasing churn.

### Pass-history budget reallocation
- **Orchestrator**: Tracks per-bullet pass outcomes (`noop`, `unchanged`, `rejected`, `applied`) in `bullet_pass_history` and passes it to the impact selector on pass 2+.
- **Impact selector**: `select_impact_bullets(..., bullet_pass_history=...)`. Bullets with repeated non-productive outcomes (noop + unchanged >= 2) are deprioritized by subtracting `PASS_HISTORY_NONPRODUCTIVE_PENALTY` (0.25) from impact score so top-K slots reallocate to other editable bullets with unresolved ATS deficits. Deterministic and stable.
- **Effect**: Economy budget is not wasted on bullets that repeatedly produce non-improving output.

### Candidate diversity
- **Prompt**: Candidate 1 = conservative factual preservation / minimal edit; Candidate 2 = ATS-targeted with explicit JD term integration. Anti-duplication instruction: candidates for the same bullet must not be near-identical.
- **Parser**: `_dedupe_candidates_by_text` in `candidate_generator.py`: per bullet_id, keep first occurrence of each distinct normalized text; later duplicates are dropped (counted as `duplicate_text_suppressed` in debug).
- **Effect**: Higher chance at least one candidate has measurable ATS gain without increasing hallucination risk.

### Residual factual guard (entity normalization)
- Entity anchor comparison uses lowercase normalization so multi-token anchors (e.g. "Large Language Model", "Applied Transformer") match paraphrased casing in the candidate. Numeric and directional checks and uncertain adjudication flow unchanged.

### Diagnostic quality signals in analysis
- **Explanation text** (worker `_build_v2_explanation`): Adds `Quality signals: no_op_pct=X.` and when rejections exist `Reject pct: factual_reject_pct=X, coherence_reject_pct=Y.` so operators can see why "no effective changes" occurred. API shape unchanged; `threshold_revert` warning semantics preserved.

---

## Ticket 8.2: LLM-as-ATS Cutover (Implemented)

Runtime ATS scoring is performed by an **LLM judge** (LLM-as-ATS) end-to-end. The static ATS module remains in the codebase as **deprecated reference only** and is not used on the optimizer path.

### Decisions (locked)
1. **Scoring engine**: LLM-as-ATS is the primary scorer for baseline, per-pass evaluation, and final acceptance.
2. **Acceptance policy**: Unchanged strict non-regression (`delta >= min_score_delta_to_accept`).
3. **Custom sections rubric**: Six categories—Semantic Job Alignment (30), Evidence Fidelity (20), Impact Strength (15), Skill Coverage vs JD (15), ATS Parse Risk (10), Clarity and Brevity (10)—sum 100. Defined in `optimizer_v2/constants.py` as `ATS_LLM_CATEGORY_NAMES` and `ATS_LLM_CATEGORY_MAX_SCORES`.
4. **Failure policy**: If the ATS judge fails once and the single retry also fails, the job is marked **failed** with message "ATS judge failed after 1 retry." No fallback to static ATS. Constant: `ATS_JUDGE_MAX_RETRIES = 1`, `ATS_JUDGE_TIMEOUT_MS = 18_000`.
5. **Cost policy**: No per-job cap on ATS judge calls.
6. **Analysis payload**: New-shape only; frontend assumes the new category schema. Older jobs with legacy category payloads may show degraded/partial analysis (accepted).

### Implementation
- **`llm_ats_scoring.py`**: DSPy signature over resume summary (from `ResumeIR`) + JD payload (from `JDProfile` + raw excerpt). Returns `ATSScoreResult` (same shape as before). Parse/validate/clamp category scores; retry once on parse/judgment error; then raise `ATSJudgeError`.
- **Orchestrator**: All scoring calls use `score_resume_against_jd_llm(...)` (baseline, pass score, post-apply pass score, final). Debug events: `ats_judge_call_start`, `ats_judge_raw_output_meta`, `ats_judge_raw_output_text` (gated by `optimizer_debug_raw_text`), `ats_judge_parse_result`, `ats_judge_retry`, `ats_judge_failure_terminal`, `ats_score_transition`, `acceptance_check` / `acceptance_revert` with `source="llm_ats"`.
- **Static ATS**: `ats_scoring.py` has module-level docstring: reference only; no runtime use in V2 scoring path. Exported symbol kept for compatibility, documented as deprecated.
- **Worker**: Catches `ATSJudgeError`; sets job status to `failed` with message "ATS judge failed after 1 retry." and uses existing terminal failure flow.

---

## Ticket 9A: Global One-Pass LLM-as-ATS Bundle Chooser (Implemented)

The runtime optimization path uses a **global one-pass bundle chooser** by default instead of a multi-pass loop. The chooser evaluates bullet-option bundles in full resume context and returns the **highest ATS-scoring observed state** (including the original resume as a candidate). No later step can overwrite a previously better state.

### Decisions (locked)
1. **Best-state policy**: Final returned resume is the highest ATS-scoring among original baseline and all ATS-scored bundles explored by the chooser.
2. **No extra final ATS re-score** after winner selection (avoids variance replacing a known-best state).
3. **`max_iterations`** remains in request/settings/DB but means **search budget**, not pass count. It drives coarse pool cap and fine eval cap: `coarse_pool_cap = min(CHOOSER_MAX_BUNDLE_POOL, 80 + max_iterations*40)`, `fine_eval_cap = min(CHOOSER_MAX_FINE_EVALS, 4 + max_iterations*2)`.
4. **Candidate-level feasibility** (compile + line-count per candidate on original context) runs before bundle ATS scoring.
5. **Strict non-regression** acceptance unchanged: if best observed delta < threshold, return original and set `acceptance_warning`.

### Flow (chooser path)
1. Compile original, build `ResumeIR`, `JDProfile`, baseline ATS once.
2. Select impact bullets once (no pass-history in this ticket).
3. Generate candidates once; run factual gate and coherence review.
4. Run **candidate feasibility prefilter** (`candidate_feasibility.py`): validate_replacement, apply single replacement, compile, verify_line_counts; mark infeasible and exclude from bundle pool.
5. Build **options per bullet**: always include original; add only feasible, gate-passed candidates.
6. **Bundle chooser** (`bundle_chooser.py`): coarse generation and pruning by deterministic composite aggregation and penalties; shortlist top bundles; **fine ATS scoring** for each shortlisted bundle (and baseline); track best state.
7. Apply chosen bundle to original LaTeX; compile and quality checks; apply acceptance gate; persist.

### Rollout
- **Default**: Chooser path is used when `use_chooser_path` is True (default). Legacy pass loop remains behind `use_chooser_path=False` for comparison/shadow.
- **Persistence**: Chooser diagnostics (options_evaluated, feasible_count, infeasible_count, bundle_pool_count, fine_evals, selected_source) are stored in `chooser_diagnostics` on `V2OptimizationResult` and included in `optimization_explanation` by the worker.

### API/settings semantics
- **max_iterations**: Described as "Optimization search budget" in API models; frontend label "Optimization search depth" with help text aligned to search budget meaning.
- **Analysis**: New-shape only; no structural change to job detail analysis payload.

---

## Feasibility recovery and diagnostics (chooser path)

Improvements to candidate feasibility and explainability while keeping the one-pass chooser architecture.

### Length validation
- **Pre-filter**: Replacement validation allows a small character growth before compile/line-count checks. Config key `optimizer_max_char_growth` (default 10) is the active runtime guard. Word-count no-growth rule and compile + line-count verification remain hard gates.
- **Effect**: Fewer early rejects from minor character overages; more candidates reach layout verification.

### Snippet-apply diagnostics
- **Structured failure reasons**: Apply-stage failures are classified into sub-reasons instead of a single "snippet_not_found" bucket: e.g. snippet missing in source, no-effect replacement, apply failed after prior mutation (pass2). Debug events carry per-candidate diagnostics (snippet found in original, noop flags, lengths, short hashes, stage).
- **Aggregate event**: A detailed breakdown event reports counts by reason and by bullet_id for diagnosis. No fuzzy snippet matching is introduced; diagnostics inform whether fallback matching is justified later.

### Targeted repair pass (single retry)
- **Trigger**: Run once per job in the chooser path after initial feasibility, only when there are infeasible candidates and at least one selected bullet has no feasible non-original option.
- **Eligibility**: Failures due to length-related rejects, line-count mismatch, no-effect replacement, or compile failure are eligible for repair. Snippet-missing-in-source and apply-failed-after-prior-mutation are excluded (diagnostic-only for the former).
- **Contract**: A dedicated repair DSPy signature produces one repaired candidate per failed input; output is strict JSON list. Repaired candidates are re-run through factual gate, coherence review, deterministic ranking, and feasibility prefilter, then merged into the option pool before bundle chooser scoring.
- **Caps and safety**: Hard cap on repaired candidates per job (e.g. 8); one repair attempt only. If the repair call fails, the job does not fail—repairs are skipped (fail-open).

### Observability
- **chooser_diagnostics** is extended with: candidates_generated, factual_rejects_total, coherence_rejects_total, feasibility_reason_histogram, bullets_with_zero_feasible_non_original, repair_attempted, repair_accepted, plus existing options_evaluated, feasible/infeasible counts, bundle_pool_count, fine_evals, selected_source.
- **optimization_explanation** (worker-built string) includes full-funnel counts from chooser_diagnostics so analysis text matches pipeline events (generated, rejected by factual/coherence/feasibility, repair attempted/accepted, bullets with zero feasible non-original).

---

## Ticket 4: Worker Cutover and API Exposure (Implemented)

1. **Runtime**: Celery worker runs the V2 orchestrator (`optimize_resume_v2`) instead of V1 `optimize_resume`. DSPy candidate generation is used via `llm_candidate_caller`.
2. **Orchestrator**: Pass-by-pass loop (max_iterations), compile/quality checks, acceptance threshold (`min_score_delta_to_accept`). Cancellation is checked between passes.
3. **Persistence**: All V2 analysis columns are written on completion/failure from the orchestrator result (serialized via `serialize_category_breakdown`, `serialize_decision_bundle_for_db`).
4. **API**: Job detail response includes raw V2 fields and a parsed `analysis` object (score before/after/delta, category breakdowns, reasons, warnings, token usage). Malformed stored JSON is handled with a safe fallback and `analysis_parse_failed` flag.

---

## Ticket 5: V2 Backend Completion (Quality + Guard Rails, Implemented)

1. **Factual adjudication**: `llm_factual_adjudicator.py` runs DSPy judge-only for uncertain static outcomes. Fail-open policy: on failure after one retry, candidate passes with reason `uncertain_unadjudicated_fail_open`. Per-pass cap: `FACTUAL_ADJUDICATION_MAX_PER_PASS`.
2. **Coherence review**: `llm_coherence_checker.py` runs DSPy for top/risk-flagged candidates (linguistic coherence, semantic plausibility, keyword-stuffing). Per-pass cap: `COHERENCE_REVIEW_MAX_PER_PASS`.
3. **Orchestrator**: LLM adjudication and coherence check enabled; token usage aggregated from candidate generation, factual adjudication, and coherence calls. Constants in `optimizer_v2/constants.py`: `FACTUAL_ADJUDICATION_MAX_PER_PASS`, `COHERENCE_REVIEW_MAX_PER_PASS`, `ALLOW_UNCERTAIN_FAIL_OPEN=True`.
4. **Explanation**: Worker builds richer `optimization_explanation` (ATS delta, rewrite summary, guard counts, quality outcome). Warning categories normalized: `factual_reject`, `factual_uncertain_fail_open`, `coherence_reject`, `format_reject`, `threshold_revert` in serialization and DB payload.

---

## Ticket 6: V2 Analysis UX + Admin Cost Analytics (Implemented)

1. **Job detail analysis UX**: Frontend shows parsed V2 analysis on `/jobs/[jobId]` for completed/failed jobs only. `JobAnalysisPanel` displays ATS score summary (before/after/delta), category breakdowns, optimization explanation, unchanged reasons, optimization/coherence warnings. Token and cost are not shown to end users. Delta copy: positive → "ATS alignment improved"; zero → "No material ATS score change"; negative → "Optimization reverted or no safe improvement accepted". `analysis_parse_failed` shows a non-blocking notice.
2. **Admin cost analytics**: New endpoint `GET /api/admin/user-costs` (admin-only) returns per-user cost: lifetime total and selected UTC calendar month total. Response includes `month` (year, month, utc_start, utc_end_exclusive), `summary` (lifetime_total_cost_usd, month_total_cost_usd, users_with_cost_count), and `users[]` with per-user rows. Cost basis: any job with `llm_estimated_cost_usd > 0`. Frontend admin page: UTC month selector, summary cards, per-user table. Currency display: 2 decimals when ≥ $1, else 4 decimals.
3. **No change**: `/api/jobs` list payload unchanged. Job detail contract backward compatible.

---

## Ticket 6.5: Redis Caching for Admin Cost Analytics + Admin List Pagination (Implemented)

1. **Admin user-costs cache**: Redis cache-aside for `GET /api/admin/user-costs`. Key: `cache:admin:user-costs:year:{YYYY}:month:{MM}:page:{P}:limit:{L}` (month zero-padded). TTL 15 minutes. Invalidate on any job write (status update, delete) via shared `on_job_write_invalidate()` so admin cost cache is cleared whenever job data affecting totals changes. Fail-open on Redis errors.
2. **Admin user-costs pagination**: Query params `page` (default 1), `limit` (default 20, max 100). Response includes `pagination` (page, limit, total_items, total_pages, has_next, has_prev). Users array is the current page only. Sort in SQL: `month_cost_usd DESC`, `total_cost_usd DESC`, `user_id ASC`.
3. **Admin resumes pagination**: `GET /api/admin/resumes` accepts `page` and `limit`; response includes `resumes` (current page) and `pagination`. No Redis cache for resumes.
4. **Frontend**: Independent pagination state for cost and resumes; pager controls per section; month/year change resets cost page to 1; Refresh re-fetches current pages for both.

---

## Ticket 7: V2 Completion, Hardening, and Targeted Refactor (Implemented)

1. **Admin cost cache invalidation**: All job write paths (route-level cancel/delete in `jobs.py`, storage `update_job_status` and `delete_job`) call a single helper `on_job_write_invalidate(user_id, job_id)` which invalidates job/list/profile caches and admin user-costs cache. No direct route-level cache calls for job writes.
2. **Admin cost query scalability**: Pagination and ordering moved into SQL. Combined CTE from lifetime and month aggregates with `coalesce` for month; one count query, one sum query for summary totals, one paged query with `ORDER BY ... OFFSET ... LIMIT`. Cache key and 15-min TTL unchanged.
3. **Backend refactor**: `cache_get_or_set_dict(get_fn, set_fn, producer, *key_args)` in `api/cache.py` for cache-aside. `api/validation.py`: `validate_admin_utc_month(year, month)` and `validate_pagination(page, limit, max_limit)`. Admin user-costs route uses cache helper and validation; same HTTP semantics (422 for invalid params).
4. **Optimizer V2 shared LLM utils**: `tailor_tom/optimizer_v2/llm_utils.py` provides `estimate_usage()`, `usage_from_lm()`, `normalize_judgment()`, `normalize_reason()`. `llm_candidate_caller`, `llm_factual_adjudicator`, `llm_coherence_checker`, and `decision_bundle` use these; duplicate cost/judgment/reason logic removed.
5. **Worker refactor**: `_now_utc_iso()`, `_build_default_failure_result(job, ...)`, `_process_memory_cleanup()` in `worker/tasks.py`. Terminal failure payloads and timeout/exception branches use the default result helper; both optimize and DOCX tasks call `_process_memory_cleanup()` in `finally`. Cancelled-job protection and sync user job counts unchanged.
6. **Frontend refactor**: `frontend/lib/formatting.ts`: `formatLocalDateSafe(iso, fallback)`, `formatUsdCompact(usd)`. `frontend/components/admin/pagination-controls.tsx`: reusable pager for cost and resumes. `frontend/lib/api.ts`: `parseErrorDetail(res, fallback)`, `assertOkOrThrow(res, options)`; admin API methods use them. Admin page and admin resume page use formatting and pagination components; no consumer-facing type or contract changes.

---

## Post–Ticket-7 Assumptions (Canonical)

1. **V2 flow**: Fully DB-backed; job detail exposes analysis; admin has cost analytics and paginated lists.
2. **Cache**: Admin user-costs cached 15 min; invalidated on every job write via `on_job_write_invalidate`. Fail-open on Redis.
3. **Admin cost query**: Pagination and sort in SQL; response schema unchanged.
4. **No further required V2 code tickets**: Remaining work is optional enhancement (e.g. monthly token budget, extra analytics). Correctness and scalability gaps addressed in Tickets 6, 6.5, and 7.

---

## Non-Goals (still locked)
1. No backward compatibility for historical V1 job rows.
2. No V2 feature-flag rollout model.
3. No DOCX optimizer architecture migration inside this V2 effort.

---

## Contributor note: docstrings, comments, and log text

Do not reference issue or ticket numbers (e.g. "Ticket X", "ticket N") in docstrings, comments, or log messages. Use functional descriptions instead so that code remains self-explanatory and independent of external tracking. As an optional pre-merge check, search touched files for patterns like `Ticket [0-9]` or `ticket [0-9]` and remove or rephrase any matches.

---

## Change-Control Rule for This Doc
When implementation deviates from prior plans, update this file in the same PR (or immediately after)
with:
1. what changed,
2. why it changed,
3. what downstream tickets should assume.

This document should remain a living, implementation-grounded context artifact, not just a static plan copy.

---

## V2 Completion Checklist (Post–Ticket-7)

1. **V2 flow**: Fully DB-backed; user-facing job detail shows analysis panel for completed/failed jobs; token/cost hidden from end users.
2. **Admin analytics**: Cached and paginated; UTC month selector; per-user cost table and resume list each have independent pagers.
3. **Duplication**: Major repeated logic in scoped modules (api routes, optimizer_v2 LLM callers, worker tasks, frontend admin) consolidated into shared helpers/components.
4. **Future work**: Optional enhancements only (e.g. monthly budget, extra metrics); no required correctness or scalability fixes left for V2 rollout.
