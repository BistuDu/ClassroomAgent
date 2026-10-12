# Pi 事件与工具重构验收

记录日期：2026-10-06（Asia/Shanghai）。变更：refactor-pi-events-and-course-tools。结果为实现和确定性回归通过，**浏览器贯通尚未完成**。

## 已执行

| 命令 | 实际结果 | 范围 |
| --- | --- | --- |
| `.venv/bin/python -m unittest discover -s tests -q` | 38 项通过 | 19 工具契约、时间线、真实安装 SDK 贯通与原有 13 项 TTS 回归 |
| `node --test tests/pi-events.mjs tests/timeline-merge.mjs tests/audio-controller.mjs tests/tool-card.mjs` | 8 项通过 | 事件快照/正文保护/重试摘要关联、增量去重、音频所有权、工具卡结构 |
| `npm run contracts` | 成功 | Python schema 导出 Node/React 共享契约 |
| `npm run build` | 成功 | TypeScript 检查及 Vite 正式构建；use-client 指令与 >500KB chunk 为已有非阻断告警 |

构建日志位于 `data/pi-events-tools-build.log`。测试不调用付费服务，不更改真实课程/配置；真实 SDK 集成测试在项目 data 内临时目录保存独立 SQLite/SDK 会话，结束删除。

## SDK 事件输入与期望节点

| 实际回归输入 | 期望与已观察结果 | 证据 |
| --- | --- | --- |
| assistant text_delta 后 message_end 给出完整正文 | 同一消息校准为最终正文，增量不含累计 partial | pi-events.mjs、test_pi_timeline.py |
| SDK start/update/end，随后 toolResult message | 同调用一张卡；冻结原参数/最终结果，进度独立 | 同上 |
| program 参数传 passed=true，被实际 SDK schema 拒绝 | 无业务 calls 缓存仍有真实错误/参数及不可变详情 | test_sdk_runtime.py |
| 第一段 TTS 完成，第二段仍等待 | SDK progress 已持久化，end 尚不存在；ACK 不等待整个业务任务 | test_sdk_runtime.py |
| auto_retry_start/end、compaction_start/end | 同一 operationId，保留状态；没有供应商正文补入 | pi-events.mjs |
| 重复序号、重复节点、旧分页、最终文本补发 | 节点数不增加、正文不重复、旧页保持顺序 | test_pi_timeline.py、timeline-merge.mjs |
| 已结束调用后迟到 progress | 不覆盖最终状态 | test_pi_timeline.py |
| 运行中取消/进程失败，SDK 无 end | 卡片有工作台中断注记，真实 SDK 状态保留，result=null | test_pi_timeline.py、test_sdk_runtime.py |
| 业务 tool_finished/user_operation 单独出现 | 新 Agent 节点为零，不能冒充订阅事件 | test_pi_timeline.py |
| 成功 SDK ask_user 后回答状态更新 | 一次工具、一张真实问题卡；刷新不能重复批准，成功后等待 | test_pi_timeline.py、test_sdk_runtime.py |
| v1 legacy 历史和同会话 v2 新调用 | 旧历史可读，新调用结果不使用旧业务缓存 | test_pi_timeline.py |
| 用户原文 + 隐藏课程上下文 + 有界完成反馈 | 用户正文一次，隐藏缺项不进 UI；同 SDK loop 有一次无进展继续后停止 | test_sdk_runtime.py |

贯通测试使用已安装 Pi SDK、生产 main.ts、生产 Python Runtime、实际 schema/订阅/RPC/落盘 ACK。测试专用 preloader 通过 SDK 的公开会话/模型流接口提供确定性模型响应，未修改 SDK 源码；这验证实际 SDK 链路，不代表真实供应商服务验证。

## 19 个工具契约

全部 19 个生产工具入口由 test_tool_contracts.py 与 test_sdk_runtime.py 调用或检验，输入/模型反馈/details 均有覆盖；provider/浏览器的部分接口使用受控替身。

| 工具 | 关键已验证行为 |
| --- | --- |
| ask_user | question 不夹带批准方案，真实等待门禁，后续调用被阻止 |
| read_skill | 固定六指导 ID，任意路径拒绝，正文返回 |
| web_search | 保存来源、返回最终版本 |
| fetch_url | URL/续读互斥，保存全文按版本续读不联网 |
| create_stage | 实际入口与 v2 结果，批准方案幂等创建 |
| list_stages | 明确数组与 v2 输出 |
| read_stage | 默认 tree 紧凑、source 长页续读、revision 冲突 |
| grep_stage | 同字段多个匹配保留、查询/版本游标冲突 |
| patch_stage | 重排后 ID 定位、删除后再次定位、整批失败无部分提交、缺 new 拒绝、反馈无整课 |
| edit_deck | 判别参数必填、实际改名与计划同步、重排定位 |
| list_scenes | 当前批准槽位、结构化缺项与目标范围 |
| generate_scene | 完整本页保存/details，模型树摘要，旧动作移除反馈 |
| generate_actions | 完整动作保留 details，模型文字长度/ID 摘要，不隐式 TTS |
| generate_image | 不支持尺寸在付费前拒绝；未知旧缓存不得重复 POST，媒体 ID 输出 |
| list_voices | 当前模型兼容列表和样音事实，既有 TTS 目录回归 |
| set_teacher_voice | 版本与兼容检查、互斥输入、紧凑影响，切换保留语言 |
| generate_tts | 独立段失败 ready/failed/ready，未知结果 uncertain/not_run；真实 SDK 逐段更新 |
| render_scene_preview | 实际 image block 与 snapshotId，details 不复制 base64 |
| check_scene | program 不接受 passed；检查不通过与设施失败分离；v2/旧报告兼容 |

