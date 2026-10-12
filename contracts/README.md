# 共享契约

运行 `npm run contracts` 从 backend/models.py、tool_args.py 和 tool_result.py 生成 schema.json、generated.ts；不要手改生成文件。Node 使用同一工具 JSON Schema，Python 再验证请求与写入，React 使用共享文档/事件类型。

课程文档 schemaVersion 和 SQLite user_version 保持 1。JSONL protocolVersion、事件 envelope 和 ToolDetails.schemaVersion 为 2；消息保留 source=pi/workbench/legacy、运行/调用关联、seq 与 payload，旧事件只读兼容。未知 SDK 事件保留原始事实，不推测语义。

ToolResult.content 是模型继续操作需要的文本/真实图片；details 保留同次执行的完整结构、target、changes、artifacts 和 issues。status=completed/partial/failed 与检查 passed 独立，isError 表示执行失败。数组不会变成对象。课程写工具不在 content 中回传无关页面或整课源码；读取工具返回明确请求内容与续读边界。

SDK 调用详情不可变，按 sessionId/runId/toolCallId 绑定；UI 从此记录读取参数和最终结果，SDK 拒绝参数时不要求存在业务缓存。凭证和签名查询值在保存前脱敏，业务 audioSignature 不属于密钥。

文档 API 展开 Pydantic 默认字段；工具输入仍保留各自默认值。判别输入、分页字段和兼容行为见 `../docs/pi-events-tools.md`。

模型 API 要求工具参数顶层为 object。RootModel 判别联合由 export_contracts.tool_parameters 补齐 object、properties 和公共 required，保留原 oneOf/$defs 以继续严格验证各操作分支。不能将原始联合 schema 直接注册给供应商；Node 启动也会检查这一约束。
