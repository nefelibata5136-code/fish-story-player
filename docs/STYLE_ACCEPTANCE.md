# v0.2 play-style acceptance — 2026-10-29

**57 free automated tests passed** on Windows/Python 3.12. New coverage includes
alternating A/B/A player projection versus full observer history; nested receipt
outcome filtering; hashes for filtered/full receipts; transactional persistence
of style; restart; explicitly tagged nodes/endings; first-line-only role labels;
unknown/contradictory role rejection; ambiguous identical-ending rejection;
idempotent receipts after transition to an unknown role; legacy game and model
ledger compatibility; and stale concurrent model-call prevention.

The official MCP SDK stdio subprocess starts a chosen style, reads the perspective
frame, submits a real tool choice and reads receipts. MCP has no observer bypass.
HTTP/CLI tests verify bounded player versus full human observation and explicit
CLI observer exports. New styles do not instantiate a model in Agent mode.

Local fake HTTP provider tests inspect actual wire messages. Immersion has
separate A/B/A character history, A's old prefix is retained on return, self-aware
history remains append-only across roles, and core/system remain stable. Unknown
roles or mistakenly supplied observer histories stop before network reservation.

Separately authorized [real DeepSeek acceptance](STYLE_REAL_MODEL_TEST.md) passed
for both styles: six actual requests, 3,684 tokens, conservative calculated cost
CNY 0.008646. Including the earlier test, calculated task total is CNY 0.014372,
below CNY 10. No official settled billing amount was retrieved. Each style paused
and restored from disk; observer reports kept all three actual choices.

Browser verification used installed bundled Playwright in isolated headless
Chromium because the configured MCP profile was occupied. Actual A/B/A flows
confirmed full human history, bounded relay clipboard, full observer exports,
fixed style after reload and self-aware history. No model requests or page errors
occurred. CSS viewports 1706×899 at DPR 1 and 1.5 and 390×844 at DPR 1 had no
horizontal overflow. See [desktop](styles-desktop.png) and
[mobile](styles-mobile.png); both contain only synthetic characters and test data.

The native `engine.py` and vendored engine were kept unchanged. Old sessions
remain `legacy_unspecified`, using old prompts, core hashes, records and ledgers;
their old choices are not retrospectively relabeled. The explicit style/version
is recorded only for new games. Budget limits and unknown-request reservations
are preserved.

Role tags define the supported information boundary. Missing/contradictory tags
stop new immersive choices; unknown multi-role ending prose remains observer-only.
This does not verify every branch of all imported stories. An original Agent's
existing memory cannot be erased; it must obey the declared character perspective.
The independent API's actual request stream is role-filtered, but cannot guarantee
that a pretrained model never draws on its own prior knowledge. Identity and
memory-candidate review boundaries apply to both styles.
