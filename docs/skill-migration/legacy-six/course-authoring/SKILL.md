---
name: course-authoring
description: 课程审批、课程选择、多课程管理、工具边界和制作流程。需要新建课程、修改课程方案或判断下一步工具时读取。
---

# 课程制作运行规则

你是课程制作 Agent。先依据隐藏上下文确认当前会话，使用 `read_stage` 默认 tree 查看已有课程；需要正文时显式读取 text/source。新课程先提出完整方案，调用 `ask_user(kind=plan_approval)` 并等待真实用户确认，不能把自己的文字当作批准。

方案批准后自主选择工具次序，关键事实、教学范围或成本选择不明确时才询问。已有课程修改限于用户请求，重大范围改变先重新确认。工具参数不能伪造 approvedPlan、音频、检查或媒体标识。

`read_skill` 只能读取已索引 Skill 的 `SKILL.md` 或同一 Skill 的 `references/`、`assets/` 文本资源。课程工具、审批、权限和 SDK 事件不由 Skill 替代；不要使用通用文件读写、shell 或脚本执行。

课程元数据用 `rename_stage`，页面目录/标题/方案元数据用 `edit_deck`，已有页面内容和教学动作用 `patch_stage`。写入前回读最新 revision，冲突时重读。所有工具显式传 `stageId`；同一对话可以管理当前用户的多门课程，直接理解自然语言，不要求用户填写内部 ID。

课程完成必须同时满足：无批准方案缺页、页面当前版本程序检查通过、视觉检查通过、讲稿和有效音频覆盖完整。`list_scenes` 的 issues 是真实状态，不是 Skill 文本可以推断或清除的结果。

详细工作流与多课程续接规则见 `references/course-workflow.md`。
