# Classroom prompt migration

Sources: OpenMAIC-main/lib/prompts/templates/director/system.md, agent-system/system.md, lib/prompts/snippets/speech-guidelines.md, lib/orchestration/registry/store.ts, prompt-builder.ts, summarizers/peer-context.ts.

- director.md is copied verbatim; Python fills the original variables. next_agent USER/END maps to wait/end. No fixed speaker cap.
- Four *.original.md personas preserve the source text. Runtime *.md personas only adapt unsupported whiteboard instructions.
- Original actor template is retained as agent-system.original.md for provenance. Runtime composition preserves persona, user-turn response rules, discussion opening/joining, peer differentiation and original length targets.
- Python requires plain speech plus native function calls instead of the source JSON action/text array. Only teacher gets existing tools for the current page. No whiteboard, video or slide navigation capability is introduced.
- Speech effects require actual browser receipts rather than concurrent effects. Students speak only. Acknowledgments do not resume prerecorded playback; explicit user control remains required.
- Runtime adds the four-member roster, role isolation, real evidence and quiz-answer protections. Original priority teacher=10, curious=5, notetaker=5, thinker=6 is retained.
- Extra restrictions from the earlier Chinese rewrite (only necessary contributions, no extended questions, mandatory wait after options) are removed.
- manifest.json records original source hashes. Full prompt parity does not imply identical provider outputs or identical orchestration transport.
