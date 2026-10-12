# Pi 事件与课程工具（20 个业务工具）

## 事件路径与权威来源

制作 Agent 运行采用唯一的事实路径：

```text
Pi session.subscribe → events.ts 同步快照 → stdout JSONL v2
    → Runtime 独立消费者 → SQLite 事件/调用详情/时间线投影原子保存
    → 持久化 ACK → SSE 或历史分页 → useTimeline/ChatTimeline/ToolCard
```

Python 业务工具的内部请求、进度和结果经 stdin 串行 RPC 返回 Node，execute/onUpdate 再交给 SDK；只有 SDK 发出的执行事件进入 Agent 卡片。业务 calls 缓存仅处理幂等与诊断。供应商 callback 不产生对话正文。隐藏课程上下文与完成反馈不显示为用户/助手消息。

学习课堂使用独立的 LangGraph、持久课堂事件和播放器回执，详见 [课堂运行](classroom-runtime.md)。课堂发言与临时演示不写入这条 Pi 制作时间线，不使用制作工具修改课程。

新事件标记 source=pi/workbench；旧事件用 legacy 保留。messageId、toolCallId、runId 与序号用于增量合并、最终消息校准与重复投递去重。toolResult 消息和执行结束不产生两个卡片。未知 SDK 事件保留事实而不推测其语义。重试/摘要保留 operationId，恢复成功不因早期失败结算错误。按用户明确选择，模型通过 SDK 返回的 thinking 文本流式显示为“思考过程”，不标成公开摘要；结束文本校准同一块且刷新可恢复，签名不转发。旧版被过滤的文本无法从时间线恢复，明确标为未保存。

工作台另行展示提交、保存、手动配音、停止及进程中断。它可以对最后真实调用标记 workspaceStatus=interrupted，sdkStatus 保留真实状态；无法得到 SDK 最终结果时 result 保持空，不伪造结束。成功 ask_user 的 SDK 结果派生问题卡，是否已回答仍由工作台持久状态校验。

详情按 `sessionId:runId:toolCallId` 读取不可变 pi_tool_detail。工具展开不会再次执行。参数/结果全部业务字段可查看，图片/音频显示附件；凭证和签名 URL 脱敏。模型收到真实图片 content，UI 保存媒体 URL，不将 base64 复制进每条时间线事件。

## 输入与结果

`content` 是模型执行下一步需要的紧凑事实；`details` 是用户完整查看的同次执行记录；`isError` 是执行失败。详情 v2 包含 status、target、data、changes、artifacts、issues。completed/partial/failed 不等同于检查 passed；程序检查执行成功但发现缺陷时 isError=false、passed=false。

读取工具返回请求正文和续读边界，不能为了精简把要求读取的内容偷偷删掉。写入工具返回 ID、revision、实际影响、缺项与回读位置；不把无关页面、整课源码或完整讲稿再次放进模型上下文。生成页面/动作的 details 同样保存紧凑结果；完整源码和讲稿用 read_stage 按需回读。details.operationRecord 保存参数哈希、版本、状态和实际影响，完整参数保存在 SDK 调用详情。

