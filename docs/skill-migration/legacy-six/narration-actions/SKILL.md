---
name: narration-actions
description: 页面讲解动作、聚光/激光、实验控件动作和 TTS 解耦规则。生成讲稿、重做动作或补音时读取。
---

# 讲解动作与语音

动作使用 `speech`、`spotlight`、`laser`、`widget_setState`、`widget_highlight`、`widget_annotation`、`widget_reveal`，另可安排 `discussion`。动作 ID 稳定；先设置实验状态或突出元素，再用 speech 解释当前画面。speech 每段自然口语 30~180 字，最多 600 字，不为每句话重复高亮。

## 讨论点

默认整课按价值安排一至两个，不是每页必有。`discussion` 必须为本页最后一个动作，单页至多一个：稳定 `id`、非空 `topic`、可选 `prompt`、`initiatorId`（`curious` 好奇宝宝、`notetaker` 笔记员、`thinker` 思考者）。不绑定预制音频、不填 speech 的 text、不泄露未提交测验答案。用户可参与或跳过，参加后由独立课堂运行生成真实讨论。

用户要求给旧课补充、调整或删除讨论点时，用 `read_stage` 读目标页动作，再用单页 `patch_stage` 局部补丁，保留其他动作 ID 和有效音频。不要重做整页讲稿/TTS；非法讨论顺序会整次拒绝，不截掉后续讲解。

幻灯片 spotlight/laser 引用真实 elementId；互动动作引用真实 variables、controls 和状态。测验只做导入和鼓励作答，不在题目页泄露答案。

`generate_actions` 只保存动作，不自动合成声音。用 `list_voices` 选择真实兼容 voiceId，`generate_tts` 负责整页或指定 actionIds 的配音；复用 ready，修复 failed/stale，未知付费结果不自动重发，force 仅用户明确要求重做。修改讲稿保留其他动作身份。
