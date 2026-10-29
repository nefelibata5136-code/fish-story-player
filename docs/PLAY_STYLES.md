# Decision perspectives

Connection mode answers where the player runs: original Agent, independent API
session, or manual relay. Play style answers how decisions are made. Both are
saved separately; no life framework or long-term memory system is introduced.

## Character immersion

The player takes the fictional character's current situation and knowledge as
the basis for choices, retaining their own identity and core. No morality,
personality trait or ending is prescribed. Their own understanding may help
interpret a situation, but does not prove that a character knows a fact witnessed
through another character.

Player tools return only the current role's attributed witnessed events. Filtering
covers nested receipt outcomes, histories, records, exports and relay clipboard.
Completion retains the last role's view instead of unlocking all histories. The
independent API uses separate A/B/A game transcripts; returning to A restores A's
previous prefix. The static system/core stay fixed. Role switching starts or
resumes a role stream and may incur a cold cache for that prefix.

Original Agents may already know other roles' scenes or walkthroughs. Tools cannot
erase their original memory. The instructions require respecting character
knowledge, but do not claim cognitive isolation. Core text is retained rather
than rewritten to remove prior life experience.

## Self-aware player

The player knows they are playing a game and may bring their own experience and
interpretation. All previously witnessed game history stays in one append-only
transcript. Future scenes, unseen endings, hidden conditions and native role
system prompts are still never supplied.

## Story attribution fields

Single-protagonist chapters use their declared protagonist. Multi-role nodes can
declare `player_facing.perspective` as a protagonist name. Endings can declare
`player_perspective`:

```json
{
  "chapter": {"protagonist": ["Character-A", "Character-B"]},
  "nodes": [{"player_facing": {
    "perspective": "Character-A",
    "context": "A scene visible to Character-A."
  }}],
  "endings": {"ending_a": {
    "title": "An actually reached result",
    "narrative": "Its visible outcome.",
    "player_perspective": "Character-A"
  }}
}
```

This illustrates additive fields, not a complete executable chapter. Names must
match declared protagonists. Invalid explicit tags or contradictory headings are
unavailable instead of silently falling back. The runtime also supports the
native protagonist phase-prefix convention and complete first-line headings such
as `当前角色：Character-A` or `【Character-A视角】` in the actually resolved,
already-visible scene. It never infers roles from node IDs or narrative name
mentions, inspects unseen variants to disclose their consequences, or defaults
an ambiguous new scene to the previous role. Explicitly named substitutes get
their own knowledge stream, not the replaced character's private history.

Unattributed current scenes stop new immersive choices with
`ROLE_PERSPECTIVE_UNAVAILABLE` before API reservation/request. Previously accepted
requests remain idempotently readable even when the next role is unknown. Fix
the local source and start a new game; do not modify a pinned story or overwrite
accepted choices. A separate self-aware game is also possible. This does not
claim complete immersive coverage of every legacy chapter or branch.

Unattributed multi-role endings remain in the full human observation. Identical
ending title/text with conflicting role tags is ambiguous because the native
public projection lacks ending IDs, so it is not assigned to either role. Tags
are data-author assertions, not automatic proof that every sentence respects
character knowledge. Imported content retains its original rights.

## Persistence and observation

New sessions store `play_style` and `play_style_version`. The adapted store adds
these and controlled characters to receipts before the native SQLite transaction
commits. Complete receipts have reproducible `content_hash`; filtered receipts
retain `source_content_hash` for private complete evidence and recompute their
own hash. Program-generated memory remains an unendorsed candidate.

The browser is a human operator console with the complete chronology. Its clipboard
uses the bounded player API; Web exports are explicitly observer exports. CLI
full export requires `--observer`. MCP exposes no observer bypass. One operating
system account's file access remains outside this interface security boundary.

Styles are fixed per game. To change style, start a separate session, preserving
the old game and ledger. Model settings pin style/prompt version with core and
budgets; metadata edits cannot silently replace an initialized model's context.

The native `engine.py` and vendor modules were not modified, preserving existing
game fingerprints. Old sessions without style metadata use `legacy_unspecified`
and their original system/core prefix, core hash and receipt schema. No previous
choice, core or budget is migrated, overwritten or relabeled as a past immersive
decision.
