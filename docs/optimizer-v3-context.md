# TailorTom Optimizer V3 Context (Canonical)

## Purpose
This document defines the canonical architecture for Optimizer V3.

V3 is an extension of V1 with selected feasibility mechanics from V2.
It is designed to keep V1's practical iterative repair loop while adding:
1. Multiple candidates per bullet (`n` candidates).
2. Batch compile-aware feasibility to reduce compile calls.
3. A final holistic DSPy chooser over validated options.

If planning notes or comments conflict with this file, this file is the source of truth.

---

## Product Decision Summary (Locked)
These decisions are explicitly confirmed and should be treated as locked for initial V3 implementation.

1. V3 is a new optimizer path and should be implemented as an extension of V1 behavior.
2. V1 bullet-selection eligibility rules remain unchanged:
   1. Same section eligibility rules.
   2. Same minimum-word rule.
3. Stage 1 generation uses V1-style generation semantics but outputs `n` candidates per eligible bullet.
4. `n = 2` for initial rollout.
5. Stage 2 uses two-pass feasibility:
   1. Pass 1 static per-candidate checks (no compile).
   2. Pass 2 slot-based compile checks (batch compile strategy).
6. Stage 2 retries use V1-style iterative feedback regeneration:
   1. Regenerate only failed candidates.
   2. Keep already-feasible candidates.
7. No V2 factual guard or coherence review in V3.
8. Stage 3 chooser is the sole authority for final bullet selection.
9. Baseline/original bullet option is allowed in chooser.
10. If any bullet has zero feasible non-original candidates after max iterations, the job fails before Stage 3.
11. V3 code should live under a dedicated optimizer v3 package.
12. Backend V2 optimizer logic has been removed; V3 is now the active architecture target.
13. V3 must track per-job LLM usage and cost statistics (prompt tokens, completion tokens, estimated cost, usage-source) as statistics output.

---

## Core Vocabulary
1. `k`: number of eligible bullets (from V1 eligibility rules).
2. `n`: candidates generated per eligible bullet (`n=2` initially).
3. `j`: number of candidate bullets, `j = k * n`.
4. Total options entering chooser: `k originals + j candidates = k * (n + 1)`.
5. `slot`: candidate index shared across bullets. With `n=2`, slot1 means each bullet's first candidate, slot2 means each bullet's second candidate.
6. `max_iterations`: maximum Stage 2 retry rounds.

---

## Architecture Overview
V3 executes in three stages.

1. Stage 1: Candidate Generation (V1-extended, n-per-bullet).
2. Stage 2: Candidate Validation (two-pass + iterative feedback).
3. Stage 3: Holistic Candidate Chooser (DSPy selection over validated options).

Output is the selected optimized resume LaTeX, or job failure when feasibility requirements are not met.

---

## Stage 0: Shared Preprocessing
Before Stage 1, V3 should perform the same baseline setup style as V1.

1. Compile original LaTeX.
2. Extract bullet constraints and stable bullet IDs.
3. Determine editable bullets using V1 eligibility logic.
4. Build the "original option" set for each eligible bullet.

If compile fails here, fail the job.
If no eligible bullets, complete with original resume (no-op success).

---

## Stage 1: Candidate Generation (V1 Extended)

### Goal
Generate `n` factual rewrite candidates per eligible bullet while preserving V1 strategy and constraints orientation.

### Input
1. Job description.
2. Eligible bullet constraints (from Stage 0).
3. Optional per-bullet failure feedback from Stage 2 retries.

### Behavior
1. Keep V1 optimization style and replacement mindset.
2. Extend output contract to emit multiple candidates per bullet.
3. Candidate IDs must be deterministic and stable.

Recommended ID scheme:
1. Original option: `b{bullet_id}_orig`.
2. Generated options: `b{bullet_id}_c{candidate_index}_it{iteration}`.

### Contract Change vs V1
V1 emitted one replacement per bullet.
V3 generator should emit a list for each bullet with exact cardinality `n` per generation call, subject to parse safety.

Minimal JSON row:
1. `bullet_id` (int)
2. `candidate_index` (1..n)
3. `replacement_latex` (string)

Optional metadata can be added later but should not block initial rollout.

### Output
Per iteration:
1. Candidate set for targeted bullets in that iteration.
2. Parse diagnostics for malformed/missing rows.

---

## Stage 2: Candidate Validation (Two-Pass + Iterative Retry)

## Stage 2.1 Pass 1 (Static, Per-Candidate, No Compile)
Pass 1 rejects impossible candidates before compile.

Checks (locked):
1. Word growth must not exceed original (`candidate_words <= original_words`).
2. Character growth max `+10`.
3. Shrink limits same as V1:
   1. `max_shrink_words = 3`
   2. `max_shrink_percent = 0.15`
4. Snippet apply check against source LaTeX context for that bullet.

Pass/fail reason codes should be explicit (for retry feedback and diagnostics):
1. `too_long_words`
2. `too_long_chars`
3. `too_short_words`
4. `too_short_percent`
5. `snippet_not_found`
6. `apply_no_effect`
7. `invalid_payload`

## Stage 2.2 Pass 2 (Slot-Based Compile Validation)
Pass 2 is compile-constrained and must minimize compile count.

Slot strategy:
1. For each slot `s in [1..n]`, build one test LaTeX by applying each bullet's slot-`s` candidate that survived Pass 1.
2. Compile once for the slot.
3. Verify line counts for each changed bullet.
4. If a bullet fails line-count in slot `s`, fail only that bullet's slot-`s` candidate.
5. Do not fail all bullets in that slot when one bullet fails.

