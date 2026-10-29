# v0.3 multiple-save acceptance — 2026-10-29

The complete local free suite contains **92 passing tests**. New coverage uses
original/synthetic stories and real local SQLite/HTTP/MCP processes; no paid model
request is needed or made for this update.

Core save tests exercise named/current/historical and automatic checkpoints,
multiple branches, names and rename history, immutable source database bytes,
prefix truncation, frozen core bytes, deterministic seed/QTE/internal outcomes,
distinct run/request IDs, inherited original times and multigeneration provenance,
legacy v0.1 compatibility, snapshot corruption detection, interrupted staging and
published-but-unacknowledged recovery. Read-only reconciliations preserve database
bytes and do not create duplicate points or branches.

Model-family tests use a local fake provider and the actual transport. They prove
that loading an earlier point does not clear calls/tokens/cost/config; branches
use the same ancestor ledger; another branch's `ready` answer is never applied
to the wrong save; unresolved calls block spending across the family; old ledger
rows migrate with their existing usage; and missing, foreign or truncated family
ledgers cannot silently become new branch budgets.

Evidence tests distinguish inherited choices from newly made real events. Reports
and memory candidates label inheritance, the dots adapter exports only new branch
choice events plus origin references, and repeat export is idempotent. Public
share candidates remove private names, lineage IDs and correlation hashes.

Official MCP SDK stdio tests start, save, choose, fork, rename and list multiple
owned saves while preserving the source, with cross-player requests rejected.
HTTP and CLI tests verify explicit observer versus player scopes. An immersive
player can return to an owned earlier-role checkpoint using redacted control
metadata; the target branch receives only its own role's prefix.

The isolated browser flow saved two named points at choice counts 0 and 1,
advanced the original to two choices, loaded count 1 into another branch and
chose a different option, then loaded count 0 into a third save. Original and
branches remained separate. Rename, reload recovery, style and inherited/new
labels were checked. No page errors or model requests occurred. CSS viewports
1706×899 at DPR 1 and 1.5 and 390×844 at DPR 1 had no horizontal overflow.
[Desktop screenshot](saves-desktop.png), [mobile screenshot](saves-mobile.png).
The configured Playwright MCP profile was occupied, so the browser verification
used already installed Playwright with a fresh headless Chrome context; no other
browser profile or production save was used.

The native engine and vendor files remain unchanged, preserving old fingerprints.
No personal stories, cores, checkpoints or logs are published. Independent
branches preserve budgets but do not restore the original digital life's whole
cognitive state. An original Agent cannot forget later events just because its
game save is loaded. Source sessions and their family ledger must be preserved;
no destructive overwrite/delete command was introduced.