| Python 工具 | 关键输入 | 模型反馈 / 完整详情 | 原项目对应与本项目取舍 |
| --- | --- | --- | --- |
| ask_user | kind=plan_approval + plan，或 question + options | 问题 ID、等待状态 / 问题与批准方案 | ask-user.ts；保留真实批准门禁，普通问题不能夹带批准 |
| read_skill | 16 个内置 Skill 的 skillId/path/offset/limit | 实际指导正文、续读边界 / 同次读取 | skill-edit-tools.ts read_skill；本项目只读固定指导，不开放技能文件写入 |
| web_search | query、limit≤10 | sourceId、摘要、最终 revision / 本次来源 | web-search.ts；批量去重一次提交，资料不是指令 |
| fetch_url | url，或 sourceId/sourceVersion/offset | 保存正文的一页、完整性、下一偏移 / 本次读取 | fetch-url.ts；增加独立正文版本，续读不联网，旧摘要标 excerpt_only |
| create_stage | approvalId/theme，批准方案来自独立新课批准记录 | stageId/revision/目录 / 本次创建摘要 | curriculum-tools.ts；本项目课程计划有明确批准锁 |
| list_stages | query/limit/cursor，taskOffset 只读续查历史任务，兼容无参 | 更新时间、保存/计划页数、有限任务摘要、续查 / 同次列表 | 原项目课程发现/历史能力；本项目仅列 local 归属课程，关联不等于新任务授权 |
| rename_stage | stageId、expectedRevision、title，可选 description | 新课程名称、描述、revision、变更摘要与回读 / 同次元数据回执 | Python 的课程根元数据专用入口；不再由 patch_stage 修改课程标题 |
| read_stage | tree/text/source、sceneId、path、offset/limit/revision | 请求投影与版本边界 / 同次读取 | dsl-tools.ts；默认结构，稳定页面 ID，兼容旧零基 Pointer |
| grep_stage | query、text/source、sceneId、limit/cursor | 所有匹配的位置、ID、续查 / 同次匹配 | dsl-tools.ts；游标绑定查询与版本，不丢同字段后续匹配 |
| patch_stage | expectedRevision、判别 operations、稳定 target | 单页 content/actions 或独立课程 theme 的实际修改、版本、影响与回读 / 本次原子修改 | dsl-tools.ts；单次页面补丁限制为一个 scene；课程/页面元数据迁到专用入口 |
| edit_deck | insert/delete/rename/set_brief/set_sources/reorder 各自必填参数 | 目标页面或目录、版本、影响、元数据是否使生成内容过时 / 本次调整 | course-edit/tools.ts；标题同步，来源须属于本课且已在当前对话读取 |
| list_scenes | stageId | 全部批准槽位、sceneId、issues、ready / 同次状态 | generation-tools.ts；新增 missing/stale/failed/uncovered 可定位缺项 |
| generate_scene | pageId/brief、expectedRevision、sourceIds/mediaIds | 页面树、revision、清空动作及语音影响 / 本页结果摘要与回读 | generation-tools.ts；无状态内容服务，不是第二个 Agent |
| generate_actions | sceneId、expectedRevision、guidance | 动作 ID/类型/文字长度/语音缺项 / 本页动作摘要与回读 | generation-tools.ts；动作、语音独立，允许只重写讲解 |
| generate_image | prompt、ratio 或 size | mediaId、请求/供应商/真实尺寸、适配问题 / 本次媒体 | generate-image.ts；不自动嵌图，不支持尺寸先报错，避免付费试探 |
| list_voices | 无参 | 当前模型兼容 voices 与样音状态 / 同次目录 | roster-tools.ts；固定百炼子集，无多供应商角色/克隆，未实测不称 verified |
| set_teacher_voice | voiceId、speed、expectedRevision，或旧 teacher | 老师配置、revision、失效范围 / 本次调整 | 原项目 set_roster 声音绑定；本项目只有老师，不开放 roster/任意模型 |
| generate_tts | sceneId、可选 actionIds、显式 force | 每段状态、错误、revision / 全部本次段落结果 | course-edit/tools.ts、scene-tts.ts；Agent/网页共用合成与签名复核 |
| render_scene_preview | sceneId、视口、可选 state | 真实 image、snapshotId/目标/指纹 / 元数据与附件 | scene-preview.ts；同一正式渲染器截图，模型图片拒绝明确报错 |
| check_scene | program；或 visual+snapshotId/passed/findings | reportId、executed/passed、issues/coverage/uncovered / 完整报告 | 原项目预览/修正与相关评测能力；本项目新增明确持久检查门禁，无完全同名工具 |

原项目位置以 `OpenMAIC-main/lib/server/agent-runtime/` 为基准。对照是职责映射，不能把原项目全部 Agent/工具总数说成 20。本项目保留原有业务入口，新增 rename_stage，已移除任务登记入口。兼容能力共享校验/事务而非重复实现。

## 协作方式

