# Working on Fish Story Player

This repository continues the existing MIT narrative engine; do not replace it
with a new Agent framework. Keep the player-facing projection separate from
hidden engine state. Agent/MCP mode never calls a replacement model. Independent
mode must stay explicitly labeled and retain finite, durable budgets.

Run `python -m pytest -q` after shared-contract changes. Targeted changes can use
the owning tests listed in `docs/OPERATIONS.md`. Use synthetic/original chapters;
do not put local Detroit story packs, core documents or player saves into tests.
Keys are environment references only. Never print provider error bodies.

Private state defaults outside this checkout. Do not stage `.env`, core files,
databases, logs, imported stories or private reports. Preserve existing source
and data before changes, and do not clear budgets or accepted choices during
recovery. `scripts/release_check.py` is read-only and scans staged/tracked files.

Keep original MIT notices with vendored sources; story licenses are separate.
The included original demo is CC0. Imported stories have not been cleared for
redistribution. Do not publish them. Public reports must describe tests honestly:
fake HTTP provider, real API test and original Agent's native life are different
evidence. Never automatically turn a program-generated memory candidate into
player-approved memory.
