# Real-provider acceptance — 2026-10-29

A real independent-player session completed both chapters of the original demonstration story with four accepted choices. The identity material was an original generic test identity; no existing digital life's core, private memories, or chat history was used. This verifies the independent session mode, not full migration or cognitive continuity of an original Agent.

- Provider: DeepSeek's official OpenAI-compatible Chat Completions endpoint.
- Requested and provider-returned model name: `deepseek-flash`. The API returned that alias; an exact deployed version was not independently returned.
- Explicit optional settings: `thinking: "disabled"` and `json_mode: true`.
- Limits: at most 6 calls, 100,000 tokens, and CNY 10 based on declared conservative prices; actual run used 4 calls.
- Actual prompt tokens: 2,415; completion tokens: 112; total: 2,527.
- Estimated cost using peak uncached input at CNY 2/million and output at CNY 8/million: **CNY 0.005726**. This deliberately ignores cache discounts and off-peak discounts. It is a conservative calculation from provider-returned usage, **not an official settled debit or bill**.
- Actual accepted option numbers: `1 → 2 → 3 → 1`; game reached `complete`.
- After the second choice, the game was paused, both service/player objects were discarded, a new service read the same saved records, and play resumed to completion without replaying a submitted answer.
- The actual outgoing request bodies retained an identical static system hash and each prior request's messages as an exact prefix. Evidence retains only hashes/counts for these comparisons, not credentials or private prompts.
- Human-readable report, structured JSON, and a separate unendorsed memory candidate were generated from the saved game records.

| Real request | Prompt tokens | Completion tokens | Provider-reported cached input tokens | Latest input cache-hit ratio |
| --- | ---: | ---: | ---: | ---: |
| 1 | 356 | 31 | 0 | 0% |
| 2 | 498 | 25 | 256 | 51.41% |
| 3 | 709 | 29 | 512 | 72.21% |
| 4 | 852 | 27 | 640 | 75.12% |

These are actual provider usage values for these four requests. A short demonstration does not guarantee the same cache behavior for other providers, models, contexts, or sessions.

The explicit thinking toggle and current prices were checked against the [official thinking-mode documentation](https://api-docs.deepseek.com/guides/thinking_mode/) and [official pricing page](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) on the test date. Provider options are opt-in; generic providers receive neither field by default.
