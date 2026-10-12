# LangGraph 课堂运行验收

验收日期：2026-10-10。变更：`add-langgraph-classroom-runtime`。

## 验收环境与范围

- 实际运行环境：Python 3.14.6、LangGraph 1.2.14、langgraph-checkpoint-sqlite 3.1.1。依赖清单支持 Python ≥3.12；本机没有单独运行 Python 3.12 验收。
- 真实课堂模型：当前配置的 DeepSeek `deepseek-flash`，completions 流式协议。课堂关闭供应商 thinking，避免有限互动输出预算被思考消耗；制作 Agent 配置不受影响。
- 真实配音：百炼 `qwen3-tts-flash`，老师沿用课程兼容音色；三位同学使用固定兼容音色。
- 首轮读取原折射课进行播放/提问；随后用 `scripts/classroom_acceptance_server.py` 在 `data/classroom-acceptance-env` 独立数据库验收，端口 8002。源课程内容、revision、讲稿、检查报告未改写。
- 隔离课共五页；P1、P2 加讨论标记。初始化生成五段真实短语音，随后 P3 改用源课程已保存的较长语音，便于验证中途暂停。没有用假音频替代真实供应商验收。

## 自动化结果

| 命令 | 实际结果 |
| --- | --- |
| `.venv/bin/python -m unittest discover -s tests` | 101 项通过，48.411 秒；日志 `data/classroom-regression-final.log` |
| `npm run contracts` | Python → JSON/TypeScript 合同生成成功 |
| `npm run build` | TypeScript 检查和 Vite 构建成功；保留原有大于 500 kB 的 bundle 提示 |
| `node tests/audio-controller.mjs` | 音频互斥与迟到 ended 通过 |
| `node tests/pi-events.mjs` | SDK 事件、独立参数/结果快照、脱敏通过 |
| `node tests/tool-card.mjs` | 默认收起、完整参数在上/结果在下、长字段与 TTS 进度通过 |
| `node tests/timeline-merge.mjs` | 最终文本校准、重放去重、分页顺序通过 |
| `node tests/pending-message.mjs` | 旧消息恢复与非法缓存处理通过 |
| `node tests/skill-resources.mjs` | 六项 Skill、渐进加载、最小回退通过 |
| `openspec validate add-langgraph-classroom-runtime --type change --strict` | 通过 |

课堂用例包括协议流/结束原因、配置整组选择、discussion 校验、归属和版本冲突、实际 ACK 必填、暂停游标、答题证据、并发租约、迟到回执、媒体引用、checkpoint 故障间隙和幂等恢复。模型/TTS 故障注入用受控响应，不冒充真实服务证据。responses 协议经过受控流用例，未用另一个真实 responses 供应商验收。

## 真实课堂结果

成功证据课堂：`classroom_8ae5d22be93741bcbf157ad5c692bdf0`。完整脱敏事实在 [provider-results.json](../data/classroom-evidence/provider-results.json)；导出脚本只读 SQLite，并读取真实 WAV 的时长与 PCM 振幅。

