# Multiple saves and named checkpoints

Players can own multiple named game sessions and choose where to save. Every
accepted choice is durably autosaved. `auto:0` denotes the beginning; `auto:N`
denotes the game state after N accepted choices, before its next pending choice.
Only positions already seen in that source session are available. The final
completed position may also be saved.

A named checkpoint freezes a prefix of the game, its rules/seed, core bytes and
play style. Loading it **creates a separate branch**; the source is never rewound
or overwritten. A later change to a source core cannot silently change an older
named checkpoint. Changing pinned story/engine bytes causes continuation to stop.
Legacy notes without trustworthy position locators remain in the source and are
not copied into an earlier branch as if they had already existed there.

## Player and human controls

Web: name the current save, save the current or a previous accepted-choice count,
select a point, and load it as a new named branch. The saved-session selector
switches between all local saves without merging their histories. Original,
alternate and further branches remain individually available after restart.

MCP: `game_saves`, `game_open`, `game_save_points`, `game_save_checkpoint`,
`game_load_checkpoint`, `game_rename_save`, `game_rename_checkpoint`. Each tool
checks the bound player first. No replacement model is created in Agent mode.
There is no global active pointer that another client can silently switch: every
choice addresses a specific session and pending request ID.

CLI: `save-points`, `save-point`, `load-point`, `rename-save`, `rename-point`.
Use `--help` for parameters. The default is player scope; human full observation
uses explicit `--observer` where supported. Web is the human observer console.

Save controls belong to the player. An immersive player may select an older point
of another character. That point's free-form label/name history and chapter title
are redacted from another role's control listing, while identifiers, position and
role remain usable. The resulting branch returns its target role's bounded game
history, never the source's later scenes. Original Agent memory cannot be erased;
the independent API receives only the checkpoint prefix allowed by its style.

## Evidence, inheritance and privacy

Inherited choices retain their original occurrence time and earliest origin
session/record/hash, plus their immediate parent reference. New run/request IDs
isolate future choices. They are marked `inherited=true`, never relabeled as new
decisions made at branch creation time. Reports and memory candidates show the
inherited/new counts; memory remains a program-generated candidate for review.

JSON reports keep full lineage locally. Public-share candidates omit private save
names, origin identifiers and correlation hashes. Original imported-story sharing
remains denied unless cleared by the existing distribution policy. Checkpoint
databases, core copies, model ledgers and logs do not belong in public Git.

The dots adapter exports only newly made choice events for a branch. Inherited
events appear as source references in the manifest, so branching does not create
duplicate real choices in an evidence timeline. Re-exporting unchanged content
keeps the same snapshot. No automatic upload, consumer read or memory acceptance
is implied.

## Budget family and recovery

Independent branches resolve their ancestor's `model.sqlite`. All share the
pinned configuration, call count, Token/cost reservations and usage. Loading a
point never refunds or resets the budget. Keys are still environment references;
no Key is included in a checkpoint. An unrelated explicit new game has its own
budget; a branch does not acquire a fresh one.

The ledger tags each call with its owning session. A saved `ready` response is
applied only to that session. Pending/unknown/overrun/ready calls block new family
spending; return to the owning save to finish or explicitly review the call.
Acknowledgement cannot be made from another branch and never refunds a retained
reservation. If a previously initialized ledger is missing, stop and restore it;
do not fall back to a branch-local empty ledger or remove its ancestor directory.

Game saves and model costs have different timelines: reverting fictional progress
does not undo actual API calls or the player's real prior experiences.

Checkpoint and fork calls accept `operation_id`. Reusing the same ID/arguments
reconciles the same result; changed arguments are refused. Published targets can
be checked read-only after a lost response, even if the source later progressed.
Interrupted unpublished work remains in local staging and resumes under the same
operation; it is not shown as a usable saved session. Snapshot hashes are checked
before recovery. Do not invent a replacement ID after an ambiguous write.

Runtime layout: each session owns `points.sqlite`; branches have separate
`games.sqlite`, pinned story/core files and parent metadata. The family's original
`model.sqlite` remains the one authority for its model spending. `model.initialized`
records that the ledger must be preserved. The native engine/vendor are unchanged,
so existing game fingerprints remain valid. No deletion or destructive overwrite
command is introduced.
