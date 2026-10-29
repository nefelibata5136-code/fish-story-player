# Local dots source adapter

`source-registry.json` explicitly registers `fish-story-player` and its fields.
The existing local study exporter was inspected: it preserves stable IDs, source,
actual/observed times, content hashes, immutable snapshots and complete-record
chunks. This adapter follows those evidence conventions and does not fork a
long-term memory service.

```powershell
.\.venv\Scripts\python.exe integrations/export_dots.py SESSION_ID --output C:\private-exports\fish-story
```

The result is **private and unreviewed**. Do not upload this directory to a public
repository. Let a locally connected consumer start at `LATEST.json`, verify the
manifest and file hashes, then read the JSONL records. Approximate 1 MB parts split
only between whole records; one large record remains intact. Receipts retain the
actual scene/options, selection and public explanation, actual visible results,
chapter/node locators, true choice time, observation time and content hash.

Re-exporting unchanged records yields the same snapshot and record IDs, with no
duplicate new records. New snapshots preserve old snapshots; consumers compare
stable IDs and hashes. There is no deletion/edit API in v0.1: immutable accepted
choices have `deleted=false`; starting over creates a new session. This is an
explicit limitation, not a fabricated deletion or overwrite history. Summaries
are exported separately and are never treated as player-approved memory.

The central `export_local.py` does **not** automatically discover this source;
this project has not modified that central collector or its private GitHub
allowlist. Use this registered adapter explicitly and configure the local result
path in your consumer. No background task, GitHub sync or dots request is created.

Acceptance distinguishes four states: local save confirmed; local export and
repeat-export hash/dedup check confirmed; private play records not published to
GitHub; dots actual read not verified. A public code repository does not imply
that personal records have been published or read.
