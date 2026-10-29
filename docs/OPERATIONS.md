# Maintenance and recovery

The game is a tool for its player. Keep this map near the code so an Agent can
discover, inspect, change and cheaply test its own installed copy.

| Behavior | Owning source / test |
| --- | --- |
| Story conditions, probabilities and cross-chapter state | `fish_story/vendor/native/{runner,campaign_runner,resolver,state}.py` |
| Pending player seam, fixed seed, transaction, receipt | `fish_story/engine.py`, `tests/test_game.py` |
| Session isolation, local imports, reports, evidence adapter | `fish_story/service.py`, `tests/test_game.py` |
| Play style, attribution and player/observer scope | `fish_story/styles.py`, `tests/test_styles.py`, `tests/test_style_model.py` |
| Named points, frozen prefixes, fork recovery and shared budget family | `fish_story/saves.py`, `tests/test_saves.py`, `tests/test_save_budget.py`, `docs/SAVES.md` |
| Identity preview, API protocol, prefix and budget ledger | `fish_story/model.py`, `tests/test_model.py` |
| MCP ownership, safe errors, CLI and loopback console | `fish_story/{mcp_server,cli,server}.py`, `tests/test_interfaces.py` |
| Screen layout and all visible interactions | `fish_story/web/index.html` |
| Publication allowlist and heuristic scan | `scripts/release_check.py` |

Installed entry points: `fish-story --help`; `fish-story stories`; MCP `story_list`.
All models are optional in Agent mode; no native life Host or private profile is
required. Behavior changes can be developed in a normal clone of this repository.

## Config and state

Data root defaults to `~/.fish-story-player` or `FISH_STORY_HOME` / `--home`.
`sessions/<UUID>/session.json` records ownership/mode/story provenance;
`story/*.json` pins story bytes; `games.sqlite` holds the native replay seed,
accepted answers, visible receipts and internal outcomes; `core.txt` exists only
for independent sessions. `model.sqlite` pins config/core hash and preserves all
API reservations, numeric usage and saved public answers. Keys come from the
configured environment variable, never those files.

The browser console is a local operator view over all sessions, including their
core preview. MCP is a separately bound player view. Neither isolates hostile
processes running under the same operating-system user. Run under separate OS
users/data roots when that is required. Do not expose this loopback console
through a public reverse proxy or port forwarding.

## Unknown model result

```powershell
.\.venv\Scripts\fish-story.exe model-status SESSION_ID --config model-config.local.json
```

`reserved`, `unknown`, or `overrun` stops further API calls. First read the current
save and ledger, then inspect the provider's own usage. A saved `ready` answer is
applied idempotently without another request; a truly unknown response must not
be blindly resent. If the operator has checked the provider and intentionally
accepts that a new request may incur another charge, they may explicitly run:

```powershell
.\.venv\Scripts\fish-story.exe model-ack SESSION_ID --config model-config.local.json --call-id CALL_ID --acknowledge-provider-checked
```

The command retains the entire conservative reservation and call count. It does
not refund money or restore quota. It is never automatic. Configuration/core
changes require a new session; do not delete a ledger to continue an old session.
The local ledger is an estimate based on user-supplied rates, not official
settled charges. Cached token ratios are the latest provider-returned usage,
when supplied; missing usage remains unknown.

## Cheap checks and restoration

1. Pause the affected game. Stop any model-run/browser auto loop and wait for
   an in-flight request to finish or remain explicitly unresolved.
2. Close writers before copying the private data directory. Back up its current
   bytes and your current source (including uncommitted changes) outside Git.
3. Change only the relevant module. Run its synthetic tests, then the full tests
   when the shared engine/API contract changed. No paid API is needed.
4. Source/story fingerprint mismatch intentionally blocks an existing run.
   Restore its exact original source/story bytes from your backup, or start a
   new session under the new version. Do not overwrite another Agent's changes,
   reset history or mutate stored choices to force compatibility.
5. Roll back code separately from user data. An accepted choice or charged API
   call is a real event and must not be erased to make a code rollback look clean.

Useful read-only checks:

```powershell
.\.venv\Scripts\fish-story.exe view SESSION_ID
.\.venv\Scripts\fish-story.exe export SESSION_ID --format json
python -m pytest tests/test_game.py tests/test_model.py tests/test_interfaces.py -q
python scripts/check_local_story.py "C:\my-local-story\ch*.json" --limit 3
```

The optional chapter compatibility script runs scripted first choices in an
isolated temporary directory and compares contexts/endings with the retained
native engine. It never opens existing player saves, calls a model, or claims
that its scripted answers are a real player's choices.

## Known v0.1 boundaries

The replay seam reconstructs state from the start of the session for each step;
very large campaigns cost more local CPU. No snapshot migration across engine
versions is implemented. Later chapter starts use declared defaults, rather than
inventing earlier decisions. CLI/Web are local operator tools, not multi-user
hosting. The original story JSON format is supported; arbitrary game engines
and every provider's thinking/tool API are outside this release. The independent
mode imports a core document, not an Agent's complete life or long-term memory.
