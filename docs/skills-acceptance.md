> 本文是 2026-10-08 原六项系统的历史验收，不能证明本次16项对齐已验收；当前状态见 skill-migration/acceptance.md。

# Skill 系统验收

日期：2026-10-08。范围：`implement-python-skill-system`，仅 Python 项目实现，未修改原项目或 `node_modules`。

## 实现

- SDK `DefaultResourceLoader` 与 `parseFrontmatter` 是唯一发现和 YAML 解析来源，Python 不再维护另一套 frontmatter 解析器。
- 6 个标准 Skill：course-authoring、slide-design、interactive-simulation、narration-actions、inspection-quality、quiz-design。
- 初始提示只有名称、描述、相对路径和 `read_skill` 示例，正文不自动注入。
- 每轮固定正文和 references 快照；重载返回 added/removed/changed 和版本，活动运行不被替换。
- 旧六个别名仍可使用，标准名称与旧名称返回同一份内容；SDK 历史记录无需迁移。
- 名称冲突、无效 YAML、缺少 name/description、越界符号链接和加载失败均有诊断。失败回退最小提示，不启用通用工具。
- `skill_diagnostics` 由 Python 持久保存，并作为 SDK 隐藏 custom 消息记录。真实读取仍产生 SDK 工具事件，正文不伪装成助手回复。

## 可重复验收

```bash
.venv/bin/python -m unittest tests.test_skills
node tests/skill-resources.mjs
PYTHONPATH=tests .venv/bin/python -m unittest test_sdk_runtime.SdkSkills.test_legacy_session_resumes_with_standard_skill_and_durable_diagnostics test_sdk_runtime.SdkSkills.test_resource_failure_uses_minimal_prompt_and_reports_error
PYTHONPATH=tests .venv/bin/python -m unittest test_sdk_runtime.SdkRuntime
PYTHONPATH=tests .venv/bin/python -m unittest test_tool_contracts
npm run contracts
npx tsc --noEmit
```

以上命令全部通过。4 个资源测试覆盖 SDK YAML、发现、分页、旧别名、references/assets、路径/符号链接拒绝、无效 frontmatter、名称冲突、新增/修改/删除重载和活动运行固定版本。2 个真实 SDK 会话测试覆盖旧会话恢复、新名称读取、持久诊断和加载失败最小提示。10 个现有 SDK 回归测试和 19 个工具契约测试覆盖工具参数、content/details、事件和会话契约。

## 真实模型

使用已配置的 `deepseek-flash`、真实 Pi Agent 和项目内 Playwright 浏览器，在隔离目录 `data/skills-live-x3uyidu3` 执行。未写入现有课程数据库。

模型根据索引主动读取 slide-design 和 inspection-quality，随后调用：

`read_skill` → `read_skill` → `read_stage` → `set_course_tasks` → `generate_scene` → `check_scene(mode=program)`。

生成 1 张 slide 页面，程序检查 `executed=true`，全部工具节点 `source=pi`。证据：`data/skills-live-x3uyidu3/acceptance.json`、该目录数据库、SDK 会话文件和运行日志。

检查 `passed=false`，报告 NO_ACTIONS 和多处 ELEMENT_OVERFLOW。本次明确只验收页面生成和一次检查，因此没有制作讲稿、TTS 或视觉检查，不将该页或课程标为合格。页面质量和教学效果不是本变更的通过结论。

重跑真实验收：`.venv/bin/python -m scripts.verify_skills`。该命令会调用真实已配置模型并创建新的隔离数据目录。

## 未迁移能力

原项目的 PPTX/PPT 模板导入、教师素材库、个人 Skill 写入和通用编程脚本没有迁移。对应范围见 `skills/agent-runtime/course-authoring/references/legacy-skill-map.md`。
