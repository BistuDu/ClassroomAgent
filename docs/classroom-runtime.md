# LangGraph 互动课堂

## 执行边界

制作仍由 Node Pi SDK 自主调用原制作工具；课堂用 Python LangGraph 的 director → actor → 工具/语音回执 → director，之后按 wait 进入 interrupt 等用户、按 end 结束话题。预制 Player 不调用模型。老师与三位同学分别使用身份提示、权限和音色，历史作为带身份的课堂证据输入，不能冒充当前角色的 assistant 历史。同学无演示工具，调度器无公开发言、工具或继续讲课权限。

`classroom_runtime.py` 使用 `StateGraph`、`AsyncSqliteSaver`、`interrupt`、`Command(resume=...)`。模型/TTS、操作意图准备与 interrupt 分属节点，恢复读取已保存结果。模型通过实际 HTTP SSE 适配 completions 或 responses，最终 stop/tool_calls/completed 校准；length/503/无效流不能计为成功。DeepSeek 课堂请求显式禁用默认 thinking（completions `thinking.type=disabled`，responses `reasoning.effort=none`），防止短调度 JSON 的预算被默认推理消耗；此设置不修改制作 Agent。依据：[DeepSeek thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/)。

## 配置与预算

未设置课堂服务组时完整复用已解析 CREATION。独立配置必须提供 CLASSROOM_PROVIDER、BASE_URL、MODEL、API、API_KEY；缺项报告错误，不混用旧凭证。不设置固定角色发言次数上限，旧 CLASSROOM_MAX_SPEAKERS 配置不再生效。保留预算：每次角色连续工具调用最多 8 次、每次模型输出 4096 token、上下文预估 24000 token、单请求 90 秒、模型/TTS 累计生成 180 秒、回执 45 秒（音频至少 duration+30 秒）。预算耗尽保持等待，不能自动继续讲课。LangGraph recursion_limit=250 是一次图执行的节点步数保护，不是角色发言次数。句段不超过 350 字，逐段合成，实际 ended 才播放下一段。

调度模板使用 backend/classroom-prompt-resources/director.md（原项目 director/system.md 原文），由 backend/classroom_prompts.py 填充原变量。新请求返回 next_agent 角色 ID / USER / END，映射为 Python 角色 / wait / end；旧缓存 next 格式仍兼容。四个角色迁移完整人设、原回复长度建议、同伴接话、讨论开场/加入和回应真人规则。仅输出协议、工具能力、真实回执和显式恢复播放适配 Python；详细来源和差异见 backend/classroom-prompt-resources/README.md。普通问答首次也由 director 按原规则选择，预设讨论保留指定发起者快捷路由。最近 10 条发言摘录每条最多 200 字符，完整历史仍保存。

课堂角色系统提示自动注入当前页语义、元素/控件 ID、必要实验契约和实际观察，以及课程名称与描述、总页数、前五页标题/类型/稳定 ID 目录和剩余页数。当前页在前五页之外仍提供自身详情。目录不是其他页正文，本次没有跨页正文读取能力。近期发言仅来自当前互动会话。工具反馈后刷新系统证据区，保留 assistant/tool 配对；不生成读取工具事件。长文字/表格有明确摘录标记；当前话题较早发言按预算保存 2000 字以内的摘录，完整事件仍可查。UTF-8 字节/2 做保守估算，不等于供应商真实 tokenizer；供应商 usage 原样记录。未结算调用和结果对不被静默截去，超过预算显式暂停。未提交测验不向角色提供 answer/explanation；有效成绩必须属于此课堂、此题目指纹。

## 工具与实际结果

实时课堂每次角色模型请求（包括收到工具反馈后的再次请求）都根据服务端角色和当前页类型计算能力。共享策略位于 `backend/classroom_tools.py`：角色许可、页面适用工具与注册目录取交集；`actor` 用同一工具列表生成提示和模型请求，`Classrooms.validate_tool` 用同一策略授权。权限不来自模型自报身份、页面标题或前端传入的工具名单。

