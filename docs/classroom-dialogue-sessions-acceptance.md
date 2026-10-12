# 课堂互动会话验收：dialogue-v1

> 历史验收记录：2026-10-10 用户随后要求删除整课重播和强制新课堂；相关入口及执行代码已移除。下文保留当时真实验收事实，涉及这两项的描述不是当前功能承诺。当前行为以 classroom-runtime.md 为准。

日期：2026-10-10。变更：`align-classroom-dialogue-sessions`。修改范围为 Python 项目与 OpenSpec，原项目仅作参考，Pi SDK/node_modules 未修改。

## 升级与数据保护

- 升级前 5 个学习记录均 paused，付费 running 操作为 0；制作运行无 running 状态。
- SQLite backup：`data/backups/align-classroom-dialogue-sessions/20261010-145200/`。两库与全部媒体共 429 个文件的 SHA256 已核对；两库在临时目录恢复后 integrity_check 均为 ok。
- 同备份对照：原有 3258 条事件的 seq/event_id/body 完全一致，9 门课程原文完全一致。新增 dialogue 索引不改旧正文，原媒体仍固定引用。
- 部署时正常停止空闲后端，再以原端口 8001 启动。兼容升级版本为 `migration:classroom-dialogues-v1`；实施文件 SHA256 见下方 JSON。回退需停止执行、保留升级后成果，恢复同一备份的两库/媒体及对应代码构建。

## 受控验收（不调用供应商）

命令：

```sh
PYTHONPATH=.:tests .venv/bin/python -m unittest test_classroom_runtime test_classroom_api test_classroom_dialogues -q
npm run build
openspec validate align-classroom-dialogue-sessions --type change --strict
```

36 项受控测试通过；TypeScript/Vite 构建通过；OpenSpec 严格校验通过。构建仍有已有依赖的 use-client 指令和大包提示，不属于构建失败。

| 场景 | 可核查证据 |
| --- | --- |
| WAIT → 追问 → END → 新话题 | test_wait_followup_end_new_topic_and_explicit_continue：dialogueId 跨追问一致、roundId 改变；END 清活动指针且保留 returnCursor；新话题模型请求不含旧话题独有词 |
| END / 预算 / 无效调度区分 | test_budget_and_bad_end_are_not_normal_completion、test_repeated_role_reply_waits_with_no_progress_reason：预算等待、无效结束原因中断，不标 topic_complete |
| 显式继续 | 受控测试断言 continue 没有新增模型/TTS请求；真实 RESTORE 回执后才 lecture |
| 重播/新课堂/确认竞态 | test_exit_confirmation_replay_new_learning_and_stale_receipt：未确认和旧 generation 不执行；重播保留成绩/讨论，同请求幂等；新课堂不继承学习状态；旧 ACK 拒绝 |
| 旧历史无损及重复迁移 | test_legacy_migration_body_identity_details_and_ownership：旧 body/seq/event_id 保持，唯一 legacy 组和原工具详情可读，其他用户拒绝 |
| 上下文筛选与身份冻结 | test_final_message_filter_and_frozen_event_identity：550 条增量不挤掉前文；旧会话状态不能继续写有效新回复；新会话无旧历史 |
| 新接口/分页/旧请求兼容 | test_course_dialogue_routes_pagination_and_ownership、test_legacy_command_hash_replay：课程目录分页、单会话历史/详情、归属隔离、旧字段缺省请求哈希复用 |
| 检查点/已完成操作/unknown | 原运行验收继续通过，覆盖 completed_model_and_tts_replay_checkpoint_gap、checkpoint_restart_rebind_and_context_budget、legacy_pending_and_unknown_intent_are_preserved_without_retry 等 |
| 角色/页面工具矩阵和测验保护 | 原运行/API验收继续通过：同学没有工具、测验无实验工具、非法请求返回实际错误、未提交答案不暴露、新学习记录成绩为空 |

受控模型、TTS和 ACK 仅证明代码合同，不当作真实供应商或播放证据。无需清理生产数据或强制重发未结算请求。

## 真实浏览器与供应商验收