1. 同一个 Agent 根据用户请求理解目标，用 list_stages 发现课程，以 read_stage/list_scenes 核实稳定课程、页面 ID 和版本，再直接调用业务工具。运行层将读取证据保存为 RunContext；当前预览不作为写入授权。新课先确认方案，create_stage 使用本轮有效批准。
2. generate_scene 制作页面，generate_actions 独立制作讲解和教学动作，generate_tts 独立配音。预览和检查使用 render_scene_preview/check_scene，发现问题按稳定 ID 回读和修复。
3. CourseStatus 根据实际课程文档、媒体文件和检查指纹计算整课就绪。局部运行只处理本轮目标页新增缺项、实际失效和未解决的操作失败，同时保留独立 courseReady 和整课缺项数量。本轮明确批准的新课目标可结算整课；目录可读和首次写入不要求自动完善全课。
4. OperationRecord 核对 runId/requestId、工具名与完整参数哈希；相同请求返回原回执，参数变化报 REQUEST_CONFLICT，已开始但缺完整回执报 OPERATION_UNCERTAIN，禁止自动重复付费操作。真实 SDK start/end 通过 toolCallId 关联，不伪造 SDK 事件。
5. 结束前最多额外反馈两轮，相同缺项无进展、等待、取消或付费结果未知时停止；工作台结算不补写 Agent 回复。

旧 courseTasks/unfinishedTasks 和旧工具事件保留只读，新运行不更新这些字段。旧登记调用返回 TOOL_REMOVED 迁移提示；已缓存历史登记结果可只读重放。旧任务和 lastRunContext 仅供恢复参考，新运行必须重新读取目标。每次调用继续校验归属、版本、页面关系和锁，提交前复核实际影响范围。语义目标由 Agent 理解，后端依据稳定 ID 和工具允许范围校验。

版本冲突先重新读取，不能用旧下标覆盖新页面。稳定 target 每个操作重新解析，删除前序元素后仍定位同一 elementId。replace_text 必须显式 old/new，new="" 才是删除。分页时保留 revision/sourceVersion，变化返回 STALE_CURSOR，不拼接不同版本正文。

TTS 每段有 ready/reused/failed/stale/uncertain/not_run/cancelled。可隔离失败不丢成功段并可继续独立段；公共鉴权/配置失败或未知结果停止后续。force 不用于自动绕过结果未知；人工明确重做才重新付费。

## 检查有效性

renderFingerprint 绑定画面；visualReviewFingerprint 另外绑定讲稿语义、动作目标、引用来源与目标；programFingerprint 包含音频文件、签名及覆盖。单纯补音频或换声音不使相同画面的视觉报告过期；改讲稿需要重审语义但可复用画面。未引用来源变化不使其他页过期。旧报告保持旧规则，只能依旧指纹精确匹配，不能自动宣称 v2 通过。

截图成功不是视觉通过。浏览器无法运行为 executed=false 的执行错误，实际检查发现溢出为 executed=true/passed=false。模型不支持图片则报告 MODEL_IMAGE_UNSUPPORTED，不能用文字猜测通过。本地程序/视觉门禁不代表独立教学效果或科学正确性评测。

## 迁移与回退

实施前备份位于 `data/backups/pi-events-tools-20261005T184725Z`，记录 SQLite、SDK sessions、旧契约与 manifest；事件水位 11991。未复制凭证。文档/SQLite 版本保持 1，新增 SDK 详情、回执与来源记录；协议、事件、详情为 2。旧历史只读兼容，新运行不从旧缓存生成新卡。

回退操作必须先停写并备份**升级后**数据库、SDK sessions、媒体及日志，再恢复对应代码/依赖锁版本。在独立副本恢复实施前快照供比对；不能用旧 SQLite 覆盖活动数据，也不能删除新增媒体“恢复”。旧代码不理解的新记录保留原样，若需兼容导出，在副本上执行并验证原始事件/成果完整性。SDK 会话与课程文档分别保留。

原项目及 node_modules 为参考，未修改其源码；此次未变更供应商配置与密钥。不在 apply 阶段归档/同步。历史 v3 元数据迁移与部署见 `natural-targeting-migration.md`；保留以上历史验收，最新记录见 `natural-targeting-acceptance.md`。后续同步顺序为 add-streaming-course-workbench → refactor-pi-events-and-course-tools → add-multi-course-conversations → refine-natural-language-course-targeting，以免重叠条款覆盖新边界。

当前 v4 运行上下文与移除验收见 [task-free-runtime-acceptance.md](task-free-runtime-acceptance.md)。本次没有重启生产服务或修改现有课程数据。
