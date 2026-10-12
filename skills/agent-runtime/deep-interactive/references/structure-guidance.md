# 结构指导（方法参考）
用于当前请求教学规划审阅，不作为隐藏绑定或严格比例校验。原不支持页型/引擎不作为生成命令；现有类型为slide/interactive/quiz与数值模拟。
```json
{
  "allowedTypes": [
    "slide",
    "quiz",
    "interactive"
  ],
  "firstSceneType": "slide",
  "typeMix": [
    {
      "type": "interactive",
      "minRatio": 0.6
    }
  ],
  "allowedWidgetTypes": [
    "simulation",
    "diagram",
    "code",
    "game",
    "visualization3d"
  ],
  "requiredWidgetOutlineFields": [
    "concept"
  ],
  "noConsecutiveSameWidgetType": true
}
```
