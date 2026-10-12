---
name: deep-research
description: "先取证再方案：问题、来源台账、时效和冲突，使用真实web_search/fetch_url和sourceId，不用于研究表演。"
metadata:
  title: "深度调研"
---

# Deep Research course design

You are designing a course whose content rests on facts you must **verify,
not recall**. Research first, outline second, generate third. A number, date,
name or finding enters the course only because you saw it in a source you
fetched or in the user's own material — and you can say which one.

## Structure

- Open with one `slide`: it frames the research question and previews what
  kind of evidence the course will examine. Not a definitions or
  history-of-the-field page.
- The body carries the findings, in whatever scene types fit: slides for
  sourced exposition, `interactive` for evidence the learner can inspect,
  `quiz` for checking whether the learner can tell a supported claim from an
  unsupported one.
- Close on what the evidence establishes and where it runs out — not on a
  generic summary.

## Step 1 — 从真实已有资料开始
list_stages/read_stage查看目标课sources；已有sourceId按fetch_url(sourceId,sourceVersion,offset,limit)分页。用户明确提供的链接可以fetch_url(url)。不假装存在上传材料或提取工具。

## Step 2 — Split the topic into facets

Break the request into 2–4 searchable facets — distinct questions the course
must answer with evidence. Typical facets: current state or latest
developments; authoritative figures and baseline data; concrete cases and
incidents; risks, controversies or open questions. Write the facet list down
before searching. Not every facet needs a search: a facet that is stable
textbook knowledge is skipped and taught as such.

## Step 3 — Search with a budget

- At most **8 `web_search` calls for the whole session**, planned across the
  facets. One precise query beats several vague ones; write queries in the
  language of the course.
- The session shares one run with planning and
  every page's generation, and every extra call is latency the user watches.
  Research is one slice of the run, not the main act. If the run gets long,
  cut facets — never generation.
- Read each result before searching again: the next query should be shaped by
  what the last one returned, not a rewording of it.

## Step 4 — Pick sources, fetch them

- From the search results, pick at most **6 URLs in total** across all facets.
  Prefer primary and authoritative origins — official bodies, named
  institutions, the report or dataset itself — and for time-sensitive claims
  prefer the most recent. Skip mirrors and aggregators repackaging the same
  story: fetch one origin, not three copies of it.
- `fetch_url` accepts only URLs that appeared in the user's messages or in
  this session's `web_search` results. Never assemble or recall a URL from
  memory — if the source you want did not surface, refine the search instead
  of guessing an address. A URL that never surfaced does not exist for this
  course.
- `fetch_url` ingests the page as a session material and returns a
  `sourceId` plus a first-page preview. That `sourceId` is what the ledger
  cites.

## Step 5 — Read deep, keep the ledger

- Page through each fetched material with `fetch_url(sourceId,sourceVersion,offset,limit)` — at least far
  enough to verify every claim you plan to take from it. Use version-bound pagination and recorded excerpts
  to locate a specific figure or name inside it rather than re-reading blind.
- Maintain a running ledger: **claim → source** (`sourceId` or URL, plus the
  source's name and publication date when visible). Only ledgered claims may
  enter the course as researched facts. Record the date: a stale figure
  presented as current is a factual error, not a styling choice.

## Step 6 — Cross-check conflicts

- Prefer primary over secondary sources, recent over outdated for
  time-sensitive claims, and domain authorities over general media. Two
  independent origins outweigh one story republished ten times.
- If a conflict survives — genuinely contested figures, diverging official
  accounts — teach the range or the disagreement with both attributions. Do
  not silently pick a side, and never average conflicting numbers into an
  invented middle.
- A load-bearing claim with a single source is single-sourced: soften the
  wording, attribute it explicitly, or drop it.

## Step 7 — Know when research is done

Research is complete when both hold:

- every facet the outline will lean on has at least one ledgered source, or is
  marked as stable knowledge needing none;
- every number, date and name the course will state is in the ledger.

Then stop. Polishing searches after coverage is reached steal budget from
generation.

## Step 8 — Ground the outline

There is no outline generator: plan the outline in the conversation, then
ask_user批准后 `create_stage` and one `generate_scene` per page with an explicit brief. The
page generator sees the actual plan/page, sources, media and brief, not unpassed conversation memory. Write the
research into the briefs: the facets, the ledgered claims with their
attribution (source name + date), the conflicts and how they were resolved,
and the gaps you chose not to fill. Anything you want to shape the course must
live in this text. Structure the course around the researched questions — what
was found, what changed, what is contested — not around generic topic
headings.

## Step 9 — Ground every page

- When generating a scene, pass that page's sourced facts in
  `generate_scene.brief` with real `sourceIds` — quoted concretely (figures, names,
  findings) with their attribution. The page generator only receives what you
  hand it; which fact belongs on which page is your choice.
- Inside page content, cite naturally — the institution, the report, the year.
  Do not dump raw URLs at the learner.
- Quiz distractors and interactive scenarios draw on ledgered facts too: a
  quiz that tests a number nobody verified teaches noise.

## Scene naming

Titles name the finding or the question, not the folder.

- Good: 「五年里成本降了多少？」「数据从哪里来」「两种口径差在哪」
- Bad: 「行业概述」「研究背景」「本课总结」

## Hard rules

- Never invent sources, citations, URLs or publication dates. A claim with no
  ledger entry is taught as stable knowledge with honest wording, or not
  taught at all.
- If `web_search` is not registered in this deployment, or searches keep
  failing: say so in chat, build from the user's materials and stable
  knowledge, and mark clearly what could not be verified. Never present memory
  as research.
- Time-sensitive claims without a source do not enter the course. Timeless
  knowledge needs no source — do not spend budget verifying what a textbook
  already settles.
- When user material and web findings conflict: on facts about the user's own
  subject (their data, their product, their case) the user's material wins. On
  external context, the better-verified recent source wins — and you surface
  the discrepancy to the user in chat instead of overriding silently.

## If the requirement is not research-driven

If the topic is timeless textbook knowledge with no external fact to verify —
a maths derivation, a classic text, an established skill — say so in one
sentence in your chat message and plan an ordinary course instead. Do not run
research theatre on a topic that needs no research.

Python首次fetch_url(url)不带offset/sourceVersion，续读只用sourceId/sourceVersion；搜索摘要不是全文证据，访问失败如实记录。8搜索/6来源为方法预算，仍服从真实运行预算。资料页的sourceId/归属与版本由实际工具结果决定，不伪造。页面、动作、TTS各自生成；教学语气通过generate_actions.guidance传递。
