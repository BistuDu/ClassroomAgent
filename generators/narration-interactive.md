# 实验页动作
仅speech、widget_setState/highlight/annotation/reveal及可选末尾discussion，禁止spotlight/laser。selector来自scene.content.controls且真实存在，state键来自initialState并遵守variables范围；不猜其他引擎约定ID。
先指出控件→设置真实预设→speech解释观察→第二组对比；至少两组真实presets值。annotation.content只写可读简短提示。动作变化需可见，不脚本化全部可能交互。方法意图若先预测/自行尝试，不提前说答案。不要以input.value改变当state更新，真实bridge调用setState。
示例结构：{"actions":[{"id":"set_low","type":"widget_setState","state":{"angle":20}},{"id":"explain_low","type":"speech","text":"先观察这组参数下的结果，再与较大角度的预设进行比较。"}]}。变量/数值必须匹配实际内容。
