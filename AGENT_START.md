# 把《底特律：变人》交给原来的 Agent

把本仓库链接交给原 Agent 即可。你是玩家；运行器只提供已见剧情、选项和存档，
不会调用另一个模型替你选择。不必迁移 Core，也不必创建数字生命。

## Windows：不依赖 Python、Git 或 pip

1. 下载 [Windows x64 便携包](https://github.com/nefelibata5136-code/fish-story-player/releases/download/v0.4.1/FishStoryPlayer-Windows-x64.zip)
   及同页 SHA256 校验文件。验证后解压到有写权限的普通目录，保留 `_internal` 文件夹。
2. 工作目录切到解压目录。读取来源说明，然后在需要该非商业第三方故事时执行：

   ```powershell
   .\fish-story.exe story-source
   .\fish-story.exe play-detroit --player my-fish --accept-source-terms
   ```

   第二条命令完成全部 32 章的本地准备并新建原 Agent 存档，返回当前剧情、真实选项、
   `session_id` 和 `request_id`。无需预先打开网页。该命令不调用模型。
   已获取的同版本剧情会复用；再次 `play-detroit` 会新开一局，续玩应使用 `view`。
3. 只通过玩家工具读取和选择。不要读取章节 JSON、引擎源码或人类完整观测来预知剧情：

   ```powershell
   .\fish-story.exe view SESSION_ID
   .\fish-story.exe choose SESSION_ID REQUEST_ID 1 --reason "可选的公开短说明"
   .\fish-story.exe pause SESSION_ID
   .\fish-story.exe resume SESSION_ID
   .\fish-story.exe sessions
   .\fish-story.exe export SESSION_ID --format memory --output memory-candidate.md
   ```

MCP 每步返回当前场景与本次回执；需要回顾时用 `game_history(offset=0, limit=20)`，跟随 `next_offset` 分页。CLI 建议在子命令前加 `--compact`，避免反复返回全部历史。

每章结束收到 `recap_required` 时，用 `game_recap_read` 读取旧摘要和已见材料，亲自撰写后用 `game_recap_update` 保存；默认最多5000字，可自行调整。写完再继续，最后一章也要写。CLI 对应 `recap-read` / `recap-update --text-file`。

每次选择自动落盘。保存返回的会话 ID，进程重启后 `view` 即可恢复；不要用反复开局代替续玩。
记忆导出是待本人审核的候选，虚构事件与真实选择分别标明，不应直接写成现实经历。

## 有 MCP 的 Agent

首页的“复制给我的 Agent，自己开玩”会自动填入本机绝对路径、玩家标识，以及当前已打开的存档。也可在解压目录生成配置：

```powershell
.\fish-story.exe agent-config --player my-fish --format mcp --output fish-story-mcp.json
.\fish-story.exe agent-config --player my-fish --format dsh --output fish-story-dsh.yml
.\fish-story.exe agent-config --player my-fish --format instructions
```

通用 MCP 客户端使用生成的 `mcpServers` JSON。DSH 使用 `fish-story-dsh.yml` 中官方
`@deepseek-ai/dsh-mcp-client` 的插件条目：加入当前 `cordis.yml` 插件列表并重载，保留原身份、
模型与其他插件。工具名以 `mcp__fish-story__` 开头。配置已包含实际路径，不需要替换 Python 路径。
生成文件使用新建模式，不会覆盖已有配置。命令本身不会改写 DSH 或唤醒原主对话。

已有存档可加 `--session-id SESSION_ID`，生成的说明会直接打开它；不重新开局。

调用顺序：`story_source` → `story_setup_detroit(accept_source_terms=true)` →
调用 `game_start(play_style="self_aware")`（默认《底特律》） →
`game_view` / `game_choose`。恢复时用 `game_saves` 与 `game_open`。
选择 `immersive` 时只使用当前角色的游戏知识；工具不能抹除你在原系统已有的记忆。

## 人类观看

双击同一目录中的 `FishStoryPlayer.exe`，默认浏览器打开本机界面。
它与 CLI/MCP 使用同一个本机数据目录；选择对应存档即可查看，外部 Agent 推进后点击刷新。
网页是私人控制台，包含 Core 预览，请勿公开转发其页面或地址。

## 其他系统或已有 Python

Linux/macOS 暂用 Python 3.10+ 源码安装，见 README；将上述 `fish-story.exe`
替换为安装后的 `fish-story`。发行包保留开发演示；面向用户的默认入口始终是《底特律》，上游章节仅在明确请求后直连获取。
剧情贡献按 CC BY-NC 4.0 使用，署名 Joey Zhang / Detroit AI Player；原作权利不由该许可授予。
`story-source` 可查固定提交、来源、许可与权利说明。无法联网时可用 `import-pack 本地.zip`
一次导入合法取得的整个仓库 ZIP，不用整理章节。
