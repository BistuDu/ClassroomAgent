---
name: understanding-by-design
description: "理解本位单课设计：持久理解、基本问题、GRASPS证据和WHERETO经历，不提供系列创建。"
metadata:
  title: "理解本位设计（UbD）"
---

# 理解本位设计（UbD）

用 UbD 逆向设计组织一节课：先明确学生最终要理解什么、如何证明真正理解，再设计学习经历。

`stage-design` 仍然约束新课堂的持久化顺序；本 Skill 约束教学设计与每页 brief 的内容。已有页面的课堂按 `pro-editing` 做局部编辑，不要重建课堂。

## 设计范围
本次实现单课；系列创建与文件夹尚不支持。用户要求系列时先确认单课边界，不声称批量建立。

## 阶段一：确定预期结果

1. 用 1–3 句声明**持久理解（Enduring Understanding）**：学生离开课堂后仍能保留并迁移的思想，而不是事实清单。
2. 写出 1–2 个**基本问题（Essential Question）**：开放、可持续讨论、没有唯一答案，并能在课程中反复回到。
3. 用基本问题打开课程第一页，把抽象概念变成一个需要探究的真实问题。

## 阶段二：先确定评估证据

在写页面计划前定义学生如何证明理解：

- **表现性任务（GRASPS）**：写清 Goal、Role、Audience、Situation、Product 和 Standards，在 OpenMAIC 中优先落到 任务说明 slide 或数值实验 interactive 页。
- **概念诊断与辨析**：用 `quiz` 暴露典型错误概念，要求学生给出理由，不只是选项。
- **迁移与应用**：用 `interactive` 或新情境任务观察学生能否把理解用到变化后的问题中。

表现性任务是学习路径的终点，前面的页面都要为它提供概念、证据或练习，不要在课程末尾突然加一个没有铺垫的任务。

## 阶段三：用 WHERETO 设计学习经历

用 WHERETO 检查每个活动，并把它们写进页面 brief：

- **W — Where & Why**：学生知道学习要去哪里、为什么值得学。
- **H — Hook**：用真实、有冲突的情境或问题引出基本问题。
- **E — Equip**：用 `slide` 提供建立概念所需的证据与逻辑链。
- **E — Experience**：用 `interactive` 让学生操作、模拟或亲手做出概念。
- **R — Rethink & Revise**：换一个情境让学生重新应用并修正理解。
- **T — Tailor**：为不同起点的学生提供支架与挑战。
- **O — Organize**：页面顺序让理解逐步生成，最后回到基本问题。

## OpenMAIC 页面节奏

可以从下列节奏起步，但根据表现性证据调整，不要机械套模板：

1. `slide`：基本问题与真实情境；
2. `slide`：用证据或逻辑链建立概念；
3. `interactive`：让学生亲手做出核心概念；
4. `quiz` 或 `interactive`：在新情境中辨析、迁移或修正；
5. 任务说明 slide 或数值实验 interactive：完成 GRASPS 表现性任务；
6. `quiz` 与收束 `slide`：检查概念并回到基本问题。

页面标题用探究式问题或真实情境，不要写成教科书目录。语言跟随用户和课程语言。

## 质量关口

- 明确写出大概念、基本问题、GRASPS 表现性任务与 WHERETO 覆盖。
- 每一页都能回答“它在服务哪个理解或基本问题”；答不出的页面删除或改写。
- 抽象概念必须有 `interactive` 或 任务说明 slide 或数值实验 interactive 让学生实际操作、判断或创造，不能只听讲解。
- 单课先确认目标与证据，不跳过方案批准。

## 边界

不用于品牌风格复制、名师讲课风格模仿、纯排版克隆或 PPT 直接导入；这些请求分别使用对应的 style、teacher-style 或 `pptx-import` 流程。


## Python执行边界
框架通过plan.objectives/pages[].brief、generate_scene.brief、generate_actions.guidance传递。页面→动作→generate_tts分别保存。基础quiz仅单选，options为id/text对象；开放答案与理由通过课堂对话收集。数值模拟不能持久记录/诊断任意自由文本，未收到真实作品不能预填掌握证据。同学发言不计为学习者证据；不提供新评分器、角色配置、系列或PBL引擎。依赖缺失的导入/克隆能力不能调用，若用户需要先说明并询问适配范围。
