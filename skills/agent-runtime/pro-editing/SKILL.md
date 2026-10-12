---
name: pro-editing
description: "读后最小编辑，区分课程元数据、目录和单页内容，保留稳定ID与成果。"
metadata:
  title: "专业编辑"
---

# 最小编辑
适用于已有页面改字、动作调整和目录变动；不默认重新生成整课。list_stages 按课程名查归属，list_scenes 获取稳定 sceneId 与 revision；read_stage(detail=tree) 定位，grep_stage 查文字或源码，read_stage(sceneId,detail=source,path) 读取准确字段，nextOffset 续读带 revision。

## 三层原子操作
- rename_stage(stageId,expectedRevision,title,description)：课程名/描述，省略描述保留，空串清空。
- edit_deck：operation=rename(pageId,title)、set_brief(pageId,brief)、insert(page,index零基)、delete(pageId)、reorder(完整order)、set_sources(pageId,sourceIds真实本课已读来源)。
- patch_stage：单个已有页面 content/actions；target.sceneId 定位，elementId/actionId 定位子对象；path 相对此目标。主题单独 patch，不能混入页面操作。标题/brief/来源不在本工具修改。

示例标识和 revision 必须替换为实际读取结果：
```json
{"stageId":"stage_actual","expectedRevision":11,"operations":[{"op":"replace_text","target":{"sceneId":"scene_actual","elementId":"claim"},"path":"/text","old":"发生反射","new":"发生折射"}]}
```
```json
{"stageId":"stage_actual","expectedRevision":12,"operations":[{"op":"replace","target":{"sceneId":"scene_actual","actionId":"action_actual"},"path":"/text","value":"光从一种介质进入另一种介质，方向可能改变。"}]}
```
先读再写，old 与现值对应，不猜下标。保留未改元素、题目、选项和动作 ID。改稿给受影响 speech generate_tts；改画面重截图和视觉判断，补音只影响 program 覆盖。实验源码还须同步变量/控件与动作目标。重写讲解用 generate_actions(guidance)，只有结构彻底改变才 generate_scene 并补后续步骤。修复预算不能靠删除重插绕过，反馈如实列问题与已保存成果。


## 叶字段优先的编辑矩阵
|意图|最小改动|
|---|---|
|改文字|target.elementId，/text 的 replace_text 或 replace|
|移动/缩放|同元素 /x、/y、/width、/height；旋转 /rotation|
|换色/字体|真实 renderer 字段 /color、/background、/stroke、/fontSize|
|换图|/mediaId 替换为本课真实已保存媒体|
|改表格|/rows/行/列，纯文本，不给表格塞LaTeX|
|重排/新增元素|scene目标 /content/elements 完整合法数组，保留现有ID、新元素提供唯一稳定ID|
|修测验|scene目标 /content/questions/...，保留题目/选项ID，answer指实际选项|
|修实验|scene目标 /content/html，同步variables/initialState/controls/presets和动作目标|
|插入/重排动作|scene目标 /actions 合法数组，已有动作保留ID|

一项意图对应可命名操作；优先叶字段，避免整个对象覆盖邻居样式。失败补丁不写入成果，重读真实错误再修；内容仍经过Python结构与范围校验。目录insert只是方案槽位，需generate_scene填页，不是假定已存在完整页面。source读取可能分页，不能把单段当整页。