| 流程 | 观察及持久证据 |
| --- | --- |
| 预制播放 | P1/P2 播放真实语音，到讨论标记暂停；参与前无课堂模型/TTS 调用 |
| 跳过/参与 | 跳过 P1 后继续 P2；参与 P2 后思考者发起，其他同学按调度参与；消费状态持久保存，不自动回到讲课 |
| 实验中提问 | P3 同一 `act-02-speech-vertical` 在 7.910616 秒暂停；保存 angle=5、n2=1.33、direction=0 与显示快照 |
| 教师演示 | `read_classroom_context` 读取现场；`widget_setState` 实际设置 60°；`widget_highlight` 高亮滑块。iframe 回执读数 60°/40.6°、向法线靠拢、无全反射 |
| 三位同学 | 好奇宝宝、笔记员、思考者分别以自己的角色发言。老师与三位同学均有真实 TTS、非零 PCM 振幅和浏览器 ended 回执 |
| 明确继续 | 用户点击继续后，先收到真实 RESTORE ACK，实验恢复 5°/3.8°，再恢复同一预制动作及已保存语音位置；互动结束不会自行恢复 |
| 测验提交 | 第1题错、第2题对、第3题错，程序判题立即显示；提交后模型调用数量不增加 |
| 按需讲评 | 提问后老师准确指出第1、3题错误，解释实际选择；追问垂直入水后继续回答并等待用户 |
| 刷新 | P5、对话和答题记录恢复，默认暂停；同一窗口刷新后控制租约仍可继续操作 |
| 重新开始 | 新课堂回到 P1，历史为空；跳到 P5 后重新出现未答选项与提交入口，不继承旧成绩 |
| 制作隔离 | 返回制作台时保留输入草稿；课堂消息未写入 Pi 制作时间线 |
| 窄屏 | 390×844 下课件/讨论可切换，输入和角色可操作；没有要求真人多人房间或麦克风 |
| 最终构建回归 | 再次跳过 P1/P2，自动进入 P3 并正确初始化真实实验；暂停位置为 8.039114 秒，恢复继续同一讲解 |

### 真实延迟

以服务端持久 `user_message` 为起点，统计首次 `text_delta`、首次 `audio_ready`。音频准备延迟不是设备首次发声延迟。

| 轮次 | 首文字 | 首音频准备完成 |
| --- | --- | --- |
| 实验与三位同学互动 | 0.335 秒 | 2.017 秒 |
| 按实际成绩讲评 | 0.318 秒 | 4.922 秒 |
| 继续追问 | 0.391 秒 | 2.901 秒 |

音色兼容和播放证据可从 JSON 的 speakerId/voice/model/duration/rms16/actualEnded 核对。此次浏览器播放结束和音频有效性已经验证；没有把这些指标当作教学质量或人工音质打分。

### 页面证据

![真实 P3 实验、课堂角色和工具回执](../data/classroom-evidence/classroom-desktop.jpg)

![390×844 课堂对话与答题讲评](../data/classroom-evidence/classroom-mobile.jpg)

## 验收发现与修复

1. 真实 DeepSeek 首轮导演回复因默认 thinking 达到互动输出上限：课堂显式关闭 thinking，保留真实错误记录，不替换为模拟成功。
2. 共享历史曾让同学续写老师身份：历史改为带发言者身份的证据输入，增加明确身份约束和冒名检测；指定三位同学时补足被导演提前结束的邀请。
3. 提问前停止音频曾丢失 currentTime：先捕获/暂停，再停止音频所有者；实际验证 7.910616 秒恢复。
4. 跳过讨论曾因同一播放 key 未继续：更新 generation 与本地加载状态；P1→P2→P3 实测通过。
5. 前一问题的实验观察可能污染下一题：问题/导航清理旧观察，真实工具回执更新当前现场。
6. 刷新与准备节点之间故障可能重复请求：冻结原操作参数，恢复用日志协调，新 iframe 只改变投递实例；未知付费结果仍等待用户处理。
7. 页末“重新讲解”原先直接走下一页：显式重置本页游标再播放；与从已保存位置继续区分。

## 运行限制与运维

- 模型/TTS 外部服务仍可能返回 503、超时或不兼容错误；课堂保留文字与实际错误，显示重试/仅文字/暂停入口。无未知结果自动付费重试。
- 缺少 SNAPSHOT/RESTORE 能力的旧实验无法保证现场恢复，明确暂停；先返回制作台更新契约。课件指纹变化不能恢复旧动作，旧历史仍保留。
- 当前只有一个本地用户和单控制窗口租约；课堂恢复默认不发声，需用户操作。
- 没有自动媒体 GC；维护删除须走引用校验。备份/回退同时保存业务库、checkpoint 库和媒体，见 [运行文档](classroom-runtime.md)。
- 原课已有检查缺项以及“答对啦”固定解析文字属于源课件数据，本次运行验收不将原课程标为质量检查合格，也没有改写原题解析。
- 此次实现未归档；完成后可以另行执行 OpenSpec 归档。
