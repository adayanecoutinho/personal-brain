# 005. Pending before confirmed

- **Status:** Accepted
- **Date:** 2026-11-25

## Context

From phase 4, records will be created from chat: an assistant reads a photo of a prescription and writes a record. Vision models misread handwriting and dosages. A misread dose presented as fact is the worst failure this system can have.

## Decision

Every record has `review_status: pending | confirmed`.

- Anything written by an AI enters as `pending`; only the owner confirms it.
- Every search result and full record returns the status.
- The tool descriptions instruct the client never to present pending records as facts and to always cite sources.

## Alternatives considered

- **Trust the extraction.** Faster, and wrong in exactly the cases that matter.
- **Keep AI writes in a separate inbox, invisible until confirmed.** Safer, but then the assistant can't answer "what is still waiting for my review?".

## Consequences

- The owner has a review step. It can happen from chat (`confirm_entry`, phase 4), so it doesn't require a laptop.
- The final guard depends on the client model following the tool description. The evaluation measures it explicitly (correct handling of pending data).
