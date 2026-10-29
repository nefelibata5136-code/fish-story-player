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
| Explicit pinned source acquisition, local attribution and checksum | `fish_story/source.py`, `tests/test_source.py` |
| Safe whole-ZIP import | `fish_story/import_pack.py`, `tests/test_import_pack.py` |
| Double-click Windows runtime and frozen CLI/MCP | `fish_story/desktop.py`, `scripts/build_windows.py`, `scripts/check_windows_bundle.py` |
| Default Detroit selection and source integrity at new start | `fish_story/service.py`, `tests/test_source.py`, `tests/test_product_entry.py` |
| Generated MCP / DSH connection with bound player and existing save | `fish_story/agent_setup.py`, `tests/test_agent_setup.py` |
| Bounded current-step responses / paginated role history | `fish_story/player_output.py`, `fish_story/mcp_server.py`, `tests/test_player_output.py` |
| Hash-bound role / terminal-route compatibility adjustments | `fish_story/detroit_compat.py`, `tests/test_detroit_compat.py`, `scripts/audit_story_campaign.py` |
| Explicit finite independent-game capacity and cost planning | `fish_story/planning.py`, `tests/test_product_entry.py` |

Installed entry points: `fish-story --help`; `fish-story stories`; MCP `story_list`.
All models are optional in Agent mode; no native life Host or private profile is
required. Behavior changes can be developed in a normal clone of this repository.

`agent-config --player my-fish` generates local absolute paths. `--format dsh`
emits an official DSH MCP plugin entry without changing the installed DSH.
`--session-id` binds the generated instructions to an existing owned save.
For CLI Agents, global `--compact` avoids repeating all previous history.
MCP step responses are compact by default; `game_history(offset, limit)` returns
at most 50 events and 50 records per page with an explicit `next_offset`.
The full private Web observation and exports retain the original evidence.

Compatibility adjustments apply only to matching pinned chapter hashes in new
imports or new session snapshots. Detailed change evidence stays in private
story manifests / `story_compatibility.json`; player responses show version/count
only. Existing saves and API ledgers are not rewritten. Preserve their exact
snapshot on recovery; start a separate new save to use corrected data.

No-provider integration checks:

```powershell
python -m pytest -q
python scripts/check_windows_bundle.py dist/FishStoryPlayer-Windows-x64.zip --detroit
python -m fish_story.cli --home PRIVATE_TEST_HOME agent-config --player qa --output connection.json
node scripts/check_dsh_bridge.mjs --runtime DSH_INSTALL_DIRECTORY --config connection.json --story detroit --campaign
```

The last command requires a prepared story in that explicitly selected private
test home. It invokes the actual installed official DSH MCP adapter/tools in a
fresh isolated registration scope, with scripted choices and no model provider.
Its success is distinct from an autonomous DSH Agent's model-driven playthrough.

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
