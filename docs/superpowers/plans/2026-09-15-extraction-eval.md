# Extraction Eval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (inline execution) to implement this plan task-by-task.

**Goal:** Add a privacy-preserving evaluation harness that measures the quality of `curator-save` extraction separately from storage and improve-loop evaluation.

**Architecture:** Keep transcripts and gold labels as local evaluation data. Store only a schema, evaluator, deterministic tests, and anonymized fixtures in the repository. The evaluator reads gold knowledge items and model predictions, matches them by explicit IDs or normalized titles, and reports precision, recall, evidence support, abstraction, noise, and atomicity.

**Tech Stack:** Python 3.12+, standard library JSON/CSV, pytest.

## Global Constraints

- Do not add an LLM call to the Python backend; extraction remains in the agent skill.
- Do not commit private session transcripts, personal knowledge, API tokens, or databases.
- Keep `eval_runner.py` unchanged; it evaluates stored-base mutations, not extraction.
- Preserve the existing `curator-save` candidate contract.
- Follow the repository's existing Python and pytest conventions.

---

### Task 1: Add the extraction-eval data contract

**Files:**
- Create: `benchmark/extraction/README.md`
- Create: `benchmark/extraction/schema.json`
- Test: `core/tests/unit/test_extraction_eval_schema.py`

**Interfaces:**
- A corpus is a JSON object with `sessions`.
- Each session has `id`, `transcript`, and `gold`.
- Each gold item has `id`, `type`, `title`, `summary`, `evidence`, `scope`, and `should_save`.
- Predictions are JSON objects with `session_id` and existing candidate fields.

- [x] Define the local-only corpus format, including the rule that transcript files are ignored by git.
- [x] Document the annotation rules for positive and negative items and the meaning of each metric label.
- [x] Add a JSON Schema that validates corpus metadata and gold annotations without requiring real transcript content in git.
- [x] Add tests for a valid anonymized corpus and rejection of missing session IDs, missing gold IDs, and invalid `should_save` values.

### Task 2: Implement deterministic candidate matching and metrics

**Files:**
- Create: `benchmark/extraction/evaluator.py`
- Test: `core/tests/unit/test_extraction_evaluator.py`

**Interfaces:**
- `load_records(path: str) -> list[dict]`
- `match_predictions(gold: list[dict], predictions: list[dict]) -> MatchResult`
- `calculate_metrics(result: MatchResult) -> dict[str, float]`
- `render_report(metrics: dict[str, float], result: MatchResult) -> str`

- [x] Add a result model that records matched gold items, unmatched gold items, unmatched predictions, and error labels.
- [x] Match only within the same session; use an explicit `gold_id` when present and normalized title matching as the fallback.
- [x] Ensure one prediction cannot match multiple gold items and one gold item cannot match multiple predictions.
- [x] Calculate precision and recall from matched positive items, excluding `should_save=false` items from recall.
- [x] Calculate evidence support, abstraction, and atomicity rates from evaluator annotations on predictions; do not pretend to infer these semantically in Python.
- [x] Calculate noise rate from explicit prediction error labels.
- [x] Render a stable human-readable report with counts and percentages.
- [x] Test perfect match, missed knowledge, extra noise, duplicate predictions, cross-session mismatch, and zero-item edge cases.

### Task 3: Add a command-line baseline runner

**Files:**
- Create: `benchmark/extraction/run_eval.py`
- Modify: `benchmark/extraction/README.md`
- Test: `core/tests/unit/test_extraction_eval_cli.py`

**Interfaces:**
- Command: `python3 benchmark/extraction/run_eval.py --gold GOLD.json --predictions PREDICTIONS.json --report REPORT.md`
- Exit code `0` for a valid report; exit code `2` for invalid input.

- [x] Parse the three required paths with `argparse`.
- [x] Validate both JSON inputs before evaluation and print a concise validation error to stderr.
- [x] Write the deterministic report to the requested path using UTF-8.
- [x] Keep the command independent from `curator` package imports so it can run without the development virtualenv.
- [x] Test successful report generation and invalid JSON handling.

### Task 4: Create an anonymized smoke corpus and baseline example

**Files:**
- Create: `benchmark/extraction/fixtures/smoke_gold.json`
- Create: `benchmark/extraction/fixtures/smoke_predictions.json`
- Create: `benchmark/extraction/results/smoke-report.md`
- Modify: `benchmark/extraction/README.md`

**Interfaces:**
- The smoke corpus contains no real project names, paths, code, or personal data.
- The example demonstrates one reusable rule, one task-specific detail, and one missed rule.

- [x] Add a small anonymized fixture with explicit positive and negative labels.
- [x] Add predictions representing the current baseline failure modes: task residue accepted and a reusable rule missed.
- [x] Run the CLI against the fixtures and record the generated report.
- [x] Document that the smoke fixture validates the harness only; it is not evidence about model quality.

### Task 5: Define the real-session baseline workflow

**Files:**
- Modify: `benchmark/extraction/README.md`
- Create: `benchmark/extraction/ANNOTATION-TEMPLATE.json`

**Interfaces:**
- Local session export is created with `read_opencode_session` or an equivalent local-only command.
- Predictions are captured from the unchanged `curator-save` skill.
- Gold labels and predictions use the schemas from Tasks 1-2.

- [x] Document how to select a balanced development set and holdout set from `list_opencode_sessions` without committing transcripts.
- [x] Document the annotation pass: positive knowledge, evidence span, scope, type, and negative candidates.
- [x] Document the exact baseline prompt conditions and model identifier for reproducibility.
- [x] Document the error taxonomy: task residue, hypothesis, weak evidence, wrong scope, duplicate, compound fact, and missed knowledge.
- [x] Document the rule that skill changes are evaluated on the development set first and the holdout set only after selecting a candidate revision.

### Task 6: Verify and report the first harness result

**Files:**
- Modify: `benchmark/extraction/README.md`
- Modify: `docs/superpowers/specs/2026-09-15-extraction-eval-design.md`

- [x] Run the extraction evaluator unit tests.
- [x] Run the smoke CLI evaluation.
- [x] Inspect the report for correct counts and percentages.
- [x] Record which parts are verified by deterministic tests and which require real-session annotation/model runs.
- [x] Run a controlled holdout comparison after selecting the candidate revision.
- [x] Keep the result scoped to the small annotated corpus; do not claim production-quality improvement.