环境：现有 Codex 内置浏览器，`http://127.0.0.1:8001/`；桌面 1440×900、手机 390×844，结束时恢复原视口。真实课程“牛顿第二定律：从实验到解题”，实际配置模型、百炼 TTS 与已有预制语音。没有向运行库插入假角色消息或假执行回执。

1. 旧历史首次收起；展开能读原老师/同学/用户消息。旧 spotlight 卡完整显示参数与真实结果，上下排列。当前 P 页码、播放位置和模型活动不随历史阅读改变。
2. P1 简短真实提问生成新 qa，会话卡流式更新；实际语音结束后等待追问。点击下一页出现确认，取消保持 P1 与话题；明确继续获得真实恢复回执，进入 lecture 并开始原讲稿与聚光。
3. 无互动时直接切至 P3。老师实际 widget_setState 设置 F=4、m=8；浏览器返回 state 及 observation.a=0.5，真实 instanceId 保留，工具结果标完成。随后确认切页到 P4，会话保留并记录 user_navigate。
4. 从头重播回到 P1，步骤 0/12、无旧字幕、等待开始；会话仍可展开。曾发现同页播放器旧步骤未清的问题，已通过重建播放器现场修复并重新观察步骤 0/12。
5. 开始新课堂创建 `classroom_1f0dd4adcca2490f9784ca49161e76fa`，旧课堂话题仍显示，已有展开选择保持，首次读取的 attempts/consumedDiscussions 为空；默认等待播放。
6. 手机视口能读取历史完整工具详情、访问重播与新课堂控制。新的 P3 提问实际改变 F=4、m=8；手机切页确认取消后保留 P3，明确继续后 RESTORE 的实际回执为 F=10、m=2、running=false，随后原预制动作/语音继续。结束验收时已暂停课堂。

三次真实 qa 均有对应模型和百炼语音运行。真实供应商在这些输入下选择 WAIT；Supervisor END、新话题上下文隔离和预算边界由受控验收覆盖，不声称自然模型此次选择过 END。记录不保证所有供应商请求未来均成功。

## 证据文件

- [实际状态、操作与回执 JSON](evidence/dialogue-sessions/runtime-evidence.json)：新 dialogue/round/generation、实际 tool/音频 ended 回执及独立 playback RESTORE 回执、部署文件哈希。
- [桌面历史](evidence/dialogue-sessions/desktop-history.jpg)
- [桌面切页确认](evidence/dialogue-sessions/navigation-confirm.jpg)
- [手机历史](evidence/dialogue-sessions/mobile-history.jpg)
- [手机重播](evidence/dialogue-sessions/mobile-replay.jpg)
- [手机切页确认](evidence/dialogue-sessions/mobile-confirm.jpg)
- [手机恢复讲课](evidence/dialogue-sessions/mobile-continued.jpg)
- [最终部署：刷新后历史仍可读](evidence/dialogue-sessions/final-history.jpg)

## Delta 场景核对（41 项）

以下按规范中的场景原名列出对应实现与证据。表中“代码核对”只表示实现路径核查，不声称每个分支都在真实供应商下触发。真实播放与供应商证据范围以上一节为准。

