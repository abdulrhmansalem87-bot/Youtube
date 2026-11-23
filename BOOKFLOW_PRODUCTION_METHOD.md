# BookFlow — Production Method (isolated from NewsFlow)

## Purpose
BookFlow is a separate, silent, book-page-inspired visual format for personal finance, investing, business and self-development. It does not replace or modify WealthRadar NewsFlow.

## Isolation rules
- BookFlow code, prompts, plans and tests stay in `bookflow/`, `scripts/bookflow_validate.py`, `tests/test_bookflow_contract.py`, and `.github/workflows/bookflow.yml`.
- Never import `newsflow`, `wealthradar_shorts`, TTS, or audio modules.
- Do not change existing workflows, production instructions, secrets, OAuth, channel settings, or upload behavior.
- This stage validates plans only. It does not render, upload, schedule, or publish videos.

## Creative direction
- Silent video: no narration, music, voiceover, or generated audio track.
- Open physical book on a warm wooden desk, soft natural light, calm premium editorial atmosphere. Keep camera angle, desk, book style and lighting consistent.
- Short English statements on screen, with a clear Arabic translation in parentheses below for review.
- First three seconds: curiosity-driven hook, preferably a question or a substantiated number.
- Visual movement: page turns, line highlights, close-ups, simple charts, coins/currency props, occasional Arabic/English page compositions. Meaningful visual beats change about every 2–3 seconds.
- End with a natural save/follow/subscribe prompt, varied to fit the subject. Avoid static repeated pages, black backgrounds and tiny text.

## Formats
### Short
- Vertical 9:16, 1080x1920.
- 6–8 scenes, normally about 8 seconds each (6–10 seconds allowed).
- English overlay plus Arabic translation in every scene.
- Hook in opening scene and CTA in final scene.

### Long
- 5-minute target, 16:9, 1920x1080.
- At least 20 scenes, each no longer than 15 seconds; total scene duration 290–310 seconds.
- Progression: hook, problem, core idea, practical example, caveat, application, recap and CTA. A long video must add useful explanation; do not stretch the Short.

## Accuracy and book rights
- Cite book title, author, edition/URL and page only when verified.
- Explain ideas in original wording. Do not reproduce full pages, chapters, tables or long copyrighted excerpts.
- Direct quotes must be no longer than 25 words and attributed; prefer paraphrase.
- Never invent quotes, page numbers, statistics, studies or attributions. Mark uncertain references for human review.
- Numeric hooks, charts and claims need a source reference that supports them. Do not imply author/publisher endorsement.

## Reliability gates
1. Validate JSON plans before expensive rendering.
2. Fail early with actionable errors; never silently invent missing facts.
3. Keep scenes independently reusable so failed scenes can be regenerated without rebuilding approved scenes.
4. Future renderers must keep a manifest with scene IDs, prompt/version, source reference, duration and asset checksum.
5. Never upload from BookFlow. Rendering and publishing require a separately approved workflow.
