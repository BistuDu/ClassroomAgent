# 普通页动作
仅speech、真实elementId的spotlight/laser和可选末尾discussion。优先聚焦关键文本、图表、图片、公式，不指装饰。先spotlight/laser后speech，讲解与当前元素匹配；一次焦点覆盖一段因果解释，不每句话换高亮。建议5–10个动作，按内容调整。没有video元素或播放工具，不输出play_video。
示例：{"actions":[{"id":"focus_claim","type":"spotlight","elementId":"claim"},{"id":"speech_claim","type":"speech","text":"观察这条光路，光在进入另一种介质后传播方向发生了变化。"}]}。claim必须真实存在。
