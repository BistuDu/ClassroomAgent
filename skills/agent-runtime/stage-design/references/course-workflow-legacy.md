# 课程设计与制作
适用于创建单课、完善已有课及自然语言定位多课。已有课先 list_stages/list_scenes/read_stage，不因编辑建立副本。新课明确 audience、objectives 与带 id/title/type/brief 的 pages，ask_user(kind=plan_approval,question,plan) 等待真实批准，再 create_stage(approvalId)；打印方案不是制作完成。角色固定老师与三位同学，无 roster 配置。

## 逐页工作流
1. list_scenes 读取批准槽位 pageId、sceneId、revision 和真实 issues。generate_scene(stageId,pageId,expectedRevision,brief,sourceIds,mediaIds) 每次只保存一个页面。brief 自包含目标、任务、方法、证据与衔接。
2. generate_actions(stageId,sceneId,expectedRevision,guidance) 独立生成讲稿与教学动作。guidance 传递当前方法及讨论安排；页面生成不等于动作完成。
3. list_voices 查看当前兼容 voiceId；必要时 set_teacher_voice；generate_tts 给已保存 speech 独立配音，保留成功段，未知付费结果不自动重发。
4. check_scene(mode=program) 真实运行；render_scene_preview 获取截图，观察后 check_scene(mode=visual,snapshotId,passed,findings) 保存判断。按 references/inspection.md 处理失败与过期。
5. list_scenes 核对无缺页、动作/音频缺失及过期/失败检查，ready 来自真实覆盖，不来自结束语。

## 方法与边界
每页承担明确学习作用：问题→证据/机制→应用→检查/迁移。标题用有意义的问题或行动。资料用真实 sourceId，图片用已保存 mediaId，不伪造读取、配音和检查。只支持 slide/interactive/quiz，interactive 为数值参数模拟。开放文本诊断在课堂对话中做，不宣称静态页实时评分。
重大范围变化先问用户；写入取最新 revision，expectedRevision 是并发保护，不选择历史版本。重做页面会清空动作，必须补讲稿、音频和检查。只改讲稿保留页面。
显式 Skill 优先于自动匹配，用户要求优先于方法默认；方法实质冲突用 ask_user 澄清。意图写入合法 plan/pages[].brief、generate_scene.brief、generate_actions.guidance，不只说 Skill 名。参考按需 read_skill(skillId,path)，分页读至 hasMore=false。
旧历史不改写，旧入口已适配独立页面、动作、配音。
