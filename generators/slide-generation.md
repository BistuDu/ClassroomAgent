输出一个 Scene JSON 对象，content.type=slide，使用传入 page.id 作为 planPageId，type/title/brief 与方案一致。scene.id 由调用方提供或保持已有 ID。actions 初始为空。
幻灯片是 1280x720 逻辑画布。根据教学关系自行构图：概念网络使用形状和连线，过程使用路径和箭头，对比使用两侧结构或表格，定量关系使用真实柱状/折线/散点图，图文页使用可用 mediaId 配图。不能每页只有标题加相同项目符号。每页有清晰主结论和视觉重心，文字简短但解释充分；多个页保持统一主题与细节变化。
元素 type 支持 text/image/shape/line/table/chart/formula。必须唯一稳定 ID，位置和尺寸在画布内；留至少 40px 边距，内容不溢出。正文建议 >=24px，标题>=40px。表格等宽行，图表需要真实含义与单位；不编造来源数据。公式用 KaTeX 语法。line 用容器对角线表达连接，rotation 可调整方向。文字是纯文本，不输出 HTML。
image 只能引用传入已保存 mediaId，不引用外部 URL、不编造媒体。背景、前景、强调色使用课程 theme。不要让连线穿过文字；尺寸足够容纳文字。sourceIds 只能引用上下文中实际资料。

页面生成与动作、TTS 分开。生成成功反馈仅有页面树与标识，完整内容在 details，可按稳定 sceneId 回读；不要因反馈精简而重建页面。修改用稳定 elementId，保留未改元素 ID；重做页面会清空旧动作，必须补动作/语音并重检。配图先确认真实尺寸，再布局；仅引用已保存媒体。

## 原项目规则的 Python 适配
幻灯片是视觉辅助，口述解释、鼓励、过渡和角色台词进入actions，不写“老师说/某老师提醒”。每个要点尽量控制约30个汉字；长解释拆讲稿，不删除事实条件。页面标题以内容为中心。数组后面的元素盖在前面的元素上，背景形状先于文字。
按证据关系选择版式而非统一模板：机制图、比较表、真实图表、独立公式与图片。对称/并行内容用相同几何值；连接箭头留60–80px通道，不穿文字。正文纯文本，LaTeX只在formula.text，不放text/table。画布保留40–50px边距，字体层级与留白一致，theme决定颜色。字号不能靠硬缩解决长文，实际渲染确认容量。
Python type仅text/image/shape/line/table/chart/formula：x/y/width/height；line的strokeWidth是线粗，width/height是范围，不能照搬原项目width=线粗的规则。table.rows为等长字符串行；chart.points含x/y/label/series，chartType仅bar/line/scatter且明确单位。image仅已保存mediaId；不提供视频或外部URL。
合法元素示例（id须在本页唯一）：{"id":"compare","type":"table","x":48,"y":180,"width":700,"height":240,"rows":[["条件","观察"],["改变入射角","折射角随之变化"]],"fontSize":28}。
有效用户意图优先：context.plan/page/brief已经包含讲授弧或工作坊任务时落实相应视觉关系与任务，不只复述Skill名。页面初始actions=[]；不能自动制造配音、动作或通过报告。
