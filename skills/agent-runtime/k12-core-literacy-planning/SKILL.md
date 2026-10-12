---
name: k12-core-literacy-planning
description: "中小学核心素养单课设计：情境、任务、证据与迁移，按需读取学科和学段参考。"
metadata:
  title: "核心素养教学设计"
---

# K-12 core-literacy classroom design

Design or reshape **one persisted OpenMAIC stage** around the Chinese curriculum
standards' core-literacy model. The deliverable is the classroom itself: pages,
roles, learner activity, assessment evidence and narration written into the
stage. Do not substitute a Word lesson plan, a `lesson.json`, or instructions
for running local render scripts.

The invariant is:

**authentic context → performance task → learning activity → observable evidence → transfer**

`stage-design` still governs the persistence sequence for a new stage. This
skill governs the pedagogy and the information carried in every page brief. If
the stage already has pages, edit it surgically under the `pro-editing` rules;
do not create a duplicate stage.

## Ground the lesson before planning

Before proposing pages, determine the subject and school stage. Then use the
受限 `read_skill(skillId="k12-core-literacy-planning",path=...)` 工具 to load both:

1. [`references/core-literacy.md`](references/core-literacy.md), always;
2. exactly one matching subject guide:
   - Chinese / languages: [`references/subjects/languages.md`](references/subjects/languages.md)
   - mathematics: [`references/subjects/mathematics.md`](references/subjects/mathematics.md)
   - science / physics / chemistry / biology: [`references/subjects/science.md`](references/subjects/science.md)
   - history / geography / morality and law / politics: [`references/subjects/humanities.md`](references/subjects/humanities.md)
   - IT / arts / PE and health / labor: the matching section in `core-literacy.md`

Loading the relevant reference is mandatory. Do not rely on a remembered
dimension name when the reference distinguishes compulsory and senior-high
wording.

If grade or topic is genuinely unknown, ask at most two load-bearing questions
in one `ask_user` call. Default the rest to 45 minutes, general curriculum
quality expectations and UDL support. Never ask again for information already
present in the request or attached material.

If the teacher names a textbook edition, standard clause or supplied material,
align to it. Otherwise use general curriculum wording and say the lesson is not
aligned to a specific textbook edition. Never invent a standard number, quote
or material fact.

## Settle the learning contract

Choose only **one or two** primary literacy dimensions for one lesson. State
the contract in this form before the page list:

> Students will **do X** in order to make **literacy dimension Y** observable
> through **evidence Z**.

Weak targets such as “understand”, “master” and “cultivate thinking” are not a
contract. Use visible verbs: annotate, model, compare, justify, test, revise,
design, decide, create or present.

The authentic context must carry all the way through the lesson:

- it creates the opening problem;
- learners use it in the central task;
- assessment returns to it with a new case or changed condition.

A story discarded after page 1 is decoration, not context. A normal exercise
with a person's name pasted on it is not an authentic problem.

## Plan pages around learner work

Default to 6–10 pages for a 45-minute lesson, but do not treat that range as a
hard page cap. Each proposed page includes `title`, `type`, `brief`, the learner
action, the evidence collected and its link to adjacent pages.

A useful default arc is:

1. `slide`: the authentic situation, the unresolved question and the final task;
2. `interactive` or evidence page: observe, manipulate, read, map or collect evidence;
3. `interactive` or `slide`: compare, classify, model, closely read or reason;
4. `quiz`: diagnose the most likely misconception and require a reason;
5. `interactive`, 任务说明 slide or task page: produce the main explanation, model,
   decision, text, design or performance;
6. `slide`: success criteria, scaffold, worked fragment or peer-review method;
7. `quiz` or task page: transfer into a new version of the same context;
8. optional closing `slide`: consolidate the method learners established and
   name what remains open.

Choose the page type by the learning action:

- `slide` frames a problem, carries source material or evidence, or consolidates
  a method. It must not become a run of teacher exposition.
- `interactive` is for changing numeric parameters and inspecting a mechanism,
  observing the resulting simulation. One interactive page
  carries one mechanism and says what changes, what is observed and what the
  observation establishes.
- `quiz` diagnoses a misconception, compares explanations or checks transfer through single choice; reasons are collected in classroom dialogue.
  Distractors come from real misconceptions and feedback teaches, not merely
  marks wrong.
- 任务说明 slide is for a genuinely multi-step inquiry, artifact or public performance.
  Do not wrap one simple exercise in PBL machinery.

Titles name what learners discover or make: 「拖动倾角，看射程怎么变」,
「两份史料为什么说得不一样」, 「给校园开放日改写导览词」. Do not use
「概念介绍」「知识讲解」「案例分析」「课堂总结」.

## 新课执行
真实ask_user(plan_approval)批准后create_stage；固定老师与三位同学，无set_roster/folderId。每页generate_scene传批准pageId、最新expectedRevision、自包含brief、真实sourceIds/mediaIds；generate_actions(guidance)独立生成讲解/讨论；再generate_tts。list_scenes/read_stage及真实程序/视觉报告验收。
每页brief包含素养维度、学习者动作、证据、误解/支架、评价、年级语言及衔接。开放表现通过任务说明与课堂对话收集，基础quiz单选不能自动分析自由作品。

## Existing-stage adaptation

When the current stage already has pages:

1. `list_scenes`, then `read_stage` the relevant pages before writing.
2. Audit subject/stage wording, context continuity, learner product, evidence,
   misconception handling, assessment alignment and narration.
3. Repair only the pages that break the contract. Prioritize decorative
   contexts, conclusions revealed before inquiry, no observable learner
   product, activity/assessment mismatch, wrong school-stage difficulty,
   literacy labels with no evidence, and exit tickets that collapse into recall.
4. Use `patch_stage` for narrow edits and `edit_deck` for page-list changes.
   Regenerate a whole page only when the user explicitly wants a rewrite.
5. Re-run `generate_tts` after speech changes, then read back touched pages and
   `list_scenes` for the final structure.

## Universal non-negotiables

- Learners do the cognitive work. The teacher supplies phenomena, sources,
  questions, models and scaffolds without announcing the conclusion first.
- The main task itself yields assessment evidence. The exit task uses a new
  case with the same reasoning or production structure.
- Primary school favors concrete manipulation, experience and short language;
  junior high favors concepts, evidence and explicit reasoning; senior high
  favors systems, models, multiple sources and justified value decisions.
- Include at least one visual or structural scaffold, one language-expression
  scaffold and one extension for learners ready for greater challenge.
- Create original cases, questions and activities. Textbooks and uploaded
  sources determine scope and facts, not learner-facing copy to reproduce.

## Completion check

Do not call the classroom done until all are true:

- the subject and school stage use the correct curriculum dimension wording;
- one or two dimensions appear as learner actions and observable evidence;
- the authentic context survives from opening through task to transfer;
- every approved page exists, has content and sits in the right order;
- learners acquire, process or compare evidence at least once;
- learners produce at least one explanation, model, text, design, decision,
  performance or other inspectable artifact;
- the central misconception is handled by an activity or quiz;
- assessment is isomorphic to the learning task and includes transfer;
- narration matches page content and every required speech line has audio;
- no curriculum quote, textbook edition, source fact or external lookup result
  was fabricated.

Close in one or two sentences: name the primary literacy dimensions and the
performance task that now makes them visible. Do not replay the whole page list.