| 角色 | slide 普通页 | interactive 实验页 | quiz 测验页 |
| --- | --- | --- | --- |
| teacher | spotlight、laser | widget_setState、widget_highlight、widget_annotation、widget_reveal | 无（自动证据） |
| curious / notetaker / thinker | 无 | 无 | 无 |
| director / 未知身份 | 无 | 无 | 无 |

未知页面类型不给工具，不回退到全部工具。无法识别的发言角色明确拒绝模型请求。每次获得独立的对象根参数 Schema；同学/调度器空列表在 completions 和 responses 请求中都省略 `tools` 字段。测验页老师没有模型工具，仍自动获得当前证据和真实提交结果，未提交答案和解析仍隐藏。

| 工具 | 参数 | 模型得到 | 用户看到 |
| --- | --- | --- | --- |
| spotlight / laser | elementId（模型参数） | 成功/失败和已显示元素 | 完整参数与实际播放器回执 |
| widget_setState | sceneId、state | 实际 state、observation 与结果 | 完整 iframe ACK |
| widget_highlight / widget_reveal | sceneId、target | 真实执行观察或错误 | 完整参数、实例与结果 |
| widget_annotation | sceneId、target、content | 真实执行观察或错误 | 完整参数、实例与结果 |

服务端先校验当前用户/课程指纹/页面/角色/变量/控件，播放器再校验实例执行。模型即使输出未提供工具，仍由服务端拒绝：角色越权返回 `CLASSROOM_TOOL_ROLE`，页面不支持或未知工具返回 `CLASSROOM_TOOL_PAGE`，绑定的原请求页面或实验目标页不一致返回 `CLASSROOM_PAGE`；适用工具继续校验参数、元素和变量/控件。失败保留 `tool_start → tool_end`、完整调用参数及 `{ok:false,error:...}` 模型反馈，不产生 `execution_pending`，不向浏览器发送，不自动切页。

允许的演示发送 pending 后仍未成功；等待对应 operationId、generation、sceneId、instanceId 的实际 ACK 才生成结果。执行失败反馈 `ok:false`，不会写成功观察；语音还要求实际 ended。**工具调用记录与页面效果分开**：有一张失败工具卡不代表演示已显示。本轮仅在当前页演示，测验页不能远程操作另一实验页。临时操作不写 Stage、revision、预制 actions 或检查报告。工具卡默认收起，上方参数、下方结果完整显示；展开不会执行。

## API 与事件

| 接口 | 用途 |
| --- | --- |
| POST /api/classrooms | stageId、expectedRevision、requestId（恢复已有记录，无强制新建选项） |
| GET /api/classrooms/{id} | 快照、游标、待处理操作与状态 |
| POST /api/classrooms/{id}/commands | requestId、controllerId、kind 与适用的 text/cursor/markerId |
| POST /api/classrooms/{id}/progress | controllerId、generation、稳定 cursor、可选 markerId |
| POST /api/classrooms/{id}/ack | generation、operationId、sceneId、instanceId、status、实际 result |
| GET /api/classrooms/{id}/history?after=&limit= | 有序完整事件分页（最多500条） |
| GET /api/classrooms/{id}/events?afterSeq= | 同一持久事件日志的 SSE |
| GET /api/classrooms/{id}/tool-details?callId=&roundId= | 脱敏完整工具参数与实际结果 |

命令：question/join/skip/continue/pause/stop/navigate/start/resume_interaction/text_only/retry_audio。稳定游标包含 sceneId、actionId、phase、audioId/signature/audioTime、experimentState/displayState、focus/laser、instanceId。模型、工具、音频绑定页码基于 planPageId，而不是当前 UI 页。

