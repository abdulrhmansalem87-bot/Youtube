# HANDOVER: WealthRadar YouTube automation

Last updated: 2026-11-26 13:15 Cairo. Keep this file current with every change. Any assistant should be able to continue from here.

## 1. Overview
- Owner: Abdulrhman Salem. Channel: WealthRadar (Arabic money and economy, audience Egypt + Gulf).
- Repo: abdulrhmansalem87-bot/Youtube (private). Work branch: `video-quality-upgrade`, open PR #91. DO NOT MERGE until the owner says so.
- Hard rules: everything free; no automatic PUBLIC upload (uploads are PRIVATE, owner publishes in YouTube Studio); no stock or listed-share recommendations (Egypt FRA rule); every number must be verified and show its source and date; no profit guarantees.
- Commits to the branch use `[skip ci]` because GitHub Actions minutes are nearly used up until Dec 1, 2026.

## 2. Strategy: "كشف حساب" (Money Audit) long-form format (approved by owner)
One money question per 9-11 minute episode. Owner conditions: numbers verified, a human angle, visible human review/trust, real income beyond ads.
Episode structure:
1. Hook (first 15 s): the key number.
2. What happened.
3. Why it happened.
4. Winners and losers: Egypt segment and Gulf segment.
5. Scenarios: scenario calculator (example: 100,000 EGP in bank certificates vs gold vs dollar, 5-year history).
6. Prediction-receipt segment: past predictions checked against what happened (`config/predictions_ledger.json`, `newsflow/predictions.py`, `newsflow/receipt_video.py`).
7. Takeaways.
Weekly cadence, plus a teaser Short for each long video.
First long episode: episode 3, the 100k comparison.
Description template has an affiliate-links placeholder section (to build; see section 8).
Monetization order: affiliate from day 1, sponsorships after ~10k subs, a digital guide later, ads as the last layer.

