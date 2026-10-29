# Real-provider two-style acceptance — 2026-10-29

Both decision styles completed an original synthetic three-chapter A → B → A story through DeepSeek official Chat Completions. Each style used a separate independent session with an original generic test identity; no existing digital life core, memory or main session was used. The API model alias requested was `deepseek-flash`; no exact deployed model version is asserted.

Each session was limited to three calls, 100,000 total tokens and CNY 0.20, with `thinking: disabled`, JSON mode and output cap 256. The application made exactly six real requests. No unknown-result retry occurred.

| Style | Real calls | Prompt tokens | Output tokens | Conservative CNY estimate | Final player / observer choice records |
| --- | ---: | ---: | ---: | ---: | --- |
| Character immersion | 3 | 1655 | 88 | 0.004014 | 2 / 3 |
| Self-aware player | 3 | 1816 | 125 | 0.004632 | 3 / 3 |

Total actual usage: **3,684 tokens**. Conservative cost for this two-style test: **CNY 0.008646**; including the earlier baseline test, the task estimate is **CNY 0.014372**, below the authorized CNY 10 limit. This uses peak uncached input at CNY 2/million and output at CNY 8/million, ignoring cache/off-peak discounts. It is a calculation from actual returned usage, **not an official settled bill**.

Verified against actual outgoing HTTP request bodies:

- Immersion requests contained only the controlled character's witnessed game facts. B did not receive A's private marker; switching back to A did not expose B's private marker.
- Returning to A retained A's first request messages as an exact prefix; each style's static system/core hash stayed stable.
- Self-aware requests retained all previously witnessed A/B scenes, with each earlier request preserved as an exact message prefix.
- The generic player identity remained present in every request. Native role/system prompts and hidden engine data were absent.
- After the first decision of each style, pause, discard/reconstruct, readback and resume preserved the saved style and records.
- Full human observer reports retained all three decisions; the final immersion player view contained only A's two decisions. Player and observer JSON reports plus a separate unendorsed memory candidate were generated locally.
- Exact credential-byte scanning across the 48 current tracked/untracked non-ignored publication source files found zero matches. No real key, native identity or private transcript is included in this summary.

These results validate the independent API mode. For an existing original Agent, the tool boundary can limit returned information but cannot erase knowledge already in its original memory; role immersion still requires that Agent to respect the declared character knowledge boundary.

Pricing reference checked for this task: [DeepSeek official pricing](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/).
