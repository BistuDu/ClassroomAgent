---
name: slide-design
description: 普通幻灯片 Scene JSON、元素布局、配图、数据图表和页面内容修改规范。生成或修复 slide 页面时读取。
---

# 普通页面设计

输出 `content.type=slide` 的 Scene JSON，使用传入 page.id 作为 planPageId，type/title/brief 与方案一致，actions 初始为空。画布为 1280x720，至少保留 40px 边距；标题建议 40px 以上，正文建议 24px 以上，文字和图形必须在画布内。

根据教学关系构图：概念用形状和连线，过程用路径和箭头，对比用两侧结构或表格，定量关系用真实柱状/折线/散点图，图文页使用已保存 mediaId。避免每页只有标题和相同项目符号，保持统一主题但让页面承担不同教学任务。

元素 ID 必须稳定唯一。图片只能引用上下文中真实存在的 mediaId；sourceIds 只能引用实际资料。修改已有页面时优先用稳定 sceneId/elementId/actionId 的 `patch_stage`，保留未改元素 ID。

页面、动作和 TTS 分开生成。生成反馈是紧凑树和标识，完整内容需按 readback 用 `read_stage` 回读，不因摘要缺少源码而重复生成。
