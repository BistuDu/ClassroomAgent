---
name: quiz-design
description: 基础单选测验页面的题目、选项、答案解析和语音/检查约束。生成或核对 quiz 页面时读取。
---

# 测验页面

输出 `type=quiz` 的 Scene JSON。每题有唯一 id、2~8 个唯一选项 id、一个确定的 answer 选项 id 和有教学价值的 explanation；题目与课程目标一致，不依赖课程外知识。题干和选项不得泄露答案。

初始 actions 为空。测验也需要导入语音和当前程序/视觉报告；修改题目保留稳定 ID，逐题核对用 `read_stage(detail=source)`。讲解动作只做导入与鼓励作答，不说答案、正确选项或解析。
