# BookFlow — Premium Silent Book-Page Video Method

## Purpose and separation
BookFlow is a separate format for personal finance, investing, business and entrepreneurship ideas. It does not replace or modify WealthRadar NewsFlow.
- Code, plans and tests are isolated in `bookflow/`, `scripts/bookflow_*.py`, `tests/test_bookflow_contract.py`, and `.github/workflows/bookflow.yml`.
- Never import NewsFlow, WealthRadar Shorts, TTS or audio modules.
- This workflow validates and renders silent MP4 review artifacts only. It has no YouTube or TikTok upload, scheduling, or publishing capability.
- It uses read-only repository permissions and does not require production secrets, OAuth tokens, or channel credentials.

## Visual identity
A premium editorial scene: open book on a warm dark wooden desk, ivory pages, deep charcoal text, antique-gold highlights and muted emerald accents. Keep the book, desk, camera language and lighting consistent so the series is recognizable.
- No black slide backgrounds, tiny type, crowded layouts or repetitive still cards.
- English statement is the primary line; a readable Arabic translation sits beneath it.
- Use generous negative space, strong contrast, mobile-safe typography and a restrained color palette.
- The page is a visual metaphor, not a license to reproduce a copyrighted page.

## Motion and retention
Every scene is divided into visual beats no longer than 3 seconds:
1. A cinematic camera push-in and opening page highlight.
2. A shifted highlight/page focus with a relevant visual motif (coins, a simple financial chart or a page-turn cue).
3. A second page focus and motif change before the next scene.
Scene content and visual motif should change with the idea. Avoid random motion that distracts from understanding.
- Opening hook lands in the first three seconds and creates a clear curiosity gap.
- Build a progression: question/problem, explanation, example, useful action, caveat, recap, CTA.
- Every scene contains English text, Arabic translation and a source note.
- The final scene has one natural action: save, follow or subscribe.

## Format contracts
### Short
- 9:16, 1080x1920.
- 6–8 scenes, each 6–10 seconds; total 48–80 seconds.
- First scene role is `hook`; final scene role is `cta`.

### Long
- 16:9, 1920x1080.
- Minimum duration is 300 seconds (5 full minutes); maximum 480 seconds.
- At least 20 scenes; no scene longer than 15 seconds.
- A long episode adds examples, context, objections and practical application. Never stretch a Short by repeating lines.

## Content, RPM and credibility
Prioritize high-intent subjects advertisers commonly value—personal finance, saving, investing basics, business models, entrepreneurship, career income and financial decisions—without promising any RPM or view count. Revenue depends on audience geography, advertiser demand, watch time, channel eligibility and many other factors.
- Use a strong, honest hook; no fake statistics, exaggerated earnings claims or guaranteed returns.
- Prefer original explanation and practical examples over generic motivation.
- Verify book title, author, edition and any specific idea attribution before publication. Mark uncertain details as unverified.
- Never invent quotations, page numbers, studies or statistics. Any direct quote must be short (maximum 25 words) and attributed.
- Do not reproduce full book pages, chapters, tables or long copyrighted passages. Summarize in original wording.

## Rendering and recovery
- Run JSON validation before rendering.
- `scripts/bookflow_render.py` generates animated beats per scene, slow camera motion and a silent MP4.
- Each beat is cached with a fingerprint and FFprobe validation. On retry, valid completed beats are reused; only missing, changed or corrupt beats are rebuilt.
- Final MP4 is checked for resolution, duration and absence of an audio stream.
- Keep the render manifest with scene IDs, fingerprints, beat status and output QA.
- The workflow uploads MP4s and manifests only as a temporary GitHub Actions artifact for review. This is not publication or approval to publish.
