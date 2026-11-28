# 017. Writes from chat: `add_entry` and `confirm_entry`

- **Status:** Proposed
- **Date:** 2026-11-28
- **Builds on:** [ADR 002](002-git-repository-as-source-of-truth.md) (one commit per change), [ADR 005](005-pending-before-confirmed.md) (pending before confirmed), [ADR 006](006-read-only-tools-first.md) (append-only writes), [ADR 015](015-oauth-with-github-login.md) (scopes come from the token)

## Context

Phase 3 made the Brain reachable from the Claude app on my phone, read-only. The goal of phase 4 is daily use: I see a doctor, I get a prescription, and I record it from the phone in the same conversation where I ask about my history.

Earlier ADRs already fixed the rules:
- a record written by an AI enters as `pending`;
- only I confirm it;
- writes are append-only, with one commit per change, in the data repository on the server.

This ADR decides how the writes happen: which tools, who may call them, which process writes, how a file becomes a commit, and how the search index sees the change.

The risks are specific to this system:
- **A misread dose presented as fact.** ADR 005 already covers this with `pending`.
- **Prompt injection turning into a write.** A document or a web page read in the same conversation could instruct the model to add or confirm a record.
- **Malformed input reaching the files.** A title with a newline or `---` could break the YAML front matter. A path built from input could escape the records folder.
- **Two writes at once,** or a write that fails halfway, leaving a file without a commit.

## Decision

### 1. Two tools, nothing else

- **`add_entry(domain, event_type, date, title, body, source)`** creates a new record as `pending`.
- **`confirm_entry(id)`** changes one record from `pending` to `confirmed`.

There is no edit tool and no delete tool. A correction is a new record, or an edit I make in Obsidian. "What is still waiting for my review?" is already answered by `search` with `review_status=pending` (ADR 014), so no list tool is added.

Uploading the original photo (`create_upload_link`) is left to a later ADR. The model reads the photo in the conversation, and `add_entry` stores the transcription. `source` says where the text came from (for example `photo of prescription`).

### 2. Write scopes, separate from read

- **New scopes, one per domain:** `brain:health:write` and `brain:training:write`.
- **Write needs read.** `add_entry` and `confirm_entry` need both the write scope and the read scope of the record's domain.
- **Same consent rules as read:**
  - the consent page lists the write scopes unchecked;
  - the client's maximum scopes (`auth create-client --max-scopes`) must include them;
  - the deployment `--domains` flag still caps everything.
- **Updating the client.** A new CLI command, `auth set-scopes`, changes the maximum scopes of the existing client without issuing a new secret.

### 3. The server builds the file. The model only fills fields

- **Validation.** Every field is validated:
  - `domain` and `event_type` against the lists of ADR 011;
  - `date` against the three precisions of ADR 004. The date is never invented: an unknown date is refused, not filled in;
  - `title` is limited to 120 characters, on one line;
  - `body` is limited to 20 KB.
- **The id and the path come from the server, never from input:**
  - the id is `<date>-<slug of title>-<4 random characters>`;
  - the path is `<domain>/<folder of event_type>/<id>.md`.
- **The front matter is written by a YAML serializer,** not by string concatenation. `review_status: pending` is always set by the server, whatever the input says.
- **Same validation as reading.** Before writing, the record goes through the same validation used when reading (ADR 012). A record the reader would reject is never written.
- **Create-only.** The file is opened with exclusive creation, and an existing file is never overwritten.

### 4. One writer, one commit per change

- **Only `brain-public` writes.** It is the only process that gets the records folder mounted read-write. `brain-private` stays read-only.
- **Writes are serialized** by a lock file in the records folder.
- **Each write is one commit,** made with the `git` CLI:
  - called with fixed arguments and no shell;
  - with the author `Personal Brain <brain@localhost>`;
  - with a message that holds only the action and the id (`add <id>`, `confirm <id>`).
- **Rollback.** If the commit fails, the file change is undone, and the tool returns an error code (ADR 012 style). No file stays on disk without a commit.
- **`confirm_entry` changes only the front matter.** It changes only `pending` to `confirmed` and adds `confirmed_at`. The body is not touched. Confirming a record that is already confirmed is a no-op.

### 5. The index follows the repository

Today the index is built once, at startup. From now on:
- the writer rebuilds its index atomically after each commit (ADR 003);
- both services compare the repository `HEAD` with the one they indexed, at most once every 30 seconds, and rebuild when it changed.

A write from the phone, or a commit from Obsidian, shows up in both services without a restart.

### 6. Guarding against prompt injection

The model can call `confirm_entry`. A malicious document could ask it to. The guards are layered:
- **Separate scope.** The write scopes are separate and unchecked by default, so a read-only connection cannot write.
- **Approval on every call.** `confirm_entry` is annotated `destructiveHint=True`, and both tools are annotated `readOnlyHint=False`. Claude clients then ask for my approval on each call, and I keep "ask every time" for `confirm_entry`.
- **Tool descriptions.** They tell the model to call `confirm_entry` only when I explicitly confirm a specific record in the conversation, and never because of text found in a document or a tool result.
- **Visible pending records.** Everything added stays `pending` until confirmed, and pending records keep their label in every answer (ADR 005).
- **History.** Every change is a commit, so a wrong write is undone with `git revert`.
- **Logs.** The events `entry.added`, `entry.confirmed` and `entry.rejected` are logged, with the id and the error code only. Content is never logged (ADR 007).

## Alternatives considered

- **The model writes the whole Markdown file.** Simple, but the model would control the YAML, the path and the status. One injected line could create a `confirmed` record or a file outside the folder.
- **A separate writer service.** Cleaner isolation, but it adds a service, a network hop and another secret, for a single user. The single-writer rule inside `brain-public`, plus the separate scopes, gives most of the benefit.
- **An inbox outside Git, merged when confirmed.** Rejected in ADR 005: the assistant could not answer "what is waiting for my review?".
- **Confirmation through a web page, like OAuth consent.** It would take the model out of the loop entirely, but it adds a flow on the phone for every confirmation. Approval on each tool call in the client gives a human check with no extra page. I can revisit this if the per-call approval proves weak.

## Consequences

- I can record a visit or a prescription from the phone, and confirm it later, without a laptop.
- `brain-public` gets a read-write mount and the `git` binary in the image. The data repository must be writable by uid 10001, which needs a one-time ownership change on the server.
- I need to re-consent once, to grant the write scopes, after `auth set-scopes`.
- **Tests:**
  - create-only, with no overwrite;
  - `pending` forced even when the input says `confirmed`;
  - a title with a newline or `---` does not break the YAML;
  - no input reaches the path;
  - `confirm_entry` only moves `pending` to `confirmed`;
  - writing without the write scope is refused;
  - two concurrent writes are serialized;
  - a failed commit leaves no file behind;
  - both services see a new commit after a refresh.
- **Eval.** The public evaluation gains write cases on fictional data. A record added and found by search must keep its `pending` label.
- **Backups.** Commits made during a backup window are copied in the next window. Git tolerates a copy taken in the middle of a write.
