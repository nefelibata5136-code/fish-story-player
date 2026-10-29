# Acceptance — 2026-10-29

The v0.3.0 multiple-save update has **92 passing free tests** and separate save,
branch, browser and shared-budget evidence in [SAVE_ACCEPTANCE.md](SAVE_ACCEPTANCE.md).

The baseline below records v0.1.0. The v0.2.0 two-style update has **57 passing
free tests** and separate real-provider/browser evidence in
[STYLE_ACCEPTANCE.md](STYLE_ACCEPTANCE.md).

Tested on Windows with Python 3.12. This document separates free software tests,
real API use, local original-game compatibility, and public distribution.

| Requirement | Evidence and result |
| --- | --- |
| Original Agent reads and chooses through tools | Official MCP SDK `ClientSession` over a real stdio subprocess initializes, lists tools, starts, reads choices, submits, and reads the accurate receipt. Invalid choice leaves zero accepted choices; another bound player's session is rejected. No API variables are passed to the subprocess. |
| Core-based independent player works | A real DeepSeek session completed the two original demo chapters with four actual choices. See [real-provider test](REAL_MODEL_TEST.md). Fake HTTP providers cover failures without paid calls. |
| Player/save isolation | Independent session directories and databases; cross-player MCP rejection; different players and repeated games by the same player retain distinct pending IDs and histories. |
| Exact outcome records | Every accepted choice commits visible options, selected text, actual following visible events, timestamp, next progress, stable ID/hash and local save locator. Internal native results stay in SQLite. |
| Restart and resume | Game/model reconstruction from disk and separate CLI OS processes recover accepted records and the pending choice. The real model test paused after choice 2, reconstructed and completed. Idempotent application does not repeat an API call. |
| Human-readable report and memory export | JSON, complete Markdown visible history and a separate memory candidate are generated. Tests compare saved scenes/ending text and every actual choice. Fiction, actual player behavior and public explanation remain distinct. |
| Stable prefix and finite budget | Actual fake-provider HTTP request bodies and the real DeepSeek request hashes preserve the static system/core and prior messages. Persisted call/token/cost reservations stop unknown usage, retries and over-budget requests. Concurrency/ready-response crash recovery are covered. |
| Usable installation and UI | Editable install, wheel build, CLI, MCP, and local Web console work. Desktop and mobile flows were exercised in an isolated browser, including saved independent config recovery. |
| Privacy and copyright | Fresh repository created by explicit source allowlist. Seven MIT code modules retained with notices; no upstream chapter/config/results tree, original-game assets, existing personal saves, keys or real core files included. Imported stories cannot use the built-in public-share export. |

Free automated suite: **33 tests passed**. The suite uses only original/synthetic
chapters, fake HTTP providers and isolated temporary directories. No live API
tests run in the default suite or CI. The real test was separately authorized,
limited to CNY 10, and stopped after four calls with conservative calculated cost
CNY 0.005726; no official settled billing total was retrieved.

## Original local chapter compatibility

The local Chinese chapter pack was checked read-only through
`scripts/check_local_story.py`, using an isolated temporary import and scripted
first-option answers. **32 chapters and 157 scripted choices completed**. Visible
contexts and all reached ending narratives matched the retained native campaign
engine under the same saved random seed; restart readback matched too.

This is engine compatibility evidence, not a real Agent's playthrough, complete
branch coverage, or permission to distribute those chapters. No source chapters,
scripted transcripts or personal player records from that check are in this
repository. Existing local player records were kept intact and were not silently
migrated or published.

## Browser evidence

The configured Playwright MCP could not start because its browser profile was
already in use. The fallback used the installed bundled Playwright with a fresh
headless Chromium context, isolated data and no production player records.

| CSS viewport | DPR | Result |
| --- | ---: | --- |
| 1706 × 899 | 1 | Start, choose, pause, resume, reload and select saved session succeeded; no page errors or horizontal overflow. |
| 1706 × 899 | 1.5 | Same CSS layout and flows; scroll width 1706, root zoom 1, no overflow. |
| 390 × 844 | 1 | Core import/model configuration fit the viewport; scroll width 390. |

Images: [desktop](demo.png), [desktop DPR 1.5](demo-dpr15.png),
[mobile](demo-mobile.png). They contain only synthetic test players and the
original demonstration. Loading configuration, viewing a ledger, and restoring
the interface made zero model requests in the browser checks.

## Evidence export and remaining limits

The local source adapter preserves complete records, stable IDs, actual and
observed times, content hashes and immutable snapshots. Repeating an unchanged
export does not create new records. Personal play logs remain local; publishing
the software is not publication of those logs, and no dots read receipt exists.

No test claims an independent model is the original digital life. No native-life
session was awakened or used for testing. Windows/Python 3.12 is the local
acceptance platform; the GitHub CI matrix separately checks Windows/Linux and
Python 3.10/3.12 when run. Only the original demo and supplied JSON game format
are supported. Arbitrary providers and all possible original-game branches are
not verified. There is no engine-version save migration; fingerprint mismatches
preserve the records and block continuation until the pinned source is restored.
