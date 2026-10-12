# Pi SDK 运行桥

`main.ts` 由 Python 为每轮启动并恢复同一项目内 SDK session。仅使用公开 SDK 接口，不修改 node_modules。通用编码工具禁用，20 个课程制作工具的参数来自共享 schema；任务登记工具已移除，资源仅来自项目的标准课程 Skill。

`skill-resources.ts` 使用 SDK `DefaultResourceLoader` 和 `parseFrontmatter` 发现资源。Python 在每轮开始时固定资源快照，运行时通过 SDK 的 `skillsOverride` 装载同一份索引。最小系统提示只加入名称、描述和相对路径；正文和 references 通过受限 `read_skill` 分页读取。诊断发送到 Python 持久记录，并写入 SDK 隐藏 custom 会话消息；不生成助手回复或课程完成状态。资源重载只影响后续运行。加载失败使用最小提示，所有业务工具权限保持不变。

stdout 为 JSONL v2，stderr 为日志。`events.ts` 同步复制 `session.subscribe` 消息、内容块增量、工具准备/开始/更新/结束、重试和摘要事件。增量不包含累计全文；最终消息按同一 messageId 校准。toolResult 消息不重复执行结束卡片。thinking_delta 正文经 SDK 事件进入界面，thinking_end/message_end 校准完整文本；thinkingSignature 等不透明签名不转发。隐藏 custom 消息与内部上下文整理正文不进入界面。

业务工具使用内部 RPC 请求 Python；实际进度经 execute 的 onUpdate 返回 SDK，最终 content/details/isError 经 SDK 结束事件进入 UI。Python stdout 消费不等待业务工具完成，stdin 写入串行；事件持久化后 ACK，最终结算等待发送队列 drain/ACK，背压不丢事实。业务缓存只用于幂等。

beforeToolCall/afterToolCall 与 Python 权限锁共同处理 ask_user、取消、预算。公开 finishTurn 以隐藏上下文反馈相关缺项；最多两次额外继续，无进展停止，不重置预算、不增加工具。用户原文单独进入 prompt。

Pi 配置、模型缓存和会话位于项目 data/pi。测试可用 PI_CODING_AGENT_DIR 指向项目 data 内隔离目录。截图是模型真实 image block；模型拒绝图像时明确报告 MODEL_IMAGE_UNSUPPORTED。事件持久化和前端使用已保存媒体附件，不保存 base64 到聊天节点。

架构、迁移、20 个业务工具对照及验证记录见 `../docs/pi-events-tools.md` 和 `../docs/pi-events-tools-acceptance.md`。
