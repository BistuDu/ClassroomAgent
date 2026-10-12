# Skill 与制作提示词对齐

变更：align-python-skills-and-generation-prompts。日期：2026-10-10。

## 两层知识入口

外层 Pi Agent 只得到 16 项索引（名称、中文标题、用途、命令、版本与正文大小）。正文及 references 由受限 read_skill 真实分页读取；每轮固定 SDK 发现的不可变快照。内部生成模型自动接收 generators 下的固定格式与制作规则：普通页、实验、测验，以及公共讲稿加按页型选择的动作片段。无需先读设计 Skill 才能得到基本生成规约。

用户可在制作输入框使用 /workshop-style、/lecture-style 等命令，兼容 /skill:name。多个独立 handle 有序去重，URL、路径和代码中的文本不作为命令。中文标题/用途可搜索，选项直接补全实际草稿；Enter 确认菜单选项，Escape 关闭，中文组合输入不误发。选择仅用于当前请求，不保存 course.skillId；原草稿、pendingMessage 文本、消息 ID 和重试流程保持。课堂 LangGraph 输入不接入此菜单。

## 完整加载门禁

agent-runtime/skill-selection.ts 集中配置：默认最多 3 个不同正文、合计 120000 UTF-8 bytes。未知或超预算选择在写入前须通过真实 ask_user 缩小选择，不静默删除。所有业务生成/写入及方案审批受门禁约束；读取和澄清可继续。

完整覆盖按 snapshotVersion、skillVersion、canonicalId、path、bodyHash 核对。read_skill 的 offset/total/nextOffset 为 Python Unicode 码点，正文哈希为原 UTF-8 SHA256。模型 content.text 保留真实分页 JSON；details.data 保留同段及元数据，索引不包含正文。连续分页覆盖 [0,total) 且终段 hasMore=false，再重算全文字节数/哈希，才算完整。

门禁检查实际送给提供商的上下文，摘要和历史已读标记不能代替正文。同批工具中读取后直接写入仍需下一次模型请求看到正文。本轮实际自动读取的方法记录为本轮依赖，压缩后缺失时重读冻结资源；不会把旧请求的选择永久绑定。连续三次绕过加载的写入尝试停止，真实读取仍服从原工具次数/运行时间预算。不会合成 assistant/toolResult 预加载事件。

用户要求优先于方法默认，显式选择优先于自动匹配；实质冲突先澄清。教学意图通过批准方案 pages[].brief、generate_scene.brief 与 generate_actions.guidance 传入内部模型，不复制所有资源全文。

## 迁移与兼容

manifest.json 记录来源与源 SHA256、目标、适配原因和目标哈希。legacy-six 保存替换前六项资源，不在 SDK 可发现根目录中。

|旧入口（含短名称）|实际目标|
|---|---|
|course-authoring / course|stage-design/SKILL.md|
|slide-design / slides|slide-craft/SKILL.md|
|interactive-simulation / simulation|stage-dsl/references/simulation.md|
|narration-actions / narration|stage-dsl/references/actions.md|
|inspection-quality / inspection|stage-design/references/inspection.md|
|quiz-design / quiz|stage-dsl/references/quiz.md|

course-workflow.md、course-workflow-legacy.md、legacy-skill-map.md 保持明确兼容路径；其他路径不盲目拼接。返回 requestedId/requestedPath 与 canonicalId/path；SDK 历史与课程不改写。菜单只有 16 项。

暂缓 curriculum-planner、spiral-curriculum、page-clone、pptx-import、style-clone、teacher-style-clone、vocational，以及 build-personal-skill。原 outline-constraints 仅作按需教学审阅参考，不接入隐藏绑定或严格比例检查器。

## 有意保留的 Python 差异

- 页面、动作、TTS 分别生成；generate_scene 初始 actions=[]，generate_actions 不自动配音。
- 普通页为 1280×720 纯文本七种元素；无原富文本 canvas 路径、视频或十类元素。
- 实验为数值模拟与 openmaicSimulation；可信 bridge 管理消息/恢复，生成内容不自写 postMessage 或访问 parent。
- 基础测验是单选，options 为稳定 id/text；开放解释/理由在课堂对话中收集，不宣称静态动态评分。
- 固定老师与三位同学，无 set_roster/PBL/系列创建；同学只发言，预制 speech 仅老师。
- 程序/视觉检查、质量指纹、修复/生成预算、音频有效签名、归属、revision 和真实审批照常执行。事实核查不是程序/视觉通过。
- 工具 content/details 和前端过程继续来自真实 SDK 订阅。set_course_tasks 的独立移除变更不在本次范围。

验收现状见 acceptance.md。资源回滚可恢复 legacy-six；业务库、媒体、SDK 历史无需回滚或清空。
