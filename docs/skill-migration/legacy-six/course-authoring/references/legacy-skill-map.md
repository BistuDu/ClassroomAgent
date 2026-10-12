# 迁移范围

旧版 `skills/course/*.md` 已拆分为两类：

- Agent 运行 Skill：`skills/agent-runtime/*/SKILL.md`，由 Pi SDK 发现并按需读取。
- 无状态生成提示：`generators/*-generation.md`，只由 Python 生成服务读取，不作为 Agent Skill。

原项目中依赖 PPTX 导入、模板、教师素材库、个人 Skill 持久化或执行脚本的能力未迁移；Python 项目继续只开放课程业务工具和受限 `read_skill`。