事件 envelope 为 seq/eventId/classroomId/dialogueId/roundId/generation/source/speakerId/messageId/toolCallId/sceneId/data/createdAt。来源：`classroom_graph` 为真实角色增量和工具过程；`classroom_player` 为用户、状态及执行回执；`classroom_service` 为恢复/中断。课堂事件从不写 Pi 制作时间线。主要事件：user_message、message_start、text_delta、message_end、tool_start、tool_end、execution_pending、execution_receipt、audio_ready、audio_end、audio_error、text_only、waiting_user、budget_reached、state、interrupted、receipt_timeout。客户端按 seq 去重，并用最终正文校准增量；不会把导演 JSON 拼成角色文本。

## 保存、恢复与媒体

业务库 `data/classroom.sqlite3` 新增 learning_* 记录与 learning_events 表；图 checkpoint 为 `data/classroom-checkpoints.sqlite3`。课程快照引用原媒体，不改写源课程。每10秒以及动作结束、暂停/切页保存游标。停止/新问题撤销 generation，迟到事件/语音不执行。每课堂一名控制者，60秒租约，进度续约；其他窗口可读取历史，不能抢占有效控制。

操作日志保存参数哈希、意图、结果和 pending/running/completed/failed/unknown/cancelled。同请求同参数复用，不同参数拒绝。跨业务库与 checkpoint 的间隙通过稳定操作 ID 协调，新的 iframe 只更新 deliveryInstanceId，不改变原意图。付费请求中重启标 unknown，不自动重复。浏览器实际 ended 是完成语音的必要证据；用户“仅文字继续”独立结算，不能冒充成功播放。音频播放失败可重播已生成片段，不重复 TTS；TTS 失败须用户明确重试。

新角色模型意图另存 `arguments.toolPolicy`（version=2、sceneId、roundId、generation、instanceId、当次工具 Schema）用于冻结能力。旧意图的 system/messages 和参数哈希原样保留，完成结果直接复用，不重复模型、TTS 或已完成演示；缓存中的工具调用在执行边界仍须授权。新 pending 请求仅在冻结能力与当前页策略一致时续接；缺少能力信息或不匹配的旧 pending 请求返回 `CLASSROOM_TOOL_POLICY` 并保留日志，课堂明确中断，用户可重新提问。running/unknown/failed 的请求沿用原不自动重试规则。本升级不改写源课程或媒体。

恢复默认等待显式操作。互动完成先 RESTORE 原实验参数和临时高亮/注释/显示，收到真实确认再播放同一 action/audioTime；缺乏完整快照的旧实验或恢复失败保持暂停，不用 RESET 冒充恢复。课件指纹改变显示版本冲突，旧课堂历史保留，从新版本重新开始。

learning_media 是持久保留引用，预制与新课堂音频都校验 owner/stage。当前无自动媒体 GC；维护清理必须使用 `Store.remove_media`，拒绝任何课程或保留课堂引用的媒体。课程原记录软删除后，属于当前用户的课堂引用仍可读取。媒体 private immutable 缓存；文件路径只能是媒体目录内文件。

## 运维和回退

构建 `npm run contracts && npm run build`，环境 `uv sync --locked`，启动 `npm start`。不要全局安装或修改 SDK。更新前停止服务并同时备份两份 SQLite 和其 WAL/SHM（或用 SQLite backup），以及 data/media、pi 和配置；不能只复制一个正在写的数据库文件。回退时停止服务、恢复同一时间点备份与对应代码/依赖/前端，原制作数据格式未作破坏性升级。直接保留新增记录给旧代码会丢失课堂功能，旧代码不得清理课堂引用音频。

显式真实验收脚本 `scripts/classroom_acceptance_server.py` 读取现有折射课，在 data/classroom-acceptance-env 隔离保存并启动 8002，仅初次生成五段短 TTS。它使用实际模型/百炼，产生真实 API 用量；普通自动化测试不调用付费服务。验收不能把模拟模型或假音频当作真实供应商证据。

