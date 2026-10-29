# Third-party notices / 第三方声明

## Detroit AI Player — reused software

Source: [Baba88611/detroit-ai-player](https://github.com/Baba88611/detroit-ai-player)

Pinned upstream commit: [`3c4ae839169df24d8934642037f27d2eb2bca9a2`](https://github.com/Baba88611/detroit-ai-player/commit/3c4ae839169df24d8934642037f27d2eb2bca9a2).

Original software files, copied from `03_runner/src/` into `fish_story/vendor/native/`:
`api_client.py`, `campaign_runner.py`, `events.py`, `logger.py`, `resolver.py`, `runner.py`, `state.py`.

The original MIT license is retained at
[`fish_story/vendor/LICENSE.detroit-ai-player`](../fish_story/vendor/LICENSE.detroit-ai-player).
The upstream author is **Joey Zhang / Detroit AI Player**. Moving source files into a vendor directory does not change their original authorship.

Modifications: `runner.py` and `campaign_runner.py` retain the local optional random-number-generator parameter wiring used for reproducible saved games. The separately adapted `fish_story/engine.py` reuses the existing local player seam around that engine: pending choices, SQLite transactions and deterministic replay. See [`UPSTREAM_AUDIT.md`](UPSTREAM_AUDIT.md) and the repository history for the reuse boundary and subsequent changes.

The MIT terms for reused software are:

```text
MIT License

Copyright (c) 2026 Joey Zhang

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Upstream data and writing — excluded

Detroit AI Player publishes its decision-tree JSON, state registry, persona/model configuration, documentation and figures under **CC BY-NC 4.0**, separately from its MIT software. The present repository does **not** redistribute these materials. Do not apply this repository's software license to an imported upstream story pack.

Authoritative upstream scope:
[License Scope](https://github.com/Baba88611/detroit-ai-player/blob/3c4ae839169df24d8934642037f27d2eb2bca9a2/docs/legal/README.md),
[CC BY-NC 4.0 text](https://github.com/Baba88611/detroit-ai-player/blob/3c4ae839169df24d8934642037f27d2eb2bca9a2/docs/legal/CC-BY-NC-4.0.txt).

Neither upstream license grants the original game's story, character, setting, trademark or asset rights. The upstream author's claim that its chapters are paraphrases is not a verified chain of permission from the original game's rights holders.

Since v0.4 an explicit user-requested acquisition command can fetch the pinned source directly from upstream GitHub into the user's private local storage. CC BY-NC does not prohibit such downloads. No downloaded chapters or upstream data are mirrored in our repository or release artifacts. Local acquisition retains attribution, license materials, source commit, checksums and import-modification notes. This capability does not grant or claim original-game authorization.

## Detroit: Become Human — no bundled game content

*Detroit: Become Human* is a work developed by Quantic Dream. Its official game page states copyright and trademark ownership by Sony Interactive Entertainment Europe and reserves the relevant rights. This project is not affiliated with or endorsed by those parties, and has no verified authorization to redistribute the original game's story materials.

No original game scripts, transcripts, decision-tree chapters, artwork, audio, video, executable files or logos are included. Local data import is a file-format capability, not a grant of rights to the imported material.

Primary references checked on 2026-10-29:
[Quantic Dream official game page](https://www.quanticdream.com/en/detroit-become-human),
[PlayStation official game page](https://www.playstation.com/en-us/games/detroit-become-human/).

## Original demo story

The demonstration story newly written for Fish Story Player is offered under **CC0-1.0**. It is independent of the Detroit story and does not use that game's characters, dialogue or setting. This dedication applies only to the project's own original demo content; it cannot waive rights in imported third-party content or private player records.

Full terms: [Creative Commons CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/legalcode).

## Runtime dependencies

Source installations use the package manager. The Windows portable edition bundles a Python runtime and dependencies, with their notices in `THIRD_PARTY_LICENSES`, including the Python incorporated-software license appendix and PyInstaller bootloader exception. The main package and retained upstream command-line convenience code use the following packages:

| Package | License | Upstream |
| --- | --- | --- |
| requests | Apache-2.0 | [psf/requests](https://github.com/psf/requests) |
| mcp (official Python SDK) | MIT, Copyright (c) 2024 Anthropic, PBC | [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE) |
| python-dotenv (retained upstream CLI convenience paths; not needed for Fish Story Player entry points) | BSD-3-Clause | [theskumar/python-dotenv](https://github.com/theskumar/python-dotenv) |

The requests and python-dotenv license identities were checked against installed distribution metadata during the audit; the MCP SDK license was read from its official repository. Distributors bundling dependency wheels, executables or a Python runtime must also preserve the notices and license files shipped with those distributions and their transitive dependencies. The original software license does not relicense dependencies.
