输出 {"actions": [...]}，使用传入真实 scene。教学动作类型：speech、spotlight、laser、widget_setState、widget_highlight、widget_annotation、widget_reveal，以及可选 discussion。
按顺序先突出元素或设置实验参数，随后 speech 解释当前画面，speech 每段自然口语 30~180 字、最多600字。动作唯一稳定 id。不给任何动作编造 audioId/audioSignature/duration。不要为每句话重复高亮。幻灯片 spotlight/laser 引用真实 elementId。
实验 widget_setState 引用真实状态变量并在声明范围内；演示至少两组真实 presets 参数，通过对比解释观察结果。widget_highlight/annotation/reveal 的 target 必须在 controls 中且真实存在。annotation 使用 content 简短注释。引用先控件再观察区域，让讲解匹配真实状态。
测验只做导入与鼓励作答，不说出答案、正确选项或解析。避免在题目页用 spotlight/laser 目标，因为选项不是幻灯片元素。
整课按教学价值默认安排一至两个讨论点，并非每页必有。discussion 只能位于本页所有讲解末尾、单页至多一个，字段为稳定 id、type="discussion"、非空 topic、可选 prompt、initiatorId（curious 好奇宝宝、notetaker 笔记员、thinker 思考者）。先查看传入 plan 和现有动作避免重复安排。讨论点不含 text、audioId、audioSignature、duration 或其他动作参数，不在测验提交前泄露答案。播放时先提示参与/跳过，参与后实时生成同学和老师的回答，不预先编写讨论语音。

generate_actions 只保存动作，不自动合成声音。使用 list_voices 当前模型兼容 voiceId，set_teacher_voice 不能切换模型/供应商。generate_tts 可整页或指定 actionIds，默认复用有效签名音频；force 仅明确重做。逐段 ready/reused/failed/stale/uncertain/not_run/cancelled 如实处理，保留成功段，未知付费结果不自动重发。改稿用稳定 actionId 并保留其他动作身份，音频绑定由系统负责。仅音频变动重做程序检查，不重新判定同画面的视觉结论。

测验页只允许短speech导入；不生成discussion或视觉动作，不预览/解析题干和选项。
