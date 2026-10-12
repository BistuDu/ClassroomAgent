# 多课程会话迁移与回退

数据仍使用 schemaVersion=1、SQLite user_version=1；新 owner/session/approval/run 元数据为 version 2，`migration/multi-course-v2` 是幂等标记。启动迁移在事务中完成，只为升级前已有本地记录补归属，保留已声明其他 owner 的元数据；升级后没有归属的新增记录拒绝访问，不自动认领。

旧 stageId 映射为 activeStageId 与 linkedStageIds；Stage 文档、ID、revision、媒体、检查、事件、SDK 历史保持原样。旧待确认问题已绑定课时为改版、无课为新建；已批准未建课转换为独立可创建记录，已建课批准保留对应绑定。旧 session approvedPlan 仅保留兼容数据，不用作跨课授权。

实施前已停止后端并用 SQLite backup API 保存 `data/backups/multi-course-20261006-162009`：数据库、媒体索引、SDK sessions、contracts、文件哈希及事件水位。媒体文件未移动；报告不读取或输出 .env 凭证。备份是本地敏感项目数据，请按现有数据权限保管。

部署：停止写入 → 备份 → 同步 Python/Node/frontend 代码 → `npm run contracts` → `npm run build` → 启动后端。不可新旧契约混跑。重启会中断活动制作，保存成果保留；course_operation 按操作 ID 释放，旧 finally 不会释放新占用。

回退：先停止写入、另存升级后的数据库/SDK sessions/媒体索引和新增成果，再恢复兼容代码。保留新元数据和多课文档，不用旧数据库覆盖实时数据。旧界面可只读旧 stageId 所指课；若旧写服务仍实施单课门禁，保持只读，升级回来继续。副本可核对旧读取、ID/版本、事件与 Pi 路径是否一致。

验收采用隔离 SQLite 副本和本地确定性供应商替身；没有调用真实生图、模型、搜索或 TTS，不将逻辑验收等同供应商实测。结果见 multi-course-acceptance.md。