独立结果回归验证数组保留、partial 不等于执行失败、真实图片块。指纹回归验证音色仅影响程序检查、讲稿语义影响视觉结论而可复用画面、未引用来源不影响其他页；局部完成反馈不会补作其他页。图片未知缓存用旧记录匹配防止再次付费。本轮没有执行真实图片生成或真实 TTS。

## 前端已验证和待验收

ToolCard 结构渲染实测：默认折叠、中英文名称和失败摘要直接可见；打开后参数位于结果上方；3000 个长字段标记完整保留；参数可独立折叠；准备/执行耗时区分；TTS 复用段计入已完成数。此测试为 React SSR，不验证浏览器点击、CSS 外观、附件播放或异步详情下载。

源码路径核对：手动配音/保存/提交/中断的 workbench 状态位于 chat-scroll 外；Agent 卡片仅来自 Pi 投影，业务事件不能生成卡。首张已保存场景自动打开只消费一次；关闭置 consumed，后续更新不强开，选页按 sceneId 保留。以上实现已完成，**以下实际浏览器行为未验收**：

- 点击工具/子折叠、异步读取完整结果、长数组/HTML滚动、图片/音频附件播放与布局。
- 第一张有效页打开、手动关闭保持、重排后选页、失败页不打开。
- 刷新/SSE 重连、历史分页、停止后继续制作、进程恢复与手动配音状态。
- 原有 Enter/中文输入法、窄屏/桌面整体视觉体验。

浏览器入口 `http://127.0.0.1:5173/` 的 native CUA 连接多次未执行：automatic approval review 服务返回 HTTP 503，提示 codex-auto-review temporarily unavailable。此为审批服务故障，未判定操作不安全；未绕过审批改走其他自动化路径。后端未重启，已有进程可能仍加载旧代码。待审批服务恢复后，先确认本项目活动运行已结束，重启本项目后端再执行上述场景；不能把源码核对或 SSR 记作浏览器通过。

真实供应商的流式工具调用、图片输入能力、图片尺寸、Tavily 与百炼 TTS 本轮均未联网验证。当前配置 DeepSeek 的截图理解能力待实际确认。此前语音实测记录可独立查 tts-verification.md，但不能替代本次端到端验收。

## OpenSpec 状态

实现任务 3.4/3.5 按代码和确定性证据完成；9.1/9.2/9.4 按回归与文档完成。9.3 的契约和构建部分完成，浏览器部分保留未勾选，因此整体 37/38，不归档。迁移/回退及后续先同步 add-streaming-course-workbench、再同步本变更见 pi-events-tools.md。

## 后续修复：供应商工具 schema 根类型（2026-10-06）

实际请求发现 ask_user 的 Pydantic RootModel 导出顶层 oneOf 无 type，供应商以 HTTP 400 拒绝（同类还包括 edit_deck/check_scene）。export_contracts.tool_parameters 为联合提供 object 根、合并属性与公共 required，保留原 oneOf 的严格分支校验；Node 启动添加根类型检查。新增全部 19 schema 根类型回归，实际 SDK 集成测试同步检查模型请求工具定义；36 项 Python 回归、契约导出及构建通过。

使用当前配置制作服务进行一次最小 chat/completions 请求，携带全部 19 个工具定义、tool_choice=none、max_tokens=32，实际返回 HTTP 200 与有效 choices；未执行业务工具。这只验证供应商接受 schema，不验证自主调用、图像能力或课堂全流程。

## 用户调整：展示 SDK 推理文本（2026-10-06）

用户明确要求展示课程模型的 thinking 文本，取代初版仅显示状态的选择。events.ts 转发 thinking_delta.delta、thinking_end.content 和最终 thinking 文本，保留 SDK 单一来源，不转发不透明签名。timeline 按同一 messageId/contentIndex 追加增量并用结束文本校准，前端显示可折叠“思考过程”，历史未保存文本单独说明。

新增真实安装 SDK 的推理事件到生产 JSONL/SQLite 的回归，覆盖推理与助手正文分离、最终校准不重复、签名排除；投影回归覆盖增量与关闭重开数据库后恢复。原先“推理正文排除”用例改为“正文传递、签名排除”。新的38项Python回归和8项Node回归、构建结果以此次执行为准。部署及浏览器检查单独记录，不用回归宣称正在运行的旧进程已更新。

此次浏览器控制可初始化，但连接工作台 URL 被用户已保存的浏览器访问偏好阻止；操作未执行，未改用其他浏览器/自动化绕过。当前用户要求保留制作中的运行，结束后再重启，因此部署等待活动运行释放后端槽位，未将未重启的当前轮次记作新实现验收。
