# Extraction Eval Design

## Goal

Measure and improve how `curator-save` extracts reusable knowledge from a session. The first iteration evaluates the agent skill, not the storage backend or the improve loop.

## Scope

The evaluation covers the path:

```text
session transcript -> curator-save extraction -> candidate facts -> human-labelled reference
```

It does not change the MCP contract, `Gatekeeper`, persistence, retrieval, or automatic session mining in the first iteration.

## Evaluation Corpus

Use a local, privacy-preserving corpus of real OpenCode sessions covering coding, debugging, review, architecture, documentation, and workflow discussions. Session transcripts and labels stay outside git unless explicitly anonymized.

Each session receives a gold annotation containing:

- reusable knowledge that should be saved;
- an evidence span supporting each item;
- the intended type and scope;
- negative examples that should not be saved.

## Candidate Contract

The evaluated prediction uses the existing candidate shape:

```json
{
  "type": "Reference",
  "title": "...",
  "content_summary": "...",
  "tags": ["..."],
  "evidence": "..."
}
```

The evaluator adds no semantic fields to production candidates. Matching and error analysis remain evaluation-only.

## Metrics

- Candidate precision: useful candidates divided by all predicted candidates.
- Knowledge recall: matched gold knowledge items divided by all gold items.
- Evidence support rate: candidates whose evidence actually supports the summary.
- Abstraction rate: candidates transferable beyond the source task.
- Noise rate: candidates that are task residue, hypotheses, duplicates, or project-only details.
- Atomicity rate: candidates containing one reusable idea rather than several merged ideas.

The existing `eval_runner.py` remains unchanged. It evaluates mutations of the stored knowledge base, while this eval evaluates extraction before storage.

## Experiment

1. Annotate a small development set and a holdout set.
2. Run the current `curator-save` skill unchanged and record its candidates.
3. Classify false positives and false negatives.
4. Test revised skill instructions against the same development set.
5. Select the smallest change that improves precision and recall without increasing noise.
6. Validate the selected skill on the holdout set.

## Expected First Finding

The current skill specifies inclusion and exclusion rules and output formatting, but does not require a fixed reasoning sequence for verifying evidence, abstraction, scope, and transferability. The eval must confirm or reject this hypothesis before changing implementation code.

## Initial Implementation Status

The repository now contains a deterministic evaluator, JSON Schema, annotation
template, CLI runner, and an anonymized smoke fixture. The smoke fixture is
verified by unit tests and reports 50% precision and 50% recall by design. No
claim about the current model's real extraction quality is made until private
real-session annotations and baseline predictions are collected.

The first private development baseline used six local sessions and 17
skill-following predictions. It matched 10 positive gold items out of 14
(`precision 58.8%`, `recall 71.4%`) and labelled 41.2% of predictions as noisy
or uncertain. A stricter revision reached 100% precision and 0% noise but
reduced recall to 64.3%, so it was rejected as over-filtering. The next revision
was rerun against the same corpus after the capture-contract migration and
preserved the development result (`precision 100.0%`, `recall 64.3%`, `noise
0.0%`). A separate controlled holdout run on three independent sessions matched
3/3 positive items (`precision 100.0%`, `recall 100.0%`, `noise 0.0%`). This is
evidence for the candidate on a small corpus, not a production-quality claim.
