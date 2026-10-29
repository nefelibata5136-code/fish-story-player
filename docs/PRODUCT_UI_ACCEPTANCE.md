# Detroit product entry verification — 2026-10-29–30

The primary entry now names **Detroit: Become Human**, and offers one action to
obtain all 32 Chinese chapters from the pinned upstream and open a new game.
The original two-chapter demonstration is in a collapsed developer section and
is never silently selected when Detroit is missing. No paid model is called by
page loading, setup, planning or starting an Agent game.

## Actual browser exercise

Verified with the installed Playwright runtime and an isolated Chromium browser,
against a fresh temporary local data home. The shared Playwright MCP profile was
already occupied by another chat; it was left untouched. This is an isolated
browser exercise, not the owner's logged-in browser or a clean Windows machine.

| Exercise | Observed result |
| --- | --- |
| Fresh home | Detroit acquisition is primary; no story selected; the generic start button is disabled; demonstration section closed |
| One-click acquisition | Actual pinned upstream archive downloaded and validated; all 32 chapters imported together; first scene opened |
| Agent preparation | Actual local connection helper generated instructions bound to the just-created player and save |
| Pause / continue | Current game changed to paused, then returned to waiting for a choice |
| Real UI save flow | First actual choice saved, named checkpoint created, and new branch opened; original record retained |
| Imported-story share | JSON download contained activity counts only; no story, identity, path or time |
| Reload | Installed Detroit remained selected; primary start text named Detroit |
| Independent planning | Current pinned data contains 208 possible decision nodes; application offered 240 calls with headroom |
| Payment setup | Cost amount remained empty; applying capacity did not fill or raise the cost limit; explicit budget confirmation required before model requests |
| JavaScript | No page errors in the above exercises |

The decision count describes the entire content's possible nodes. A particular
route skips some nodes. Token planning counts only one applicable context and
one option set at each node. It estimates triangular history growth for the
existing 157-choice reference and for the 208-node capacity scenario, without
cache discounts. Suggested Token capacity adds the final conservative request
reservation and 25% headroom; it is distinct from estimated spending. These
scenarios are not route predictions or price bounds. Actual provider usage,
caching and play length remain variable. Saved model budgets retain their
existing durable behavior; branching never resets them.

## Visual check

Screenshots were captured at CSS scale and opened for visual inspection. Each
uses a fresh browser context with the listed viewport and measured DPR. No
overflow, clipped primary buttons, page zoom or DPR compensation was observed.
The public screenshots show only the acquisition screen, with no imported story
text, player records or generated local connection paths.

| CSS viewport | Measured DPR | Screenshot |
| --- | --- | --- |
| 1365 × 900 | 1 | [Desktop](detroit-entry-desktop.png) |
| 1365 × 900 | 1.5 | [Same CSS size, DPR 1.5](detroit-entry-dpr15.png) |
| 390 × 844 | 1 | [Portrait](detroit-entry-mobile.png) |

## Automated boundary verification

`tests/test_product_entry.py`, `tests/test_quickstart.py` and
`tests/test_interfaces.py`: **20 passed**. These use original or synthetic data,
real loopback HTTP and the official MCP stdio client/server. They verify missing
Detroit does not start the demonstration, explicit demonstration selection still
works, ZIP import needs no individual paths, acquisition retains strict consent
and origin/CSRF checks, planning returns no future story text or hidden rules,
and configuration generation does not start a game or model.

This evidence does not establish that a new native DSH Agent independently
completed every chapter, or that all routes have been explored. Those require
the separate gameplay/DSH acceptance evidence. Memory candidates remain subject
to the player's review. Imported-story sharing exports activity counts only;
complete narrative and choice reports remain private local exports.

The final budget panel was also visually checked: [budget planning](detroit-budget.png).
Before the later player-authored recap feature, this pinned pack and empty Core suggested Token allowance was
26,590,000; the separate 157/208-choice scenarios estimate approximately
11.75/20.51 million input Tokens before any cache discount. These planning
figures use the configured maximum response length and may exceed actual usage.
The amount limit remains a required user choice. A browser flow also caught and
fixed an export-button race: export stays disabled while a preceding save or
branch is still reloading, instead of dropping an early click.

The final planner additionally reserves the same model's chapter-recap calls and their history. Live capacity depends on the selected perspective; the earlier screenshot figures are historical UI evidence, not the final budget default. The final recap interface is documented in RECAPS.md.
