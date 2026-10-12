---
name: interactive-simulation
description: 互动实验页面的自包含 HTML、变量、控件、预设、观察值和可信桥接接口规范。生成或修复 interactive 页面时读取。
---

# 互动实验页面

输出 `type=interactive` 的 Scene JSON。`content.html` 必须是完整自包含 HTML/CSS/JS，不使用 CDN、远程脚本、网络 fetch、导航或父页面访问。实验要表达真实模型，明确变量范围、初值、单位和方程，参数或拖动必须驱动图像与可读观察值。

`variables`、`initialState`、`controls` 精确对应；至少两个有教学差异的 presets；所有控件有稳定选择器，包含教学高亮目标和 reset。必须公开 `window.openmaicSimulation` 的 `getState`、`setState`、`observe`、`reset`、`pause`、`resume`。手动输入、拖动和老师 setState 共享同一状态更新函数。

动作生成时至少演示两组真实预设并比较 observe 结果。源码精确回读用 `read_stage(path=/content/html, detail=source)`，续读必须带 revision；修改使用稳定 target，不重排数组下标。
