# 当前页上下文与指示工具验收

日期：2026-10-10；变更：align-classroom-langgraph-context-and-pointer-tools。用户已明确允许测试及浏览器验收。

## 运行范围

独立服务 http://127.0.0.1:8010 使用本次后端代码和 `npm run build` 生成的前端，不改用户 8001 服务或课程库。固定模型通过真实 ClassroomRuntime/LangGraph 请求、操作日志、SSE 和浏览器播放器执行；短本地静音 WAV 用于真实 ended 回执。没有调用真实模型或云 TTS，本验收不证明供应商生成质量或音色。

运行夹具：`scripts/context_pointer_acceptance_server.py`；本轮数据：`data/context-pointer-xrx73_su`。代码和前端构建 SHA256、实际请求统计、完整工具事件保存于 `data/context-pointer-browser-evidence.json`。

## 自动验收

命令：

```sh
PYTHONPATH=.:tests .venv/bin/python -m unittest tests.test_classroom_runtime tests.test_classroom_model tests.test_classroom_api tests.test_classroom_dialogues -q
npm run build
```

最终结果：41 项测试全部通过（60.061s），前端构建通过（4.13s）。测试结果及构建日志分别保存于 `data/context-pointer-tests-final.log`、`data/context-pointer-build.log`。

覆盖：

- 两种模型协议中的 2/4/0 工具矩阵、角色无工具、对象根 Schema、elementId-only 合同与 Schema 副本隔离。
- 课程名称和描述、前五页目录、总页数与剩余页数；第七页在目录之外仍获得正文；老师与三位同学共享当前页证据，其他页正文不注入。
- 工具回执后刷新观察，保留 assistant/tool 配对，证据只出现一次，旧独立证据消息删除。
- 未提交测验隐藏答案，已提交成绩有效且按课堂关联。
- 聚光和激光原始参数与内部 sceneId 分离；无效元素、额外参数、越界实验变量、未声明控件、非法角色和测验工具拒绝。
- 切到存在相同 elementId 的另一页后旧请求拒绝；旧 ACK 失效。
- 真实失败回执不形成成功观察；超时保留待执行意图并明确中断。超时测试仅跳过等待时长，执行真实超时处理函数。
- 版本 1 待执行指示显式兼容、刷新投递实例而不更改意图哈希；历史读取记录保留；完成结果复用；身份缺失/策略变化/结果未知不自动付费重试。
- 话题历史隔离、WAIT/END、切页确认、恢复现场和所有权合同回归。旧固定发言次数测试更新为现有时间预算合同，未修改调度生产代码。

## 真实浏览器观察

使用 Codex In-app Browser，通过真实 UI 操作，没有模拟浏览器 ACK。

1. 进入隔离课堂，提问“请聚光标题”：标题高亮、其余区域变暗；工具卡默认折叠；实际回执后显示完成。
2. 展开聚光工具详情：参数只有 `elementId: title`；结果保留 generation、operationId、sceneId、status 及 displayed=true。
3. 提问“请激光标题”：标题中央出现红色激光点，约 650ms 后消失；实际结果 displayed=true、completed。
4. 互动期间下一页要求确认；确认后旧话题结束且历史保留，进入 P2。
5. P2 测验未提交时提问正常回复并等待追问；保存模型请求 tools=[]，问题证据无 answer/explanation；该话题没有工具调用。

截图：

- `data/context-pointer-spotlight.png`：聚光及展开详情。
- `data/context-pointer-laser.png`：红色激光点。
- `data/context-pointer-quiz.png`：测验问答。

独立夹具初始将 skills 链接至项目外层，工作台显示“Skill 根目录超出项目范围”；这是夹具配置限制，不影响课堂验收。已将夹具改为复制 skills，未改生产 Skill 边界。课堂浏览器控制台无 error/warn。构建存在既有第三方 use client/chunk-size 提示，构建成功。

## 保留范围

本次没有跨页正文读取、多页比较或整课真实证据总结；目录仅含元数据。原工具结果 12000 字符限制未改造。此验收没有重启用户 8001 后端，生效仍需正常重启。