## 2b. Standing rules from the owner (permanent)
- Present ONE strongest final decision, never option menus. The owner decides only on money and his own brand/name.
- Every recommendation goes through: research, decision, self-evaluation, revision; only the final result is shown.
- Zero-cost constraint: replace every paid item with a free alternative. His own voice recording is the planned voice (free, clear rights, builds trust). No TTS in finished videos.
- Sources are NOT shown on screen. They go in the video description (Da7ee7 style). Source block template (Arabic): "المصادر: ... الحساب تقريبي على متوسط السنة وليس لشهر بعينه."
- Visual standard (palette A, approved 2026-11-26): navy gradient background (14,20,58)->(5,8,26), vivid gold accent (255,196,31), coral red for losses (255,92,92), mint green (46,222,150) for good, white text, card (24,32,82). Fonts: Noto Kufi Arabic; DejaVu Sans Bold for text containing . , % : (Kufi lacks those glyphs). Keep the bottom ~25% of Shorts free (YouTube UI).
- Channel rename to "كشف حساب": proposed, awaiting the owner's yes/no. The show name is one variable (SHOW_NAME) in the sample renderer; change it and the channel tag together.
- Sample Short (matrix #1, 38 s, silent, palette A) was rendered by a standalone script, not by the repo renderer; the script is not committed yet.

## 3. Launch plan: 9 distinct Shorts (experiment matrix) - PENDING OWNER APPROVAL
3 topic groups x 3 title formulas; hook and narration rotated (Latin square). 9 videos give a directional signal only; confirm the winner on a second batch before locking style for 3 months.
Title formulas: A number shock, B question to viewer, C contrarian claim.
Hooks: H1 key number first, H2 question, H3 myth then "wrong".
Narration: N1 data voice, N2 story (labeled fictional example person), N3 myth vs fact split.

| # | Topic | Title | Hook | Narr | Main metric |
|---|---|---|---|---|---|
| 1 | 100k EGP in 2021, real value now | A | H1 | N1 | baseline swipe-away and retention |
| 2 | Is a 27% certificate positive after inflation | B | H2 | N2 | retention to end |
| 3 | High interest is not profit (real vs nominal) | C | H3 | N3 | shares/comments |
| 4 | 1 g gold price 2021 vs now | A | H3 | N2 | numeric title + myth hook |
| 5 | Dollar or gold vs inflation, 5 years | B | H1 | N3 | comments |
| 6 | Dollar is not a safe haven in Egypt | C | H2 | N1 | subs per view |
| 7 | 15,000 SAR/AED salary, save 20% for 5 years in EGP | A | H2 | N3 | Gulf reach |
| 8 | Does sending money home lose value | B | H3 | N1 | Gulf vs Egypt retention |
| 9 | Expat saving advice is backwards | C | H1 | N2 | subs per 1,000 views |

Publish order interleaved: 1,4,7,2,5,8,3,6,9; one per day, same time slot.
Each Short ends with the fixed teaser line pointing to the long video (PR #91 wiring: `related_video_links.json`; the "Related video" button cannot be set by API, set manually in Studio after upload).

### Tracking sheet (fill at 48 h and 7 days from YouTube Studio)
short_id | topic_group | topic | title_formula | hook_style | narration | publish_datetime_cairo | duration_s | impressions | CTR | views | viewed_vs_swiped_pct | avg_pct_viewed | avg_view_duration_s | likes | comments | shares | subs_gained | subs_per_1k_views | views_EG | views_Gulf | long_video_clicks | notes
Second tab "summary": AVERAGEIF per formula, hook, narration, group. Rule: pick a winner per axis only if it leads in 2 of 3 videos in its bucket.

## 4. Pipeline architecture
Python package `newsflow/` (run `python -m newsflow`):
- `discovery.py` RSS collection (`config/sources.yml`); `editorial.py` finance-topic filter and source diversity.
- `source_evidence.py` fetches original publisher pages; `fact_check.py` independent verification (Groq + Tavily); unsupported stories are dropped alone.
- `scriptwriter.py` Arabic script (Groq). `history.py` story dedupe. `predictions.py` and `receipt_video.py` prediction receipts.
- `broll.py`, `thumbnail.py`, `rendering.py`, `pipeline.py` voice (Fish Audio), video render, Shorts, YouTube private upload.
- `wealthradar_shorts/` isolated Shorts experiment; `wealthradar/production.example.json` plan example.
- `scripts/` QA and preview renders; `tests/` unittest suite (228 tests at last report).
Method reference: `WEALTHRADAR_PRODUCTION_METHOD.md`, `WEALTHRADAR_SHORTS.md`.

LLM: Groq free tier. Default model `openai/gpt-oss-120b` (set in `newsflow/fact_check.py` as DEFAULT_GROQ_MODEL, pinned in both workflows via NEWSFLOW_GROQ_MODEL). Groq removed Llama 3.1 8B and 3.3 70B from the free tier on 2026-08-16; do not use them. Other free models named by the owner's brief: gpt-oss-20b, Qwen. Verified in code only, not against Groq's live list.

## 5. How to run
- Local: Python 3.11+, FFmpeg, `pip install -r requirements.txt`, copy `.env.example` to `.env`, `python -m newsflow --dry-run`, output in `output/`. Tests: `python -m unittest discover -s tests -v`.
- Actions: `newsflow.yml` runs 3x daily Cairo time (3 pm, 7 pm, 10 pm), editorial checks only (no render or upload). Full episode needs manual `workflow_dispatch` with `private_test=true` and `dry_run=false`. `wealthradar-shorts.yml` is manual only. `quality.yml` runs checks on push/PR.

## 6. Credentials (names only, never values)
GitHub repo secrets: GROQ_API_KEY, TAVILY_API_KEY, FISH_AUDIO_API_KEY, FISH_AUDIO_REFERENCE_ID, PEXELS_API_KEY, YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN.
Status at last update: Groq and Tavily keys are still to be supplied by the owner through a secure link. Rendering is blocked until then.
YouTube OAuth needs scopes youtube.upload and youtube.readonly; re-authorize if the refresh token is old.

## 7. Publishing schedule
Pipeline checks: 3 pm, 7 pm, 10 pm Cairo. Shorts batch: one per day, same slot (owner to choose time). Long video weekly. All uploads PRIVATE until the owner reviews and publishes.

## 8. Status: implemented vs not
Implemented (on branch): news pipeline, fact-check gate, scriptwriter, prediction receipts, teaser-Short wiring, quality upgrades (tests passing at last report).
New package `wealthradar_audit/` (own 20 tests pass: `python -m unittest discover -s tests`; run `python -m wealthradar_audit --out DIR`):
- `data.py` sourced snapshot (Egypt CPI, USD/EGP, gold, NBE certificate rates per year with URL, Gulf CPI from the World Bank, pegs). `calculator.py` 100k scenario (cash, dollar, gold, certificate) plus `gulf_view`. `charts.py`, `description.py` (affiliate placeholders), `episode.py` (9-11 min structure and fact brief), `receipts.py` (ledger segment).
- Certificate method (owner decision): each January roll the whole amount into the best NBE certificate rate available that month, sourced rates only: 2021 11, 2022 11, 2023 25, 2024 27, 2025 30 (percent). Compounded 2022-2025 multiple about 2.29 vs inflation 2.23, real about +2.7 percent. Must be stated on screen and in the script (`brief.on_screen_required`). On-air point: the 18 percent certificate ran only 21 Mar to 30 May 2022 and the 25 percent one only 4 to 31 Jan 2023, so a January-only rule misses windows. Not modelled: caps, new-money limits, tax, monthly payout (22.5 vs 25). 2024 tenor not confirmed; 2025 is the year-one rate of a 3-year stepped certificate.
- Official vs parallel USD/EGP differed in 2022 to early 2024: say so on air.
- The receipt segment is dropped when `config/predictions_ledger.json` has no settled, sourced prediction (currently empty).
Not built yet: pipeline wiring (`newsflow/pipeline.py` does not call `wealthradar_audit`), narration, render of episode 3, Shorts matrix config, tracking sheet file.
Untested: the repo's 228 tests and Actions on the new code, real upload path, anything needing Groq/Tavily/Fish keys.

## 9. Open items
- Owner approval of the 9-Short matrix and topic swaps.
- Groq and Tavily keys.
- Commit access: the coding agent has read-only GitHub API access; commits go through the browser editor.
- Possible licensing check for Egypt/Saudi finance content.
- Episode 3 render after keys.
