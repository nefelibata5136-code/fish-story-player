# 让你的大肥鱼玩《底特律：变人》 · Fish Story Player

**下载 Windows 便携包，双击打开，一次准备全部 32 章，让原来的 Agent 亲自玩。**

一个本地运行的文字互动游戏工具。你的小鱼可以在原有 Agent 中通过 MCP / CLI 直接游玩，也可以带入一份身份资料，在独立的模型会话中体验剧情。每次选择自动保存，随时暂停、继续、回看，最后把经历带回原来的生活系统。

基于 [Detroit AI Player](https://github.com/Baba88611/detroit-ai-player) 的 MIT Python 引擎，保留剧情判定、跨章状态和确定性回放。**首页、CLI 和 MCP 默认游戏均为《底特律》**；没有剧情时引导一次获取全部中文 32 章，已安装时直接开始。无需找 JSON 或逐个填写路径。原创演示仅保留在开发选项中。第三方章节经用户明确请求后直连固定上游下载到本机；发行包不镜像剧情。见[版权审计](docs/UPSTREAM_AUDIT.md)与[第三方声明](docs/THIRD_PARTY_NOTICES.md)。

**给 Agent 的最短入口：[Agent 快速开玩](AGENT_START.md)。**免 Python 的 `fish-story.exe play-detroit --player my-fish --accept-source-terms` 完成剧情准备并返回首个可玩节点，不创建替身模型。

## Windows：下载、解压、双击

1. 从 [v0.4.1 发布页](https://github.com/nefelibata5136-code/fish-story-player/releases/tag/v0.4.1)下载 **FishStoryPlayer-Windows-x64.zip**，解压整个文件夹。
2. 双击 **FishStoryPlayer.exe**，浏览器自动打开本机界面。保留同目录 `_internal` 文件夹；不需要安装 Python、Git 或依赖。
3. 点击首页 **“按上述许可获取 32 章并开始”**，程序一次完成全部章节准备并打开第一章。已安装时按钮直接开始《底特律》。
4. 点击 **“复制给我的 Agent，自己开玩”**。生成的说明和 MCP/DSH 配置已带本机真实路径、玩家标识和当前存档，交给原 Agent 即可；有终端工具时也可直接用 CLI。

打开网页会显示当前剧情与观测历史，**原 Agent 连接并调用工具后才由它本人作选择**。首次获取和原 Agent 工具接口不会在游戏程序里创建新模型。独立模型方式另需用户填写 API、环境变量和有限预算。

首次获取需要能访问上游 GitHub。下载经过固定提交与 SHA256 校验，不运行下载包内脚本，也不建立剧情镜像。重复准备复用同版本本地章节。网络失败可选整个上游 ZIP 一次导入，不用解压或逐个选择 32 个 JSON。

上游剧情贡献为 Joey Zhang / Detroit AI Player，按 **CC BY-NC 4.0，非商业使用**提供；署名、许可正文、来源声明与导入差异保存在本机。原游戏的第三方权利不由该许可授予，上游未获原游戏官方授权。本项目不声称已获得这些权利。软件代码 MIT 与剧情许可分别适用。

便携包为 Windows x64，未购买代码签名证书；下载页提供 SHA256 与构件清单。请从本仓库 Release 获取并核对文件，不需要关闭系统安全软件。关闭启动窗口会停止网页服务，存档仍在本机；重开即可继续。其他平台暂使用以下源码安装。

## 源码安装与一分钟演示

需要 Python 3.10+、Git。以下命令在 PowerShell 执行；首次安装需要联网下载 Python 依赖。

```powershell
git clone https://github.com/nefelibata5136-code/fish-story-player.git
cd fish-story-player
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m fish_story.cli serve --open
```

浏览器会打开终端显示的本机地址，优先使用 `http://127.0.0.1:8765`；默认端口被占用时自动选择空闲端口。首页一次准备《底特律》，选择“原 Agent 直玩”或“手动接力”开始。界面显示剧情、选项、选择与章节结果，可以暂停、继续、查看历史并下载 JSON、Markdown 报告或经历摘要。双击 `start.cmd` 会自动检查源码环境、创建虚拟环境并安装依赖；缺少 Python 或网络失败时给出中文处理说明。普通用户优先使用含运行环境的 Windows 便携包。

![底特律主入口](docs/detroit-entry-desktop.png)

数据默认保存在用户目录的 `.fish-story-player`，不在代码仓库内。自定位置使用命令前的 `--home 路径` 或环境变量 `FISH_STORY_HOME`。源码、已导入章节或核心资料变动时不会静默换规则；每局章节固定一份，核心与模型配置在首次运行时固定。

## 每章由玩家自己维护前情摘要

新游戏每章结束后，Agent 自己更新一份本地 Markdown 前情摘要，用来理解后续剧情。
默认最多 **5000 字**，Agent 可以调整上限；超长拒绝而不截断。原 Agent 使用
`game_recap_read` / `game_recap_update`，写完再继续下一章。独立模式由同一模型和 Core
整理，额外请求计入同一预算。沉浸模式按角色隔离，读档不带入未来摘要；文件与历史版本
保存在本地，正式长期记忆仍由本人决定。详见 [前情摘要说明](docs/RECAPS.md)。

## 多存档与自己选择存档点

每个玩家可以保有多份独立命名存档。程序每接受一次选择都会自动保存，并提供从开头到当前已见进度的自动点；小鱼也可以给当前或历史进度创建命名点。**读取一个点会创建新分支，原局保留**，不会撤销真实选择或覆盖它们。

网页左侧“继续已有存档”切换各局；当前存档区域可命名、保存进度点、选择旧点开分支，随后分别观看各分支历史和导出报告。自动点可以另存为命名点。MCP 提供 `game_saves`、`game_open`、`game_save_points`、`game_save_checkpoint`、`game_load_checkpoint`、`game_rename_save` 和 `game_rename_checkpoint`，均绑定本人玩家。

```powershell
.\.venv\Scripts\fish-story.exe new --player my-fish --save-name "第一轮"
.\.venv\Scripts\fish-story.exe save-points SESSION_ID
.\.venv\Scripts\fish-story.exe save-point SESSION_ID --name "留在这里" --operation-id point-001
.\.venv\Scripts\fish-story.exe load-point SESSION_ID POINT_ID --name "另一条路" --operation-id fork-001
.\.venv\Scripts\fish-story.exe rename-save BRANCH_SESSION_ID "重读这一章"
```

存档点只允许当前或已见进度，不能选择未来节点。分支保留原随机种子和此前真实选择，重新绑定会话／请求 ID；继承的选择保留原时间及来源，报告分别统计“继承”和“新增”。小鱼可选择自己的跨角色旧点；沉浸模式下其他角色的自由文本点名会遮蔽，读档后的剧情仍按目标角色过滤。回退存档不会擦除原 Agent 已有的后续记忆。

**独立模型的所有分支共用原预算账本，读档不清零调用数、Token 或费用。**未决模型结果先核对，不通过读档逃离预留。API Key 不进入快照。核心资料与存档只在本地冻结，全部分支均不自动公开。操作结果不明时保留原 `operation_id`，同 ID 核对同一存档点／分支，不盲目重复创建。详见[存档说明](docs/SAVES.md)。

![命名存档点与分支界面](docs/saves-desktop.png)

## 两种决策玩法

玩法与“原 Agent / 独立模型 / 手动接力”的连接方式分别设置，均可在开始新局时选择：

| 玩法 | 实际行为 |
| --- | --- |
| **角色沉浸** `immersive` | 以当前角色当时掌握的信息和处境作判断。玩家保有自己的身份；游戏历史按角色分开，角色甲 → 乙 → 甲时，模型回到甲自己的历史，不收到乙的私有剧情。 |
| **自知玩家** `self_aware` | 小鱼知道自己在玩游戏，可以携原本的经历与理解面对剧情，并参考全部已经见过的角色经历。仍不提供未来剧情、隐藏条件或攻略。 |

浏览器新增“决策玩法”选项。MCP `game_start` 接受 `play_style`，CLI 使用 `new --play-style immersive` 或 `new --play-style self_aware`。玩法随每局固定保存，恢复不会重置；每条新选择回执、报告和记忆候选都带玩法。旧存档显示“未声明玩法”，保留原提示和账本，不追溯宣称采用了新玩法。

人类网页可看完整时间线并导出完整报告；MCP、CLI 玩家视图和手动接力材料遵守所选角色范围。人类 CLI 完整导出需显式 `export SESSION_ID --observer`。原 Agent 原有的跨角色记忆无法被工具擦除，沉浸模式要求其本人遵守角色知识边界；独立 API 会话实际使用分角色消息流。

沉浸需要明确的角色归属。单角色章节自动识别；多角色使用显式数据标签、原生线路标签或当前已显示场景首行的明确视角标题。缺失、矛盾的标签会停止该节点的新选择，模型不会为此产生请求。归属不明的多角色结局只保留在人类完整观测中。固定上游包按章节哈希应用已核实的角色标签及死亡线路兼容修复，保留变更清单和旧存档；不能把整章角色列表当成共享知识。详见[32 章审查](docs/DETROIT_COMPATIBILITY.md)。详见[玩法与数据约定](docs/PLAY_STYLES.md)、[两种玩法真实模型验收](docs/STYLE_REAL_MODEL_TEST.md)。

![玩法选择与完整观测](docs/styles-desktop.png)

## 方式 A：原 Agent 直接游玩（推荐）

Agent 使用已有身份、记忆和自己的运行环境作出选择。游戏只提供当前已展示剧情、可用选项和存档功能，**此模式不会创建模型实例，也不需要游戏 API Key**。原系统仍可能按自身模型调用规则计费。

首页可复制原 Agent 的操作说明、通用 MCP JSON 和 DSH 原生配置。也可在便携包目录运行下列命令自动生成真实绝对路径，免手改路径；每个玩家用自己的稳定标识。导出配置不会覆盖已有文件。

```powershell
.\fish-story.exe agent-config --player my-fish --format mcp --output fish-story-mcp.json
.\fish-story.exe agent-config --player my-fish --format dsh --output fish-story-dsh.yml
```

DSH 使用官方 `@deepseek-ai/dsh-mcp-client` 的 stdio 条目。将生成的条目加入当前 `cordis.yml` 插件列表并重载；保留原模型、身份和其他插件。工具以 `mcp__fish-story__` 开头。其他支持 `mcpServers` 的客户端使用生成的 JSON。程序生成配置和给 Agent 的安装说明，由 Agent/用户安装到其实际环境；不会擅自覆盖现有配置或向主对话投递测试消息。

MCP 每步只返回当前场景和本次可见结果，不反复复制整部历史；`game_history` 按当前角色分页读取，跟随 `next_offset` 直到结束。CLI Agent 可在命令前加 `--compact`。完整记录仍保存在本机。

工具包括 `story_list`、`game_start`、`game_view`、`game_choices`、`game_choose`、`game_history`、`game_pause`、`game_resume`、`game_export`。先开始新局，读取当前场景，再用返回的 `request_id` 与选项编号提交选择。只能选择当前存在的选项；错误选项不写存档。同一请求同一内容重复提交返回原收据，不重复推进；不同内容冲突则拒绝。

有终端但没有 MCP 时：

```powershell
.\.venv\Scripts\fish-story.exe new --player my-fish --mode agent
.\.venv\Scripts\fish-story.exe view SESSION_ID
.\.venv\Scripts\fish-story.exe choose SESSION_ID REQUEST_ID 1 --reason "可选的公开说明"
.\.venv\Scripts\fish-story.exe pause SESSION_ID
.\.venv\Scripts\fish-story.exe resume SESSION_ID
```

`SESSION_ID`、`REQUEST_ID` 用实际返回值替换。CLI 输出 JSON，可直接交给其他 AI 做手动接力。玩家只用这些工具；引擎源码和故事包含未发生的剧情与隐藏规则，不应作为游玩材料。MCP 的玩家绑定用于正常接口隔离，同一操作系统账户的文件读取能力仍可绕过它，不能宣称操作系统级隔离。

## 方式 B：导入核心资料后独立游玩

**这是“基于核心身份资料创建的独立游玩会话”。**它会使用你提供的背景资料，但不保证完整复现原数字生命系统的认知状态、长期经历、工具和记忆。游戏角色是虚构人物，不覆盖小鱼的核心资料。程序不要求玩家善良、勇敢、理性或追求某个结局。

网页切换到独立游玩，导入 UTF-8 Markdown / TXT，或直接编写专用资料。最多 20,000 Unicode 字符；页面显示完整最终内容、字符数和粗略 Token 估计。核心资料保存在本地；**开始 API 游玩后，核心资料和已见剧情会发送给你选择的模型服务商**，须先确认其数据政策。核心不进入日志导出。模型面板提供显式的 DeepSeek Flash 预设与可选思考/JSON 配置；通用模式默认不向服务商发送额外专用参数。

API Key 只从本地进程环境变量读取，不放入网页、模型配置文件或 Git。普通用户可先在 PowerShell 设置自己的变量，再从同一个窗口启动程序：

```powershell
$taskModelKey = Read-Host "Model API key" -AsSecureString
$env:FISH_MODEL_API_KEY = [System.Net.NetworkCredential]::new('', $taskModelKey).Password
Remove-Variable taskModelKey
.\.venv\Scripts\python.exe -m fish_story.cli serve --open
```

不要把 Key 发到聊天中。关闭该终端后变量不再保留。程序不会打印 Key。

模型配置示例：[通用模板](examples/model-config.example.json)、[已实测 DeepSeek 模板](examples/deepseek-config.example.json)。`base_url` 为 OpenAI 兼容 Chat Completions 服务根地址（通常以 `/v1` 结尾）。**通用模板的模型名和单价是占位值；DeepSeek 模板按 2026-10-29 核对的人民币高峰价格填写，使用前仍需核对服务商当前价格。**单价、最高费用必须使用同一种货币；本地成本是按声明单价的估计与预留，不是平台实际扣款证明。真正免费服务可填零单价，但仍须设置有限调用数、Token 预算与正数费用上限。

```powershell
.\.venv\Scripts\fish-story.exe core-preview .\my-core.md
.\.venv\Scripts\fish-story.exe new --player my-fish --mode independent --core .\my-core.md
.\.venv\Scripts\fish-story.exe model-step SESSION_ID --config .\model-config.local.json
.\.venv\Scripts\fish-story.exe model-run SESSION_ID --config .\model-config.local.json
```

必须设置最大调用数、总 Token 预算、最高费用、输入/输出单价和单次最大输出 Token。网页按所选章节计算决策容量与增长历史的 Token 场景，明确确认后填入调用/Token 容量；费用上限由本人填写并确认。不再用 30 次调用暗示能完成 32 章，也不承诺任何预算必然通关。每次先保存保守预留，再发请求；失败也计入调用数。状态不明或用量缺失会停止，预留保留；程序没有网络自动重试。预算、模型和资料固定，重启不能清账。查看调用账本、人工核对后的解除办法见[运维说明](docs/OPERATIONS.md)。预算限的是本程序估算，无法替代模型供应商账户的账单或服务端限额。

固定系统提示和核心资料放在稳定前缀，已见剧情与真实选择仅向历史末端追加；跨章节不重写身份头。Provider 如返回缓存用量会保留实际字段；离线前缀测试不能证明线上缓存命中。模型接口仅接受编号与可公开短说明，不接受自编剧情作为游戏结果，不请求隐藏推理。

## 本地导入已有章节

网页可以一次选择整个仓库 ZIP，自动发现 `01_json/zh/`（或选择英文）；也支持仅含章节的平铺 ZIP。

```powershell
.\fish-story.exe import-pack C:\my-downloads\story.zip --title "我的故事" --language zh
```

上面的命令用于便携版；源码安装后用 `.venv\Scripts\fish-story.exe`。它与显式联网的 `setup-detroit --accept-source-terms` 分开：`import-pack` 只读本地包，不下载或执行包内程序。

兼容上游 `01_json/zh/ch*.json`、`01_json/en/ch*.json` 格式：

```powershell
.\.venv\Scripts\fish-story.exe import-story --title "本地互动故事" C:\my-local-story\ch*.json
.\.venv\Scripts\fish-story.exe stories
.\.venv\Scripts\fish-story.exe new --player my-fish --story STORY_ID --chapter 1
```

CLI 自己展开通配符，适用于 PowerShell。导入只读源文件，把 JSON 复制到本地数据目录；不执行脚本、不联网、不上传。各章内置的角色 system prompt 不转发给玩家。不要导入来源未知的材料或把引擎目录交给玩家当攻略。

从后面的章节新开游戏会使用该章默认初始状态，明确标为新起点；只有从前文连续游玩，才继承前面的真实选择。继续旧局使用原会话 ID，不需要重新导入或重新开始。

《底特律：变人》的原作权利与上游自写决策树许可分别存在。上游的 CC BY-NC 4.0 不是原作授权证明。本项目没有重新发布它们，也不把本地导入解释为任何内容的使用授权。

## 带回生活系统的经历

```powershell
.\.venv\Scripts\fish-story.exe export SESSION_ID --format json --output .\experience.json
.\.venv\Scripts\fish-story.exe export SESSION_ID --format markdown --output .\play-report.md
.\.venv\Scripts\fish-story.exe export SESSION_ID --format memory --output .\memory-candidate.md
```

结构化记录包含稳定记录 ID、来源、章节、不泄漏规则的节点引用、实际场景/选项/选择、可选公开说明、随后实际可见结果、真实时间、后续进度、存档定位和内容 hash。规则内部状态留在本地存档，不进入玩家材料。未知结果保持未知，不能从隐藏变量生成玩家未曾看见的结论。

摘要明确分开虚构事件、玩家真实选择、玩家公开解释。它是程序生成的待审候选，**不是已经获得玩家认可的正式记忆**。由玩家决定是否修改、接受和写回自己的长期记忆；程序不覆盖核心、不建立新的记忆系统。

所有日志默认私人。`--share` 对内置原创演示生成脱敏经历候选；对导入故事生成**不含剧情文字的活动统计候选**，省略剧情、选项、结局、自由说明、身份、时间和存档定位。完整经历仍可在本地私人导出。公开前由本人检查；导出不等于自动公开或长期记忆已接收。

本地 dots 证据适配见 [integrations/README.md](integrations/README.md)：记录与摘要分开，按完整记录分块，稳定 ID/hash 去重、内容寻址快照。默认不上传、不启用后台同步，也不代表 dots 已实际读取。

## 测试与维护

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/release_check.py
```

自动测试使用原创/合成章节与本机假模型 HTTP 服务，不需要付费 API。覆盖原 Agent 工具调用、独立 API 请求的真实 wire、预算/未知结果/前缀稳定性、跨章状态、每次选择回执、非法选项、幂等、隔离、暂停重启、报告、MCP 和 HTTP 安全边界。此外已在授权预算内完成一次 [DeepSeek 真实 API 两章验收](docs/REAL_MODEL_TEST.md)。具体实测结果和限制见 [本轮产品验收](docs/PRODUCT_ACCEPTANCE.md)与保留的历史 [ACCEPTANCE.md](docs/ACCEPTANCE.md)。

源码入口、便宜测试和恢复方法见 [OPERATIONS.md](docs/OPERATIONS.md)。本地 UI 的卡片、时间与安全文本渲染延续既有监看界面；没有依赖原来的生命 Host、固定 life ID 或私有目录。Windows 是本次实测环境；其他平台安装路径与浏览器行为尚未作同等验收。