| 规范与场景 | 实现与验收依据 |
| --- | --- |
| interaction：连续追问同一概念；结束话题后再次提问；老师回答后用户追问；调度器正常结束 | question 关联当前 dialogue，director → wait_user / end_dialogue 分流；WAIT/END 受控测试核对身份和上下文 |
| interaction：参加预设讨论 | join → begin_dialogue(kind=discussion)；discussion_consumption 测试核对讨论身份和来源课堂 |
| interaction：新课堂查看旧对话；workbench：展开上一轮学习的对话 | 课程级 list_dialogues、DialogueHistory；受控新课堂测试及真实新课堂历史展开 |
| interaction：新话题不继承旧结论；当前会话有多次追问；长会话需要摘录 | bounded_history 限当前 dialogue，SQL 先筛最终消息再计预算，摘录限 2000 字符；上下文隔离与 550 条增量测试，代码核对摘录边界 |
| interaction：旧会话工具指向其他页面 | DialogueHistory 仅调用只读接口，不操作 Player；当前页 context/tool_schemas 仍独立校验；真实历史阅读及权限矩阵测试 |
| interaction：阅读旧课堂记录；重复执行兼容迁移；workbench：读取旧版课堂 | migrate_dialogues 幂等 legacy 分组，不改原事件正文；迁移/旧详情测试和生产备份比对 |
| interaction：升级时有待执行实验操作；服务在付费调用期间重启 | 原 thread_id/paid key 保留，unknown 不重试，显式恢复检查点；legacy_pending、completed_model_and_tts 与 checkpoint_gap 测试 |
| interaction：请求其他用户的课程会话 | dialogue/list/history/details 归属校验；新接口分页与其他用户拒绝测试 |
| interaction：用户明确继续；workbench：Supervisor 结束话题后继续讲课 | continue 不请求模型/TTS，RESTORE ACK 后才 lecture；WAIT 后和 END 后分别受控断言，真实 WAIT 后恢复回执 |
| interaction：回复预算耗尽；调度器输出无效结果 | director 严格解析、budget/no_progress 等待原因、错误中断；预算/非法 end/重复回复测试 |
| interaction：刷新等待追问的课堂 | recover 保留 waiting_user 身份，前端控制权需显式恢复；checkpoint_restart 测试及恢复路径代码核对 |
| interaction：旧动作被编辑删除 | live fingerprint 拒绝版本变化并中断会话，cursor 校验动作身份；progress_version_guard 测试与版本冲突路径核对 |
| interaction：从头重播后重开网页 | replay_course 保存 emptyCursor，Player 重建，progress/capture 拒绝旧 generation；最终部署真实重播后刷新仍 P1、0/12，等待开始 |
| interaction：流式回复后收到最终文本；workbench：等待追问时更新当前会话 | 按 seq 去重、dialogue/messageId 校准最终文本；project 代码核对及真实问答流式卡片 |
| interaction：浏览器无法执行实验操作；结束后迟到的事件 | failed ACK 回馈 actor，冻结 dialogue/round/generation/scene，drive 与 ACK 校验；failed_receipt、stale_receipt、navigation_recomputes 与 frozen_identity 测试 |
| workbench：长历史分段加载 | 列表 limit≤100、正文 limit≤500，前端循环读取并按 seq 合并；分页接口测试、旧长历史真实展开与加载代码核对 |
| workbench：用户比较两个学习入口；窄屏确认切页 | 独立按钮和保留/重置说明，共用 alertdialog；桌面/手机真实截图和取消验收 |
| playback：暂停并继续普通讲解；语音未结束时切页 | Player capture/restore 原音频位置，navigate 停旧声、清焦点并重建现场；原播放路径核对、真实暂停继续及普通切页 |
| playback：等待追问时取消切页；角色正在回答时确认切页；确认弹窗中的会话已变化 | exitPermission 取消无命令，确认后读最新身份；服务端命令锁再次核对；真实取消/确认、受控旧 generation 拒绝及前端竞态路径核对 |
| playback：保留学习状态重播整课；开始新的学习记录；重复请求新课堂或重播 | replay_course 保留 attempts/consumed，restart 稳定请求创建新记录；幂等与状态测试、真实重播/新课堂 |
| playback：当前页重播；互动期间取消重新学习 | start(replay) 仅当前页 navigate/restore/start，重置入口先等待 exitPermission；代码核对、未确认不变的命令测试；整课重播另有真实验收 |

范围复核：本次源码修改只涉及 Python backend/frontend/contracts/tests，文档与证据位于 Python docs，规范和任务位于 openspec。原项目源码和 node_modules 未执行写入；父目录不是 Git 工作区，因此不将 git diff 作为验证依据。最终构建与部署已包含异步现场捕获和进度回传的 generation 校验。

## 边界

旧数据只按来源课堂归组，无法还原未记录的话题边界；旧卡片明确标注。回退恢复在备份副本中核验，未覆盖生产库。历史阅读与播放器、已完成付费副作用相互独立；本次没有改动模型供应商、角色数量或工具权限。
