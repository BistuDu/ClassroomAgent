---
name: stage-dsl
description: "Python课程文档定位及actions/quiz/simulation受限参考，读取和编辑路径。"
metadata:
  title: "课堂文档结构"
---

# Python 课程文档合同
Stage.title/description由rename_stage改；approvedPlan.pages目录/标题/brief由edit_deck改；已有Scene.content/actions由patch_stage改。revision是并发保护，不提交整课JSON当补丁或沿用原data.canvas路径。
Scene包含id/planPageId/title/brief/type/content/actions/sourceIds，type仅slide/interactive/quiz。planPageId是批准槽位，sceneId不是显示页号P1。

## 按需读取
- 普通页：read_skill(skillId=slide-dsl)
- 动作：references/actions.md
- 测验：references/quiz.md
- 实验：references/simulation.md

read_stage在sceneId下使用页面相对路径（/content/html、/actions），detail=source返回真实内容，offset/nextOffset是Unicode码点。patch target子对象路径同理；无target的旧全局零基Pointer仅兼容。主题兼容独立patch /theme，不能混合页面。读完正文/参考到hasMore=false。
