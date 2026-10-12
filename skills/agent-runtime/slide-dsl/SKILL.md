---
name: slide-dsl
description: "Python七种元素字段、纯文本、图表、公式、mediaId和稳定目标编辑参考。"
metadata:
  title: "页面数据结构"
---

# Python Slide DSL
普通页是Scene.content元素画布，不是HTML。1280×720，elements至少一项。唯一稳定id，type=text/image/shape/line/table/chart/formula，必须x/y/width/height。通用color/background/stroke/strokeWidth/fontSize/fontWeight/align/radius/rotation/opacity。禁止原left/top/content.canvas、富文本、src/latex字段。

|类型|实际字段|
|---|---|
|text|text纯文本，fontSize/fontWeight/align|
|image|真实mediaId，alt，不传URL|
|shape|shape=rect/ellipse/arrow，background/stroke|
|line|容器对角线，rotation方向，stroke/strokeWidth|
|table|rows等长字符串二维数组|
|chart|chartType=bar/line/scatter，points的x/y/label/series，xLabel/yLabel|
|formula|text为KaTeX，fontSize|

```json
{"type":"slide","width":1280,"height":720,"elements":[{"id":"claim","type":"text","x":48,"y":40,"width":1160,"height":76,"text":"折射改变光的传播方向","fontSize":44,"fontWeight":700},{"id":"data","type":"chart","x":730,"y":170,"width":460,"height":400,"chartType":"line","points":[{"x":0,"y":0},{"x":30,"y":19.47}],"xLabel":"入射角（°）","yLabel":"折射角（°）"}]}
```
示例数据为空气到折射率1.5介质近似；真实数据需模型/资料依据。读取read_stage(sceneId,detail=source,path=/content)，续读带revision。编辑target={sceneId,elementId} path=/text或/fontSize；spotlight/laser引用真实elementId。标题走edit_deck，正文走patch_stage。
