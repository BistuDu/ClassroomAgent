# 自然语言课程任务迁移与回退（历史 v3）

变更：refine-natural-language-course-targeting。2026-10-06。

以下为历史 v3 上线记录。当前新运行使用 v4 RunContext/OperationRecord，旧任务保持只读；最新验收见 task-free-runtime-acceptance.md。

SQLite user_version 与课件 schemaVersion 仍为 1，协议/SDK 详情仍为 2。run/session 任务元数据为 3；启动使用 course-tasks-v3、task-resolution-hints-v3 两个幂等标记。迁移不修改 Stage、revision、媒体、检查报告、原 SDK 事件/调用详情或消息 hash。

旧 courseTargets/unfinishedGoals 保留为兼容资料，同时复制成 courseTasks/unfinishedTasks：旧 full-course → complete/course；旧 local 根据 touchedSlotIds 和真实 scene.planPageId → edit/pages。没有范围的旧局部记录为 needs_resolution；pendingFullGoal 只记录待解析提示，不能选择当前预览或把第一次写入当作整课目标。提示由同一个 Agent 结合原对话核实。

每项新任务有独立 taskId、原 requestText/sourceMessageId、answerChain、registeredRevision、scope/work、真实回执和失效记录。续接保留任务 ID、原请求与范围，另记录续接消息。旧目标列表仍参与历史消息 hash 校验，新前端不再发送；精确旧消息重放返回原 accepted，不重新执行。

## 本次备份与部署

备份目录为 `data/backups/natural-targeting-20261006-180035`，包含 SQLite、SDK pi 目录、契约和媒体索引 manifest，事件水位 204781，6 门课程、7 个会话。上线前再次确认无 Agent/配音活动，追加 pre-restart.sqlite3 与 pre-restart-fingerprint.json。未复制或输出凭证。

部署需在空闲点停止本项目后端，同步 Python/Node/frontend/课程指导，执行 npm run contracts 与 npm run build，再启动后端。不得让旧后端与新的 20 工具契约长期混跑。实际服务端口为 8001，前端开发端口为 5173。

重复迁移验证命令：`.venv/bin/python -m scripts.verify_natural_targeting_migration`。仅读取上述备份并迁移临时副本，不写实时数据库；migration-acceptance.json 保存比较结果。副本重复迁移、旧别名只读、新增产物保留及重开均通过。live-restart-acceptance.json 核验上线后原课程/媒体/检查/消息/问题/SDK 详情与水位未变。

## 回退规则

先停写并另存升级后数据库、SDK sessions、媒体及日志；保留所有 v3 原任务和新产物。不能恢复实施前 SQLite 覆盖升级后的成果。旧界面可只读 stageId 别名；旧 runtime 的首次写入目标分配不能重新启用，它无法理解逐课任务语义。需要恢复写入时使用理解 v3 范围的兼容版本，或重新上线此版本。验证脚本证明的是数据保留及旧字段读取，不声称旧写运行时支持 v3。

## 与在途规范的关系

原多课变更 add-multi-course-conversations 的 20/26 保留；引用控件相关验收改由本变更新自然语言场景覆盖，未勾选旧任务。浏览器访问受保存权限阻止时，导航/音频交互仍未验收。后续在依赖全部完成后，按 add-streaming-course-workbench → refactor-pi-events-and-course-tools → add-multi-course-conversations → refine-natural-language-course-targeting 顺序同步，逐条核对重叠条款。本次 apply 不同步、不归档。