This preserves compile efficiency while avoiding over-penalizing unrelated bullets.

## Stage 2.3 Iterative Retry Loop (V1-Style)
V3 retry behavior is explicitly V1-like.

Loop:
1. Run Stage 1 + Stage 2 for the current set of unresolved failures.
2. Regenerate only failed candidates with specific failure feedback.
3. Keep accepted feasible candidates untouched.
4. Stop early if every bullet has at least one feasible generated candidate.
5. Stop when `max_iterations` reached.

### Hard Failure Rule Before Stage 3
After the final iteration:
1. If any eligible bullet has zero feasible generated candidates, fail the job.
2. Do not proceed to Stage 3 in this case.

Rationale:
Stage 3 requires a complete, validated option surface for holistic choice.

---

## Stage 3: Holistic DSPy Candidate Chooser

### Goal
Select one option per bullet holistically, considering interactions across all bullets.

### Input Surface
For each bullet, chooser receives:
1. Original option.
2. All feasible generated options from Stage 2.

Chooser therefore sees exactly the validated option lattice and can choose original where appropriate.

### Chooser Contract (Initial)
Keep output minimal and deterministic.

Per row:
1. `bullet_id` (int)
2. `chosen_option_id` (string), where option is one of:
   1. `b{bullet_id}_orig`
   2. `b{bullet_id}_c{idx}_it{iter}`

No rationale fields required in initial contract.

### Authority
1. Chooser is sole decision authority.
2. No external ATS rescoring gate in V3 acceptance path.

### Apply
1. Apply selected options to original LaTeX.
2. Compile final output.
3. Run final layout quality checks.
4. Return success if compile and quality pass.

If final compile fails unexpectedly:
1. Return failed job (do not silently degrade correctness).

---

## Runtime and Performance Model
V3 runtime should emphasize compile minimization.

1. Pass 1: zero compiles.
2. Pass 2: at most `n` compiles per iteration (slot compiles).
3. Iteration count bounded by `max_iterations`.
4. Total compile envelope approx:
   1. `1` baseline compile
   2. `max_iterations * n` slot compiles
   3. `1` final compile

With `n=2`, this is practical and bounded while still validating all candidates.

---

## Data and Diagnostics Requirements
V3 should emit transparent diagnostics for each stage.

Minimum diagnostics:
1. Eligible bullet count `k`.
2. Generated candidate count `j`.
3. Per-iteration pass1 fail reasons histogram.
4. Per-iteration pass2 line-count fail histogram.
5. Per-bullet feasible option counts after each iteration.
6. Early-stop vs max-iteration-stop reason.
7. Final chooser selected option IDs.
8. Final changed bullet count.
9. Per-job token/cost statistics:
   1. Prompt tokens.
   2. Completion tokens.
   3. Estimated USD cost.
   4. Usage source (`actual` vs `estimated`).

These are required to debug "why no changes" and "why failed before chooser."

---

## Comparison to Existing Systems

## Relative to V1
Keeps:
1. Iterative feedback loop and practical constraints orientation.
2. Core bullet extraction and eligibility behavior.

Adds:
1. Multi-candidate generation per bullet.
2. Slot-based compile feasibility for efficiency.
3. Holistic final chooser.

## Relative to V2
Keeps:
1. Two-pass feasibility concept.
2. Bundle-level holistic selection concept.

Removes:
1. Factual guard.
2. Coherence review.
3. LLM-as-ATS acceptance loop and ATS non-regression gating.
4. Multi-pass ATS scoring complexity.

---

## Repository Layout (Current)
1. V3 package: `backend/tailor_tom/optimizer/v3/` (orchestrator, stages, types, debug, llm_usage).
2. V1 remains at `backend/tailor_tom/optimizer/v1/` (unchanged).
3. Worker calls V3 orchestrator; persisted analysis is V3-only (analysis_json, llm_usage_source).

---

## Persisted Analysis Contract (V3-Only)
Job analysis is stored in `jobs.analysis_json` (JSONB). Token/cost fields `llm_prompt_tokens`, `llm_completion_tokens`, `llm_estimated_cost_usd`, and `llm_usage_source` are kept. No legacy V2 ATS/text columns; all analysis is V3-native.

---

## Implementation Constraints and Guardrails
1. Comments/docstrings should describe behavior, not ticket IDs.
2. Initial chooser output should stay simple to reduce parser fragility.

---

## Open Design Notes (Non-Blocking)
These are intentionally deferred and should not block first V3 implementation.

1. Whether to include optional chooser rationale in a later schema version.
2. Whether to expose per-bullet chooser confidence in analysis UI.
3. Whether to increase `n` beyond 2 after benchmark validation.

---

## Acceptance Criteria for Initial V3 Milestone
V3 initial milestone is complete when:

1. Stage 1 generates `n=2` candidates per eligible V1 bullet.
2. Stage 2 validates with:
   1. Pass 1 static constraints (including `+10` char cap),
   2. Pass 2 slot compile line-count checks,
   3. V1-style failed-only feedback regeneration up to `max_iterations`.
3. Jobs fail before Stage 3 if any bullet has zero feasible generated candidates.
4. Stage 3 chooser selects one option per bullet from validated options.
5. Final output compiles and passes quality checks.
6. Diagnostics clearly explain failures and selected options.
