# 自然语言课程任务验收

变更：refine-natural-language-course-targeting。2026-10-06（Asia/Shanghai）。

完整 Python 回归共 59 项通过，Node 回归共 10 项通过；最终后端 PID 82224。OpenSpec 严格校验通过，任务进度为 22/24（5.4 和 6.3 等待真实浏览器）。

## 已执行证据

| 验证 | 结果 | 实际覆盖 |
| --- | --- | --- |
| test_course_tasks.py | 13 项通过 | 双课独立范围、事务登记、外部请求前拒绝越界、共享来源提交范围、检查失败后局部修复、旧缺项与真实新增失效区分、续接原任务、多于 20 条待续任务分页、v3 迁移 |
| test_natural_targeting_api.py | 5 项通过 | 隔离 ASGI 消息精确重放、预览切换、同名问题刷新与原需求、stale/foreign/deleted 候选拒绝、新课批准重放及旧批准不扩大局部任务、跨对话占用 |
| test_sdk_runtime.py | 9 项通过 | 真实安装 Pi SDK → 生产 JSONL → Python → SQLite；查询/登记/混合范围修改/越界失败/反馈、自然问答恢复、仅语音任务完成但整课未就绪、取消/等待/逐段进度/无进展/推理文本 |
| test_tool_contracts.py | 14 项通过 | 20 个顶层 object schema、原子稳定 patch、模型紧凑 content 和用户完整 details、读取边界、来源池及语音状态 |
| test_pi_timeline.py | 5 项通过 | SDK 唯一 Agent 事实来源、最终校准、重复投递、问答及中断记录 |
| test_tts.py | 13 项通过 | 旧语音机制回归；补齐 fixture owner/批准前置条件，未放宽生产门禁 |
| Node 事件/时间线/工具卡/音频/待重试 | 10 项通过 | 默认折叠与完整字段结构、事件快照、音频互斥、精确旧 pendingMessage 读取 |
| npm run contracts / npm run build | 成功 | Python/Node/React 契约一致，TypeScript 与 Vite 正式构建；仅现有 use-client 和大 chunk 提示 |
| verify_natural_targeting_migration | 通过 | 36 个旧运行、7 个会话的副本迁移，原文档/媒体/检查/消息/问题/批准/SDK 详情/事件/时间线哈希保留，重复迁移与只读回退 |

SDK fixture 使用真实已安装 AgentSession、订阅、工具循环、会话管理和生产传输；模型流由本地确定性 fixture 注入，媒体由本地合法 WAV 替身生成。它能证明契约与执行链路，不能证明当前供应商自然语言理解质量。API fixture 在 import backend.app 前隔离 ROOT，未连接或修改实时业务数据。

范围反馈已验证：补现有页语音不生成缺失页，不把原本缺失的检查视为本次失效；曾经有效的检查发生指纹变化才纳入新增失效，新生成页面要求检查。局部编辑登记时保存缺项基线，旧无关缺项不自动补作，实际新增问题与有效报告失效仍反馈。只完成语音时 taskReady=true、courseReady=false，工作台不能称整课就绪。续接保持原请求、原范围和 taskId；结束一项不清除其他项。

## 部署与数据

安全空闲点重启 Python 后端至 http://127.0.0.1:8001；GET /api/sessions 返回 7 个会话。当前前端服务为 http://127.0.0.1:5173。原 6 门课程、293 个媒体记录及事件水位 204781 保留；元数据升级至 v3。逐项证据在 data/backups/natural-targeting-20261006-180035 下 migration-acceptance.json、live-restart-acceptance.json。

## 真实浏览器尚未覆盖

CUA 连接 127.0.0.1:5173 被用户保存的网站访问权限拒绝。已告知在 Codex 设置 → Browser 管理允许/禁止网站；未换浏览器或用 CDP/命令访问前端绕过限制。

以下场景仍需实际浏览器记录，任务 5.4、6.3 保留未完成：无引用输入与 Enter/中文输入法、同名自然问答、工具中 A/B 目标显示、后台 A 制作时 B 稳定显示、A 讲稿草稿导航保存/放弃、切课停止旧音频、空课/失败首张/历史回放不自动打开或发声、刷新输入草稿/待回答/旧待重试原载荷，以及桌面/窄屏布局。构建、SSR、API 或单独音频控制器检查均未计为真实浏览器交互通过。

## 旧验收对应与限制

| 旧多课行为 | 本次证据 | 剩余范围 |
| --- | --- | --- |
| 多课发现、版本、归属、批准与占用 | 任务/契约/API fixture | 当前真实模型理解与供应商成功率未测 |
| 引用选择、多课目标提交 | 新正文解析指引与 SDK task 登记替代，旧消息保持精确重放 | 无引用输入的浏览器交互待验收 |
| 切课、后台不抢预览、草稿、音频、刷新 | 原 guard 保留，API 与 Node 结构回归 | 5.4/6.3 真实浏览器待验收 |
| 逐课结算与未完任务 | 独立 taskId/scope/work、taskReady/courseReady、续接与分页 | 自由自然语言路由质量未测 |

本轮没有真实付费模型、搜索、生图、TTS 请求，不替代历史真实语音验收。原项目与 node_modules 未编辑；供应商配置保持。未虚勾旧多课 20/26 或事件工具 37/38；未在 apply 阶段归档或覆盖主规范。
