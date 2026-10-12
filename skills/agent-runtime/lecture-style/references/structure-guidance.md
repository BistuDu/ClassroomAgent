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
      "type": "slide",
      "minRatio": 0.65
    },
    {
      "type": "quiz",
      "min": 1,
      "max": 3
    },
    {
      "type": "interactive",
      "max": 2
    }
  ]
}
```
