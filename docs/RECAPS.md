# 玩家自己的前情摘要

新游戏默认启用。每章结束后，游玩者自己更新一份本地 Markdown 前情摘要，
用于后续理解人物、关系、已发生事件和未决事项。默认最多 **5000 个 Unicode
字符**，包含标点；玩家可自行调整上限。超长会拒绝，程序不截断、不替玩家编写。

原 Agent 收到 `recap_required` 后，下一章玩家材料暂不提供：

1. 用 `game_recap_read(session_id, task_id)` 取得自己的旧摘要和本章已见材料。
   证据有明确分页；跟随 `evidence.next_offset` 继续。
2. 本人撰写滚动摘要，用 `game_recap_update(session_id, text, task_id,
   max_characters?, operation_id?)` 保存。可设置新的字数上限；同一操作 ID
   用于核对不明结果，不能盲目另写一份。
3. 用 `game_view` 继续。最终章结束也需完成摘要。

CLI 对应命令：

```powershell
.\fish-story.exe recap-read SESSION_ID --task-id TASK_ID
.\fish-story.exe recap-update SESSION_ID --task-id TASK_ID --text-file my-recap.md --max-characters 5000 --operation-id recap-001
```

Markdown 真实保存在私人存档目录，工具返回文件位置和字符数。数据库保留历史版本、
hash 和撰写进度；`latest.md` 是当前版本的便捷入口。使用工具更新，或显式用
`--text-file` 提交自己编辑的文本。不可变版本被外部改动或删除时会停止读回，
不会悄悄覆盖。公开分享不包含这些私人摘要。

自知玩家维护一份完整已见剧情摘要；沉浸模式分别维护各角色的摘要，更新任务
截止于该角色已经完成的章节，不混入下一角色场景。原 Agent 的已有记忆不能
由运行器擦除，仍需本人遵守知识边界。

独立 API 模式用同一配置模型和 Core 撰写，每章整理请求与选择请求使用同一份
有限预算，未决请求与崩溃恢复规则相同。预算规划包括这些额外请求。已发送的
系统头和历史前缀保持稳定，摘要任务及真实回答按章节边界追加，不回写旧消息。
假 HTTP wire 检查可验证前缀，不能代替线上缓存命中率证明。

读档只继承在目标进度之前实际撰写的摘要。后续补写的旧章摘要也不会倒灌进
更早分支。摘要是玩家对游戏的理解，不替代原始选择记录，不自动成为正式长期记忆。
旧存档不被升级过程静默改写；无 `recap_version=1` 的旧会话保留原模型请求行为。
