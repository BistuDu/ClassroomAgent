# 课堂工具可用性验收

变更：`filter-classroom-tools-by-role-and-page`。日期：2026-10-10。

## 证据类型与结果

使用临时 SQLite、现有课堂 fixture、受控 `FakeModel` / `FakeTTS` 和 `httpx.MockTransport`。运行真实 LangGraph 节点、持久操作记录、命令/ACK 接口及两种模型协议的序列化；生成服务和播放端回执由测试控制。没有请求真实模型/TTS 供应商，也没有真实浏览器执行或声音验收。本记录证明权限、请求、错误回流及恢复合同，不将模拟 ACK 当作真实页面演示。

执行命令（Python 项目根目录）：

```sh
PYTHONPATH=.:tests .venv/bin/python -m unittest tests.test_classroom_runtime tests.test_classroom_model tests.test_classroom_api -q
```

最终运行 **33 项通过，0 failures / 0 errors**。捕获 **64 次角色/调度器请求、54 次 Mock HTTP 请求**，见 [机器可读证据](classroom-tool-availability-evidence.json)。HTTP 矩阵包含两协议 × 六身份 × 四类型共 48 次请求，其余请求用于已有协议解析/错误合同。证据带 `evidenceType=controlled_model_and_mock_http` 和 `realProviderRequests=0`。

## 已验证矩阵

| 角色 | slide | interactive | quiz | 未知类型 |
| --- | --- | --- | --- | --- |
| teacher | read_classroom_context、spotlight、laser | read_classroom_context、widget_setState、widget_highlight、widget_annotation、widget_reveal | read_classroom_context | 无 |
| curious / notetaker / thinker / director / 未知身份 | 无 | 无 | 无 | 无 |

每种工具的名字、描述、必填参数、`type:object` 根 Schema 与原七工具合同逐项一致。读取工具保留空 properties/required；修改返回 Schema 的嵌套字段不会污染后续调用。实际 actor 捕获包括三类页面及三位同学；未知 actor 在外部请求前明确拒绝，director 请求无工具。两协议对空集合均省略 `tools`，不会发送 `null` 根 Schema。角色提示的能力名与实际工具列表一致。

## 执行和恢复证据

| 受控用例 | 验证结果 |
| --- | --- |
| `test_tool_actual_receipt_and_resume` | 首次和反馈后的实验请求均提供五工具；ACK 前没有成功结果；ACK 后模型得到真实观察，继续讲课恢复原参数 |
| `test_quiz_illegal_widget_call_is_recorded_and_returned_without_delivery` | 测验页 widget 指向本页或另一实验页，均产生 tool_start/tool_end 和失败反馈；无 execution_pending，无浏览器工具操作意图，课程不变 |
| `test_invalid_tool_targets_produce_feedback_without_browser_delivery` | 不存在的元素、跨页目标、未知/越界变量、未声明控件、过长注释、额外/缺失参数及未知工具均失败；同学不能调用读取工具 |
| `test_actual_failed_receipt_reaches_actor_without_success_observation` | 合法实验先 pending；failed ACK 转成实际失败反馈，未写入成功观察或改动课程 |
| `test_navigation_recomputes_tools_and_rejects_old_calls_and_ack` | 实验切至测验后新请求只提供读取；旧 generation 工具调用/ACK 被拒绝，旧意图已撤销，测验答案/解析未暴露 |
| `test_completed_model_and_tts_replay_checkpoint_gap` | 模拟旧格式 system/messages 和参数哈希；跨重启恢复不重复模型或 TTS，原哈希与参数保持一致 |
| `test_completed_legacy_effect_replay_preserves_hash_without_redelivery` | 已完成演示直接复用结果，不重新投递，原意图与哈希不变 |
| `test_completed_legacy_model_call_is_reauthorized_on_quiz` | 旧完成模型结果虽含 widget 调用，测验页仍拒绝，无新模型/TTS 请求或浏览器投递 |
| `test_legacy_pending_and_unknown_intent_are_preserved_without_retry` | 旧 pending 明确要求重新提问；running/unknown/failed 不自动重试，记录保持原样 |
| `test_legacy_pending_recovery_interrupts_and_keeps_history` | 恢复不能安全续接的旧 pending，课堂明确 interrupted；历史保留，用户新问题使用新策略 |
| `test_new_pending_model_intent_resumes_with_matching_policy` | 新 pending 能力一致可安全续接并保持参数哈希，能力不匹配时拒绝且保留记录 |
| 已有课堂/API 用例 | 归属、媒体保护、版本、讨论、控制、语音 ended、取消及恢复合同继续通过 |

第一次测试运行出现检查点连接已关闭的清理警告：测试读到业务 waiting 状态时，图的 interrupt/checkpoint 尚可能在落盘。fixture 的 `state()` 现在等待本次图任务完成后才返回，使后续恢复/关闭验证发生在持久边界。最终运行没有该警告；生产关闭逻辑未改动。

## 范围复核

本轮文件修改清单：

- `backend/classroom_tools.py`（新增共享策略）
- `backend/classroom_runtime.py`（角色工具提供、说明及冻结意图兼容）
- `backend/classrooms.py`（执行前共享权限校验）
- `tests/test_classroom_runtime.py`
- `tests/test_classroom_model.py`
- `docs/classroom-runtime.md`
- `docs/classroom-tool-availability-acceptance.md`
- `docs/classroom-tool-availability-evidence.json`
- 父项目 OpenSpec 的本变更 `tasks.md`（完成标记）

工作前保存 13,404 个文件的 SHA-256 基线，包含原项目 2,945 个源文件、Python 项目现有文件及已安装的三个 Pi SDK 包 2,082 个文件。原项目、SDK、制作工具、现有课程/媒体和配置基线无变化；现有文件仅上述五个 Python 代码/测试/文档文件发生变化，新增文件仅为本清单。生成的 Python 字节缓存与测试临时数据库不算源文件修改。根目录没有 Git 仓库，因此采用文件内容基线复核。

`openspec validate filter-classroom-tools-by-role-and-page --type change --strict` 通过。后端尚未因本轮改动重启；正在运行的服务须正常重启后才加载新策略。没有为验收中断当前课堂，也没有改变跨页演示能力。