本次工具过滤的受控请求、执行回执和恢复验证见 [classroom-tool-availability-acceptance.md](classroom-tool-availability-acceptance.md)；记录明确区分受控模型/HTTP 捕获与真实供应商或浏览器演示。

## 互动会话与播放分离（dialogue-v1）

当前图：START → director → actor → 工具/语音实际回执 → director。director 的 `next` 为角色、`wait` 或 `end`：wait → wait_user → 用户追问 → director；end → end_dialogue → END。结束只结束话题，学习记录为 `waiting_lesson`，讲课仍暂停。仅明确继续才走原现场 RESTORE 和实际浏览器回执，不请求新的模型/TTS。正常结束原因必须为 `topic_complete`；预算达到、无进展、执行错误分别保留实际原因，不冒充正常结束。

| 身份 | 保存范围 |
| --- | --- |
| stageId | 当前用户课程；课程级历史查询范围 |
| classroomId | 一轮学习记录、课件快照、成绩、已处理讨论、播放器游标、控制租约；仍为 checkpoint thread_id |
| dialogueId | qa/discussion/legacy 话题、跨轮消息、状态及有界摘录 |
| roundId | 一次输入的模型、TTS、工具操作身份 |
| generation | 取消和回执有效性，旧代执行不能推进新页或新会话 |

`records.learning_dialogue` 保存来源学习记录、起始 sceneId/planPageId/当时 P 页码、标题、状态、结束原因与时间。`learning.activeDialogueId` 只关联当前未结束话题。新问题没有活动话题时建立 qa；讨论参与新建 discussion；WAIT 后追问沿用 dialogueId 并新建 roundId。旧历史展开不会 adopt 其课堂，不恢复旧现场或发声。

actor 与 director 读取当前话题的有效用户/最终角色消息，SQL 先按消息种类筛选，再依据 UTF-8/2 预算取得近期消息和最多 2000 字较早摘录。摘要归属话题，旧课堂 `summary` 不注入新话题。director 另有本轮发言证据，避免事件落库时差丢失最后一句。每个角色本轮实际工具请求/反馈对仍保留。完整历史与送入模型的摘录是不同查询，仍沿用当前页证据及本学习记录的真实测验保护。

新增只读接口：

| 接口 | 返回 |
| --- | --- |
| GET /api/courses/{stageId}/classroom-dialogues?cursor=&limit= | 元数据 items + nextCursor；默认50、最多100；不含摘要/全部正文 |
| GET /api/classroom-dialogues/{dialogueId}/history?after=&limit= | 同一 learning_events 日志按 seq 分页，最多500 |
| GET /api/classroom-dialogues/{dialogueId}/tool-details?roundId=&callId= | 同一会话实际工具参数与结果，完整脱敏 |

课堂旧路由仍有效。新增事件 `dialogue_started/active/waiting_user/completed/interrupted`。新图事件携带执行节点冻结的 dialogueId/roundId/generation/sceneId；流落库前再次校验有效性，状态变化事件与会话状态同事务写入。历史消息与 SSE 按 seq、messageId、roundId/callId 合并，最终消息覆盖同条增量；Pi 制作事件不参与课堂投影。

### 播放入口

课堂控制按操作对象分布：课件下方播放栏提供上一页、播放/暂停、下一页与当前页重播；互动结束且讲课现场仍存在时，主播放按钮变为“继续讲课”。右侧只展示课程对话、输入框和发送按钮，未结束的活动会话卡片内提供“结束问答/讨论”，结束后按钮消失。结束会话不会自动播放。右侧不再常驻播放、暂停、重置与历史入口按钮。

历史通过会话卡片直接展开。窄屏用顶部“课件/对话”切换视图，播放控制仍在课件一侧。当前页重播与切页确认继续校验会话身份。

