# 013. Retrieval evaluation with a fictional twin of the private set

- **Status:** Accepted
- **Date:** 2026-11-26

## Context

"It works" is not a measurement. The server's job is narrow and testable: given a query and a caller's scope, return the right records, with the right status, and nothing from outside the scope. Whether the client model then answers well is a separate question that depends on the model.

The real evaluation questions are about real health records, so they can't be public. Without a public evaluation, the claim of quality can't be checked.

## Decision

- **A fictional set in the repository.** `eval/cases.fictional.yaml` mirrors the categories of the private set: encounters, prescription vs actual use, exams, pending data, questions with no answer, and scope. It runs against the fictional records in `examples/records`.
- **What each case can check:**
  - every expected record appears in the top 5 (`expected_ids`);
  - nothing is found when nothing should be (`expect_empty`);
  - expected records carry the right review status (`expected_status`);
  - some event types must not appear (`forbid_types`), for example no `medication_use` for a vitamin that was only prescribed;
  - **no result falls outside the caller's scope.** This is checked on every case.
- **Metrics:**
  - gating cases passed;
  - scope violations;
  - mean reciprocal rank (MRR) of the first expected record.
- **The run fails** if any gating case fails or if there is any scope violation. CI runs it on every push.
- **Paraphrase cases are informational.** They ask in different words ("stomach doctor" for gastroenterology). They are measured but don't fail the run: they document the limit of keyword search.
- **The private set on the server.** It uses the same format and runs with the same command against the real records. It never leaves the server, and its output contains only case ids and reason codes.

## Results at the time of this decision

20 cases: 17/17 gating passed, 0 scope violations, MRR 0.962. Paraphrases: 0/3.

## Alternatives considered

- **LLM-as-judge on full answers.** It measures the client model more than the server, costs money per run, and isn't deterministic. It may come later, for answer-level metrics.
- **No public evaluation, only the private one.** The quality claim would be unverifiable.

## Consequences

- **Every change to search is measured.** A regression in retrieval or scope fails CI.
- **Paraphrases are the open problem.** They fail today, which is the evidence [ADR 003](003-sqlite-fts5-index.md) asked for before considering semantic search. The next retrieval change has to raise the paraphrase score without breaking the gating cases.
- **A fictional set is easier than real data.** Results on the private set will be lower and are the honest number for real use.
