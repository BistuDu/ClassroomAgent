# 对齐验收记录

日期：2026-10-10；中文输入法人工验收补充：2026-10-11。变更：align-python-skills-and-generation-prompts。

## 6.1 资源和加载合同：完成

- SDK loader 发现16项，公开索引不含正文，无诊断；`node tests/skill-resources.mjs` 通过。
- `tests/test_skills.py` 4项通过：真实SDK发现、YAML诊断/名称碰撞、受限路径、分页、资源新增/修改/移除和不可变运行快照。
- `node tests/skill-selection.mjs` 通过：多个handle去重；URL/路径/代码排除；120000 UTF-8 bytes体积预算；缺页、不同版本、正文哈希不符及摘要均不能证明完整加载。
- SDK运行验收六组通过：完整分页前两次写入被阻止、未知/四项选择超限进入真实ask_user、实际SDK compact后重读、50次正文/reference/旧别名读取及4次拒绝路径、读取中重载仍返回冻结版本、正文体积超限进入真实ask_user。
- 全资源场景54个调用均有真实SDK工具事件、content和details，正文与冻结快照逐项相等。验收时间线读取显式分页，避免默认50项造成缺证。
- SDK测试模型响应由`ModelRuntime.streamSimple`测试入口提供，生产streamFunction、加载策略、beforeToolCall、afterToolCall、压缩流程、订阅、RPC和Python持久化均实际执行。没有伪造preload消息或前端工具卡。此为合同验证，不能代表真实模型选择能力。
- 当前配置模型的真实制作运行另有read_skill→read_stage→登记范围→生成页面→生成动作及pro-editing流程证据。旧SDK流程22项回归通过，资源加载和显式加载新增场景通过。

原始材料见`resource-evidence.json`及`sdk-acceptance-evidence/*.json.gz`。每份压缩JSON保存提供商实际上下文、运行、事件、时间线和工具详情，标注测试响应来源。

## 6.2 教学方法与生成集成：完成，记录实际质量发现

运行脚本：`scripts/skill_alignment_acceptance.py --live`。使用独立数据库/课程/会话，真实当前制作模型（没有测试响应替换）。原项目、用户已有课程和历史没有改写。

- 工作坊：三页slide/interactive/quiz，分别有13/17/2个动作；brief和guidance明确“先预测→动手→反馈”。
- 讲授：一页slide，13个动作；brief和guidance明确合外力→比例关系→同一购物车案例→定律。两种方法在实际内部输入中可辨识，未向内部请求复制全部Skill正文。
- 8个真实内部生成请求记录固定类型模板及JSON Schema；三种页面和三种动作使用各自规约，Scene/ActionOutput验证后保存。
- pro-editing真实读取后patch_stage只把第一页title元素fontSize从48改为36。其他元素、其他两页及该页动作保持一致，没有重建课程。
- 真实浏览器查看三页型和讲授页。实验预设F=8 N,m=2 kg后真实读数a=4.0 m/s²；测验提交前只显示题目与选项。截图见`browser-evidence/`。
- 页面生成返回actions=[]，随后独立generate_actions；没有调用generate_tts，没有新增音频/media。课程显示待完善符合验收范围，未宣称整课就绪。
- **实际发现**：讲授页公式与说明文字有重叠，工作坊公式也需视觉复核；提示词提供布局规则不等于生成页必然合格。本轮完成的是方法/格式/保存/渲染集成验收，没有调用程序或视觉检查，未把截图发现写成质量检查通过。课程质量仍应由既有check_scene与局部修正流程处理。

原始材料见`live-generation-evidence/`：三次真实运行、8次模型输入、保存课程、最小编辑比较；所有JSON/JSONL可gzip解压读取。原隔离运行目录为`data/skill-alignment-92vnbuwo`。

## 6.3 制作输入浏览器验收：完成

以前自动审批服务503为历史阻塞；本次浏览器入口已恢复，可以实际操作。

已实际验证：

- 桌面菜单来自真实16项索引；中文“工作坊”查询，Enter只补全不发送；方向键选择第二个“费曼”命令，正文保留。
- 390×844窄屏菜单可滚动；收起导航后输入、菜单和发送入口可访问；临时viewport已恢复。
- 已创建隔离对话，刷新后草稿`/workshop-style 请用中文说明 /feynman-learning 两种方法`完整保留。
- 验收服务中故意首次返回503；刷新后仍显示原消息和“重试原消息”。两次POST载荷完全相同，包括messageId、文本和关联字段。
- 重试后真实SDK只创建1条用户消息，执行2次read_skill和1次ask_user；浏览器能展开实际参数、正文、content/details、哈希、快照版本和分页结果。此UI场景使用受控测试响应，但SDK运行/工具执行/订阅完全真实。

真实中文输入法组合输入由用户人工验收：2026-10-11，用户在隔离页`http://127.0.0.1:8011/`的制作输入框使用真实中文输入法输入“工作坊”，候选字确认时按Enter，并明确反馈“已验证：确认候选字没有误发或误选”。此项依据为用户实际操作确认，不是代理填充中文文本或脚本模拟composition事件。结合上述浏览器操作、画面与发送载荷证据，6.3完成。

## 验证与范围

前序npm build、合同再生与OpenSpec严格校验已通过。本次仅增加/更新Python验收入口、测试、证据和本变更tasks；没有修改原项目或SDK。主规范、其他待办保持本次范围外。用户现有服务未重启，本次浏览器使用8011隔离服务。