- 当前页重播：保留原入口，只回到当前页起始步骤，沿用当前学习记录。
- 历史对话：仅展开只读会话卡片。进度提交也冻结来源课堂和 generation；切页/重播后旧播放器异步捕获结果不覆盖新游标。用户展开选择在同课程的课堂切换与增量更新中保持；已结束会话首次加载默认收起，活动会话首次出现展开。主动上翻和历史展开不拉回底部。

导航以及结束问答/讨论的明确结束 stop 在服务端命令锁中要求 `confirmEnd + expectedDialogueId + expectedGeneration`。普通预制播放直接切页；有活动互动或待参与讨论时必须确认。取消没有业务副作用；确认期间若话题被替换则重新确认，旧确认报 CLASSROOM_STALE。关闭视图的 stop 仍可保存为中断供恢复，不当作正常话题结束。

### 升级与兼容

初始化为 learning_events 增加可空 dialogue 列及 (dialogue,seq) 索引。旧课堂缺少 activeDialogueId 时建立确定性 `legacy:<classroomId>` 兼容组，不能可靠判断的边界明示“旧版课堂互动”。原 body、event_id、seq 不重写，只补索引；媒体引用及付费操作 ID/hash 保留。重复迁移不产生第二个组；缺少新字段的检查点在显式恢复时绑定兼容身份。历史阅读不恢复检查点。已完成模型/TTS复用原结果，running/unknown 不自动重发。

本地升级备份：`data/backups/align-classroom-dialogue-sessions/20261010-145200/manifest.json`，包括两份 SQLite backup 和全部媒体的 SHA256。回退前停止执行、保存升级后记录，再同时恢复两库/媒体和对应代码构建；不能只恢复业务库或让旧版本自行解释 waiting_lesson。

验收证据见 [classroom-dialogue-sessions-acceptance.md](classroom-dialogue-sessions-acceptance.md)，区分受控测试与真实浏览器、模型、TTS及实验回执。


### 2026-10-10 功能收敛

根据用户明确要求，删除整课从头重播、强制开始新课堂及顶部更多菜单。`POST /api/classrooms` 不再接收 intent；课堂命令不再接收整课重播。已有有效学习记录继续恢复；首次打开或课件快照失效时才建立必要的新记录。旧记录、成绩、对话和操作日志保留，旧创建回执哈希与历史结束原因只作读取兼容，不能触发已删除能力。当前页重播、切页、WAIT/END、继续讲课和历史查询保留。之前的会话验收材料记录的是当时版本，涉及已删除入口的部分不再代表当前功能。

## 当前页上下文与指示合同升级（2026-10-10）

新模型目录为六个演示工具，已移除 read_classroom_context。普通页老师获得 spotlight/laser，实验页四个 widget_*，测验页、同学及 director 无工具。原生函数调用继续使用，不复制原项目 JSON 动作数组。

新策略版本为 2，模型意图绑定 sceneId、roundId、generation、instanceId；聚光/激光只传 elementId，服务端在执行前检查已保存模型结果、原策略、当前页及元素。原始参数保存在 tool_start 和操作意图，浏览器执行参数由运行层补 sceneId；pending/ACK 继续校验页面和实例。不得以切页后的当前页重新绑定旧请求。

历史名称映射保留 read_classroom_context，旧记录与完成结果仍可读，不重发。待执行旧版本 1 指示只有保存策略、原模型结果、原页和 generation 有效且 sceneId 一致时才可兼容执行；缺少证据则明确中断。旧未发出模型请求与新策略不一致时拒绝，未知付费请求不自动重试。保存意图的参数及哈希不改写；刷新仅更新投递实例。

用户授权后 41 项课堂测试全部通过，前端构建通过；独立浏览器验收确认聚光/激光、折叠详情与无工具测验问答。详见 classroom-context-pointer-acceptance.md。固定模型和本地短音频用于验收，真实执行与 ACK；未验证供应商生成质量。用户 8001 后端未重启，需正常重启加载修改。
