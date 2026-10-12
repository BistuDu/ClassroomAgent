输出 type=quiz 的 Scene JSON。content 包含基础单选 questions，每题唯一 id、题干、2~8个唯一 id 的 options、一个 answer 选项 ID 与有教学价值的 explanation。概念、难度与课程目标一致，答案可确定且无歧义；不依赖课程外知识。初始 actions 为空。题干和选项不得泄露正确答案。sourceIds 仅引用实际资料。

页面、讲解动作与配音分别生成，测验也需要导入语音和当前程序/视觉报告。题目/选项稳定 ID 保留，修改答案时检查引用，不修改评分记录伪造通过。紧凑生成反馈不是完整题目：需要逐题核对时按 sceneId 和 /content 用 read_stage(detail=source) 回读。
