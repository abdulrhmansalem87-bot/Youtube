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
GitHub repo secrets: GROQ_API_KEY, TAVILY_API_KEY, FISH_AUDIO_API_KEY, FISH_AUDIO_REFERENCE_ID, PEXELS_API_KEY, PIXABAY_API_KEY, YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN.
Status at last update: Groq and Tavily keys are still to be supplied by the owner through a secure link. Rendering is blocked until then.
YouTube OAuth needs scopes youtube.upload and youtube.readonly; re-authorize if the refresh token is old.

## 7. Publishing schedule
Pipeline checks: 3 pm, 7 pm, 10 pm Cairo. Shorts batch: one per day, same slot (owner to choose time).
Long video (owner decision 2026-11-26): 2 per week as the base, scaling up (up to one a day) only when the material, length and information justify it. Quality before volume; the owner's recording time is the limit.
Fast lane (section 11): a Short within hours for a breaking Egyptian event with a money angle, outside the fixed schedule.
All uploads PRIVATE until the owner reviews and publishes.
Episode roadmap: ep 1-2 as planned in section 2; ep 3 the 100k EGP comparison (data ready, render waits on narration); then 2 per week, one of them a "كشف حساب" audit and one a follow-up or receipts/predictions episode when the ledger has settled, sourced predictions.

## 8. Status: implemented vs not
Implemented (on branch): news pipeline, fact-check gate, scriptwriter, prediction receipts, teaser-Short wiring, quality upgrades (tests passing at last report).
New package `wealthradar_audit/` (own 20 tests pass: `python -m unittest discover -s tests`; run `python -m wealthradar_audit --out DIR`):
- `data.py` sourced snapshot (Egypt CPI, USD/EGP, gold, NBE certificate rates per year with URL, Gulf CPI from the World Bank, pegs). `calculator.py` 100k scenario (cash, dollar, gold, certificate) plus `gulf_view`. `charts.py`, `description.py` (affiliate placeholders), `episode.py` (9-11 min structure and fact brief), `receipts.py` (ledger segment).
- Certificate method (owner decision): each January roll the whole amount into the best NBE certificate rate available that month, sourced rates only: 2021 11, 2022 11, 2023 25, 2024 27, 2025 30 (percent). Compounded 2022-2025 multiple about 2.29 vs inflation 2.23, real about +2.7 percent. Must be stated on screen and in the script (`brief.on_screen_required`). On-air point: the 18 percent certificate ran only 21 Mar to 30 May 2022 and the 25 percent one only 4 to 31 Jan 2023, so a January-only rule misses windows. Not modelled: caps, new-money limits, tax, monthly payout (22.5 vs 25). 2024 tenor not confirmed; 2025 is the year-one rate of a 3-year stepped certificate.
- Official vs parallel USD/EGP differed in 2022 to early 2024: say so on air.
- The receipt segment is dropped when `config/predictions_ledger.json` has no settled, sourced prediction (currently empty).
Fast lane: `wealthradar_audit/fastlane.py` (money-angle detection, sensitive-event gate, two-source gate, title and hashtag builder, Short brief) with 5 tests. The live watch is not wired yet.
Not built yet: pipeline wiring (`newsflow/pipeline.py` does not call `wealthradar_audit`), narration, render of episode 3, Shorts matrix config, tracking sheet file.
Untested: the repo's 228 tests and Actions on the new code, real upload path, anything needing Groq/Tavily/Fish keys.

## 9. Open items
- Owner approval of the 9-Short matrix and topic swaps; channel name answer.
- Narration: the owner's own recording (see section 12 for the voice-cloning research).
- Pexels key not verified (repo secret exists, value not readable; GitHub secrets are write-only). Pexels' API page said on 2026-11-26 "New API key issuance is currently paused and cannot be requested" (www.pexels.com/developer/api/), so a lost or rejected key may not be replaceable: the Pixabay adapter (now written, see section 10) is the insurance. Fish Audio secrets exist but the plan is not to use TTS.
- Pixabay: free account (site pixabay.com, signup email abdulrhmansalem87@gmail.com, key name newsflow-pipeline, created 2026-11-26). Key is in the repo secret PIXABAY_API_KEY and in the vault. Live API search verified 2026-11-26 (3 queries, 15 clips each). Clip download from cdn.pixabay.com returned HTTP 429 from Cloudflare in my tests (default, referer and browser User-Agent), so end-to-end download is NOT verified. Retest later; the adapter falls back cleanly if download fails.
- Commit access: the coding agent has read-only GitHub API access; commits go through the browser editor.
- Fast lane watch wiring (section 11), provider-fallback adapters (section 10), possible licensing check for Egypt/Saudi finance content.

## 10. Alternatives register (خزينة البدائل)
Standing rule from the owner: no single dependency may stall the channel. Each row: primary, ready fallback, limits, and the trigger to switch. "Tested" means a real call or run; everything else is read from the source named.

| Component | Primary | Fallback (ready to use) | Limits to know | Switch when |
| --- | --- | --- | --- | --- |
| Rendering | GitHub Actions (manual dispatch) | 1) Local render on the owner's PC, private source, no publish step: Python 3.11, FFmpeg, `pip install -r requirements.txt`, `python -m newsflow --render-only` (PC specs pending, not yet tested). 2) Self-hosted runner on his PC (free per docs.github.com/en/actions/concepts/billing-and-usage; keep the repo private). NOT AN AUTOMATIC FALLBACK: flipping the repo to public (free Actions minutes) needs separate explicit owner approval after a privacy review, because it exposes Actions history and logs to everyone and public forks cannot be pulled back. | GitHub's table (docs.github.com/en/billing/reference/product-usage-included, read 2026-11-26) lists the Free plan as $12 USD of included Actions compute per month, not a fixed 2,000 minutes: check Settings > Billing for the real remaining figure before planning. The private repo's minutes reset Dec 1. | Billing shows under 20 percent left, a run is refused for budget, or GitHub is down. Never change repo visibility without the owner's explicit approval after a privacy review. |
| LLM (script, fact-check) | Groq `openai/gpt-oss-120b`, free tier (key tested 2026-11-26: models list and a chat call returned 200) | 1) Same Groq org: `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`. 2) Cerebras free tier, same `gpt-oss-120b` model (inference-docs.cerebras.ai). 3) Gemini API free tier (aistudio.google.com/docs/pricing; the free tier lets Google use content to improve products, fine for public news only). 4) OpenRouter `:free` models. | Groq free per model: 30 requests/min, 1,000/day, 8,000 tokens/min, 200,000 tokens/day (console.groq.com/docs/rate-limits as quoted by third-party checks dated 10-23 Nov 2026). Gemini free about 15 req/min, 500/day. OpenRouter free: 20/min, 50/day. | HTTP 429 that retries do not clear, a model removed from the free list (Groq removed Llama 3.1 8B and 3.3 70B on 2026-08-16), or a key revoked. Switch via `NEWSFLOW_GROQ_MODEL` first. Provider fallbacks 2-4 need a small adapter in `fact_check.py` and `scriptwriter.py` that is NOT written yet; not tested (no keys). |
| Web search for fact-check | Tavily free "Researcher" plan, 1,000 credits/month (323 used on 2026-11-26; key tested: search returned 200) | Publisher-page fetch already in `source_evidence.py` (no key); RSS summaries | Credits are monthly | Under 10 percent of credits left: fact-check falls back to original-page evidence only and the story stays unverified unless two readable sources agree. |
| Stock footage | Pexels API (secret exists; free; not verified) | Pixabay API (Content License; free key; 100 requests per 60 s; responses cached 24 h; no permanent hotlinking, download first; show attribution where results are displayed: pixabay.com/api/docs, pixabay.com/service/license-summary) | Pixabay license forbids trademarks/logos in commercial use | Pexels key rejected or empty results. Adapter WRITTEN 2026-11-26 (`newsflow/pixabay.py`, wired in `broll.py`): used automatically when the Pexels search fails and `PIXABAY_API_KEY` is set, or first with `NEWSFLOW_BROLL_PROVIDER=pixabay`. Attribution handles both sources. Unit-tested with mocked responses only; NOT tested against the live API because no Pixabay key exists yet (needs a free account and key, then add `PIXABAY_API_KEY` to repo Secrets and the workflow env, and to the local .env). |
| Music | YouTube Audio Library (monetization allowed, some tracks need a credit line; support.google.com/youtube/answer/3376882) | No music at all (voice and captions only) is zero risk. Pixabay music is a candidate; its license page was not checked for music, verify before use. | Audio Library downloads are manual from YouTube Studio | A track gets a claim or the library is unavailable: ship without music. |
| Voice | The owner's own recorded narration | Cloned voice from his recording, see section 12 | | He cannot record in time. |
| Repo hosting | GitHub private repo | Local clone on the owner's PC (private). Public flip is not a fallback; see Rendering. A second remote (GitLab or Codeberg) is an idea, not checked. | | GitHub unreachable for more than a few hours: render locally from the clone. |
| Credentials | Vault entries "Groq API key (newsflow-pipeline)" and "Tavily API key (newsflow-pipeline)"; GitHub repo secrets | Regenerate a key in the provider console (accounts are under the owner's Gmail via Google sign-in) | | A key leaks or is revoked. |

## 11. Fast lane: breaking Egyptian moments with a money angle
Owner example (2026-11-26): the fire at Nazlet el-Kobba / Boulaq the day before. A Short like "الحريق كلف التجار كام؟" with a trending title and hashtags would have ridden the moment.
Flow (target: hours, not days):
1. Watch (needs the Groq and Tavily keys, now in Secrets): the scheduled `newsflow.yml` collects Egyptian news RSS; `fastlane.money_angles()` flags items with a loss, compensation, traders, prices, markets or policy angle. Tavily search then gathers figures and trending terms. Not wired yet.
2. Gate (built, tested): `fastlane.build_short_brief()` blocks unless every figure has an https source, there are at least two independent source domains, and the event has a money angle. Events with deaths or injuries are flagged sensitive: economic fallout only, no victim names, no blame, owner review before publishing.
3. Title and hashtags (built, tested): question-style Arabic title from the angle (at most 70 characters), hashtags from the trending terms first, then #كشف_حساب, #Shorts, #اقتصاد_مصر (at most 8; YouTube shows the first three).
4. Render: the v3 Short renderer (palette A, 720x1280, 35-45 s, final numbers only, sources in the description). That script lives in the author's workspace and is NOT committed yet; commit it before wiring the lane.
5. Narration: the owner's recording or the cloned voice (section 12). This is the step that decides whether "hours" is real: a fast Short needs a voice within hours.
6. Upload PRIVATE for the owner's one-tap approval, then publish.
Rules: never state a number that is not in a source; never guess a cause or blame; the owner approves the first fast-lane Short before the lane runs unattended.

## 12. Voice cloning research (2026-11-26), for the owner's own voice
Goal: he records once, the pipeline narrates in his cloned voice. Free, local, commercial use on monetized YouTube. Nothing is built or promised yet.
- Recommended to test first: Cairo-TTS (Egyptian Arabic, code and model on Hugging Face mohammedaly22/Cairo-TTS, pip package cairo-tts). Egyptian dialect, about 100M parameters, runs on a laptop CPU (the project reports about 2.6x real time on an i7-10750H), zero-shot cloning from a 5-10 s clean recording. Code is MIT. Weights are fine-tuned from Kyutai Pocket TTS and "follow the Pocket TTS terms"; the Pocket TTS card on Hugging Face declares CC-BY-4.0 (commercial use allowed with attribution) plus a prohibited-use clause against deception. Open points: the Cairo-TTS weights license is stated only by reference (its NOTICE.md could not be fetched); it was trained on about 747 hours of Egyptian podcast speech whose rights are not stated; its model card asks creators to disclose synthetic audio. Quality for his voice is UNTESTED (no run was possible: the sandbox has 1 CPU and 1 GB RAM). Needs his 38-second sample to judge.
- Not safe: Coqui XTTS-v2 (license text: "allows only non-commercial use of a machine learning model and its outputs"); F5-TTS pretrained models (README: CC-BY-NC because of the Emilia data); ElevenLabs free plan (docs: no commercial license); Fish Audio free plan (the plan page lists commercial use but the site FAQ says the free plan is for personal use only, and the free API window is announced only through 2026-11-30: contradictory, do not rely on it).
- Unresolved: Habibi-TTS EGY (SWivid/Habibi-TTS): Apache 2.0 label, strong Egyptian metrics in the paper, but the paper says it was initialized from F5-TTS weights, which the F5-TTS README licenses CC-BY-NC, and trained on datasets with their own terms. The Apache label may not hold; do not use for monetized video without clearing this. Needs a GPU in practice.
- Alternative: Chatterbox Multilingual V3 (MIT, includes Arabic but not Egyptian-specific, 500M parameters, archived as of Aug 2026).
- Hardware if local: Cairo-TTS runs on a normal laptop CPU; GPU not needed. Unknown: his PC specs.
- YouTube's rules on disclosing realistic synthetic audio were not checked here; check before the first upload.

## 13. Local render engine (second engine) for the owner's PC

Status 2026-11-26: built, NOT yet run on his PC. Target machine, final answer from the owner (corrects an earlier wrong Ryzen 7 note): HP ProBook 650 G4, Intel Core i3-8130U (2 cores / 4 threads, up to 3.4 GHz), 16 GB RAM (8 GB + 8 GB, upgraded; owner's update 2026-11-26), one SSD + one HDD (sizes not confirmed after the change), Intel UHD 620 (no usable GPU encoding), Windows 11.

What it is: the same `python -m newsflow --render-only` pipeline that Actions runs (same episode data, same renderer) plus `local/run_local.py` (preflight, low-memory settings, timing log). Uploads are forced off and privacy stays private; nothing is published from his PC.

Code changes that make it portable (Linux/Actions behaviour unchanged; the 215-test suite gives identical results before and after):
- Font lookup searches `NEWSFLOW_FONT_DIR`, then `./fonts`, then Linux paths, then Windows system fonts (Segoe UI, Arial, Tahoma).
- `NEWSFLOW_FFMPEG_THREADS` caps x264 threads (run_local.py sets 2). The renderer already encodes one scene at a time, so memory stays small on 16 GB. The thread cap of 2 stays because the i3 is CPU-bound, not RAM-bound.

### Render time and care for this laptop (ESTIMATES, not measured on his machine)
Basis: on a single Xeon vCPU in my sandbox, FFmpeg at the pipeline's settings (veryfast, crf 22, 1 thread) encoded a 1080p zoompan clip at about 0.9x real time and a b-roll style scale+crop clip at about 0.45x real time. The i3-8130U with 2 encoder threads should be somewhat faster than that single vCPU, but plan for the same order of speed. Encoding is not the whole job: Arabic caption frames, clip downloads and the final mux add time I did not measure.
- Short (about 45 s, 9:16): plan 5 to 15 minutes.
- Long video (about 10 min, 16:9): plan 30 to 90 minutes. Do not use the laptop for anything else during that time.
- These are guesses to plan with. The first real run writes the true minutes to `output/local_render_log.json`; replace these ranges with that number.
Care while rendering: plug in the charger (on battery the CPU slows down), set Windows power mode to Best performance, close the browser and other apps (16 GB is plenty, but a free CPU renders faster), keep at least 10 GB free on the SSD (C:), and do not close the lid or let it sleep. If it overheats or freezes, lower threads: set `NEWSFLOW_FFMPEG_THREADS=1` in `.env`. Keep the project on the SSD, not the HDD.

### Install on Windows 11 (numbered, in order; about 15 minutes)
Do these once. Open "Terminal" or "PowerShell" from the Start menu (normal window, not admin) unless a step says otherwise.
1. Install Python: `winget install Python.Python.3.11`. Close the window and open a new one.
2. Install FFmpeg: `winget install Gyan.FFmpeg`. Close the window and open a new one.
3. Check both: `python --version` (shows 3.11) and `ffmpeg -version` (shows a version). If either says "not recognized", restart the laptop and try again.
4. Download the project: open the repo page on GitHub while signed in, choose Code, Download ZIP, unzip it to `C:\newsflow`. Open the terminal in that folder (in the folder, right-click, Open in Terminal).
5. Install the libraries: `pip install -r requirements.txt`
6. Create the keys file: in the folder, create a text file named `.env` (Notepad: Save as, type `.env`, file type All files) with these lines, each followed by its value: `GROQ_API_KEY=`, `TAVILY_API_KEY=`, `PIXABAY_API_KEY=` (Pexels is optional and unverified), and the voice line `NEWSFLOW_TTS_VOICE=ar-EG-ShakirNeural` (default; change only to his pick: `ar-EG-SalmaNeural` or `ar-SA-HamedNeural`). Keys: saved vault and repo-Secret values cannot be read back by anyone, so the laptop needs its own free keys: sign in to console.groq.com, app.tavily.com and pixabay.com/api/docs with the project Google account and create one key each (about 2 minutes each, free). Paste them only into `.env`, never into chat. Never share or upload this file. Do NOT put YouTube OAuth values in it: the first video is uploaded by hand (see below).
7. Check the machine: `python local/run_local.py --check`. It must print `[LOCAL_PREFLIGHT_OK]`.
8. Render: `python local/run_local.py`. Results are in the `output` folder; the minutes taken are saved in `output/local_render_log.json`.
Optional, same look as Actions: put NotoSansArabic-Regular.ttf and NotoSansArabic-Bold.ttf in a folder named `fonts` next to `local`. Without them Windows fonts (Segoe UI, Arial) are used; Arabic shows, the letter shapes differ slightly.

### What the first local video does, end to end (built, UNTESTED on his laptop)
`python local/run_local.py` runs `python -m newsflow --render-only`:
1. Topic: RSS sources in `config/sources.yml` plus Tavily trend-radar candidates (money angle only), freshness filter, then the editorial gate. He does not pick the topic; the pipeline takes the top story that passes every gate. If none passes it stops with `[BLOCKED]` and renders nothing.
2. Evidence and fact check: fetches the original publisher page, checks numbers against the source text, writes `output/fact_check/`. A story that fails is dropped.
3. Script: Groq model (fallback chain, section 14) writes the Arabic plan; hook rule rejects openings with a greeting. Written to `output/bulletin/script.txt`.
4. Narration: edge-tts with `NEWSFLOW_TTS_VOICE` (Shakir unless he chose another). Needs internet; the voice is Microsoft's online service, unofficial. Output `voice.mp3`.
5. B-roll: Pixabay (or Pexels) clips downloaded and cached, attribution kept.
6. Render: FFmpeg, 2 threads, to `output/bulletin/long.mp4` plus companion Shorts in `output/bulletin/shorts/`. Video QA checks audio and video length match.
7. `output/bulletin/upload_kit.txt` (new): title, description with sources and B-roll attribution, tags, and the two Studio settings to set.
8. Private upload BY HAND: Studio, Create, Upload videos, pick `long.mp4`, paste from `upload_kit.txt`, Visibility Private, Altered content Yes. Nothing is public until he clicks publish. Thumbnails come from the audit-package path (`thumb_A.jpg`, `thumb_B.jpg`), not from this run; make or upload the thumbnail in Studio.
Voice: his pick from the 3 samples is pending. If he has not answered by render time, run with Shakir and tell him which voice it was.
Windows portability: `newsflow/broll.py` and `newsflow/rendering.py` use the portable font lookup (./fonts, then Windows fonts). Not verified on a real Windows machine.

### Needs Actions (cannot be done from the laptop path)
- Scheduled and automatic runs (cron, private staging, automatic upload): upload needs YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN, which exist only as write-only repo Secrets and may be stale. Manual dispatch of `newsflow.yml` (private_test) and the full-automation date Dec 1 depend on Actions minutes resetting.
- `quality.yml` test run, and render-minute measurement on a GitHub runner.
- `comment-desk.yml` (needs the refresh token with the readonly scope).
- Test & Compare thumbnails, the scorecard and Altered-content check are Studio, by hand either way.
- Self-hosted runner on the laptop is the other free route (section 10), not set up.

### If step 7 says RAQM / Arabic shaping is missing: WSL2 fallback (Ubuntu inside Windows)
The renderer refuses to run without proper Arabic shaping, by design. Linux inside Windows behaves exactly like Actions.
1. Open PowerShell as administrator (right-click Start, Terminal (Admin)) and run `wsl --install -d Ubuntu`. Restart the laptop when asked, then open "Ubuntu" from the Start menu and create a username and password.
2. In Ubuntu: `sudo apt update && sudo apt install -y python3-pip python3-venv ffmpeg fonts-dejavu-core fonts-noto-core unzip`
3. Copy the project in: `cp -r /mnt/c/newsflow ~/newsflow && cd ~/newsflow` (the unzipped folder from step 4 above).
4. `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`
5. Put the `.env` file in `~/newsflow` (copy it: `cp /mnt/c/newsflow/.env ~/newsflow/.env`).
6. `python local/run_local.py --check`, then `python local/run_local.py`.
7. Results are in `~/newsflow/output`. To see them in Windows, open File Explorer and go to `\\wsl$\Ubuntu\home\<username>\newsflow\output`.
WSL2 needs about 1 to 2 GB of the 16 GB RAM while running; close the browser during renders. Never run both engines for the same episode.

Not verified: everything above on his actual laptop (an i3 is slower than the first Ryzen 7 assumption; times above are for the i3). The preflight, font lookup and thread cap were tested on Linux only. The winget package IDs (Python.Python.3.11, Gyan.FFmpeg) and WSL commands are from memory of how those tools work and were not run here. If any step fails, copy the error text to the engineer, never any key.

Not done: measured render minutes on his PC; narration is still the owner's recording; Pexels key status (see section 9).

## 14. LLM fallback chain and Tavily trend radar (added 2026-11-26)

Status: built and unit tested; NOT yet run against the live Groq, Tavily or fallback providers (those keys exist only as repo Secrets, and Actions minutes are used up until Dec 1).

LLM chain (`newsflow/llm.py`, used by the fact checker and the script writer):
- Order: Groq primary model (`NEWSFLOW_GROQ_MODEL`, default `openai/gpt-oss-120b`), then Groq `NEWSFLOW_GROQ_FALLBACK_MODELS` (default `openai/gpt-oss-20b`), then optional providers that have a key: `CEREBRAS_API_KEY` (model `gpt-oss-120b`), `GEMINI_API_KEY` (`gemini-2.5-flash`), `OPENROUTER_API_KEY` (`openai/gpt-oss-120b:free`). Override a model with `NEWSFLOW_CEREBRAS_MODEL`, `NEWSFLOW_GEMINI_MODEL`, `NEWSFLOW_OPENROUTER_MODEL`. Force an order with `NEWSFLOW_LLM_PROVIDERS` (for example `cerebras,groq`).
- A candidate is skipped on any error (rate limit, quota, 5xx, timeout, empty answer) and the next one is tried. A strict-JSON failure on the first fact-check call still gets the existing compact retry first.
- Fallback models get plain JSON mode instead of strict json_schema and no `tool_choice`. The local evidence validators and number checks are unchanged, so a weaker model cannot pass a story the gates reject. The fact-check record's `model` field names the model that actually answered.
- Today only Groq models are active (no new accounts were created). That covers a model-level limit but NOT a full Groq outage. To cover an outage the owner approves one free account (Cerebras free tier is the first choice; Google AI Studio Gemini is the second) and its key goes into the matching repo Secret. The workflow already passes the three optional keys (empty until a Secret exists).
- Endpoints checked against the providers' docs on 2026-11-26: https://inference-docs.cerebras.ai/resources/openai and https://aistudio.google.com/docs/openai. Model ids are from the docs and not live-tested.

Trend radar (`newsflow/trend_radar.py`, called from `collect()` in pipeline.py):
- Up to 3 Tavily news searches per run (basic depth, last day; 1 credit each), `NEWSFLOW_TREND_RADAR_QUERIES=0` turns it off. Results become trend signals in the same shape as the Google Trends ones, so `attach_trend_signals()` boosts matching stories in the ranking. A signal is never a story and never a fact; fact checking is unchanged.
- Fail-soft: no key or any Tavily error returns no signals and the run continues.
- Tavily parameters checked against https://docs.tavily.com/documentation/api-reference/endpoint/search.

Radar-to-topic path (requested through the main agent on 2026-11-26; the owner has not separately signed off on this feature):
- Radar signals that match no collected story can become candidate episode topics, so the radar finds topics and does not only re-rank them. The cap is `NEWSFLOW_RADAR_TOPICS_MAX` (default 3, 0 turns it off).
- Editorial filter, from the owner's standing rule that the channel format is "what did it cost people" and not plain news (example: "الحريق كلف التجار كام؟"). A candidate needs ALL of these:
  1. A real article URL from Tavily, not already among the collected stories, and no collected story covers the same headline.
  2. A clear money angle (`money_angle()` in `newsflow/trend_radar.py`): an explicit amount with a currency or billion/million in the title; or a cost, loss, price, tax, fee, wage, tariff or similar term in the title; or an amount in the snippet together with an economy or market headline. A headline like a fire, a match or a speech with no money in it is dropped.
  3. The normal editorial `relevance()` check (direct finance terms, no sport, no generic politics). The candidate gets the neutral category "رادار الترند", so there is no finance-category shortcut.
- A candidate is then an ordinary story: lookback window, `select_stories`, original-article extraction, and the same fact-check gates. A story whose original article cannot be read or verified is not produced. The money-angle word lists are in the code and are easy to extend after the first real runs.
- Tested: unit tests for accept, reject, matched-signal, cap, off switch and selection, plus a run of `collect()` with a mocked radar. Not run against live Tavily results yet, so the real hit rate is unknown until the Dec 1 run.

## 15. Thumbnail A/B pair, comment desk, and later items (added 2026-11-26)

Status: built and unit tested; NOT run against live YouTube.

Thumbnail pair (`wealthradar_audit/thumbnails.py`, called from `prepare_episode`):
- Every audit episode package now writes `thumb_A.jpg`, `thumb_B.jpg` and `thumbnails.json` (palette A, 1280x720, under 2 MB). The numbers come from the calculator's verified cash result; nothing is invented, and a brief with no verified result produces no thumbnail.
- Brand-led system (owner decision 2026-11-26: people bond with the channel, not his face, like the BBC). Every thumbnail carries the same identity: navy gradient, a gold bar along the bottom edge, and a small radar-ring wordmark at bottom left in soft text (no box, no badge). A face is never required.
- Each design has three elements at most. A (result-first): a drawn banknote with the lost share torn away (kept share = 1 + real return), the big number in coral (loss) or mint (gain), and one label "قوة شراء فلوسك". B (curiosity-first): the whole banknote, a big gold question mark, and the open question "بقوا كام دلوقتي؟"; the answer stays in the video. They differ in layout and emphasis, so the test measures a real difference.
- Why this shape (secondary sources, patterns not measured winners for our channel): ThumbnailBench's 2026 study of 11,223 covers from 1,043 channels over 100k subscribers found finance has a face on 88% of covers, a number on 39%, text on 94%, median 4 words (https://thumbnailbench.com/resources/youtube-thumbnail-study-2026). Large money visuals plus one big number are common in the top finance thumbnails viewed (Mark Tilbury, Graham Stephan, the Egyptian channel Ahmed Hisham Banknote). Our brand-led choice drops the face on purpose; the banknote is the visual anchor. Whether it earns clicks is for the Test & Compare data to say.
- YouTube's Test & Compare is Studio-only: it works from a computer in YouTube Studio, takes up to 3 thumbnails and picks the winner by watch time (https://support.google.com/youtube/answer/16391400). It is not in the Data API, so the owner uploads A and B in Studio by hand. The API sets only one thumbnail.
- The newsflow `thumbnail.py` (footage-frame thumbnail, older style) is not used by the audit episodes and was left alone.
- Verified by rendering both images and checking them at full size and at phone size (168x94). The wordmark name is a parameter (`channel`, default "WealthRadar"), so the pending rename to "كشف حساب" is one value.

Comment desk (`newsflow/comment_desk.py`, manual workflow `.github/workflows/comment-desk.yml`, or `python -m newsflow.comment_desk` on the owner's PC):
- Read-only. It uses the `youtube.readonly` scope and only list calls (channels, playlistItems, commentThreads; about 1 quota unit each). The module has no call that posts, edits or deletes, a test checks that, and the scope could not do it anyway. Posting a reply later would need a different scope (`youtube.force-ssl`) and a new owner decision.
- Output: `output/comment_drafts.md` and `.json`, sorted criticism, advice requests, questions, praise, then spam. Each comment has a draft reply and the status `needs_owner_approval`. The owner posts the replies he approves by hand.
- Drafting rules: advice requests ("اشتري ايه؟") get a fixed reply that says the channel gives numbers and no buy or sell advice, and never reach the model. Spam and links get no reply. Other replies use the LLM chain, treat the comment as data only, and are checked locally: Arabic, at most 280 characters, no link, no number the viewer did not write, no buy, sell or guarantee wording. Any failure falls back to a fixed reply.
- Limits: on Actions the "already seen" file does not persist between runs, so a rerun can show the same comments again. On his PC it persists in `output/comments_state.json`. The refresh token must carry the readonly scope. The upload pipeline already requests it (upload + readonly), but I could not read the token's real grants, so this is unverified until the first run.

Later items (not built, no real data yet):
- Weekly analytics report (CTR and retention) once real data exists after Dec 1. It needs the YouTube Analytics API, which means one more read scope on the refresh token, so it needs an owner decision at that time.
- Light background music as a later audio upgrade. Free and licensed only. Candidates: the YouTube Audio Library (the register in section 9 lists its credit rules). Keep it under the voice, off by default, and check each track's license before use.

## 16. Narration voice and voice research (2026-11-26)

Decision (owner, via the main agent): launch Dec 1 with the best free Arabic voice. The voice clone path is parked; his 1:22 sample is kept privately outside the repo for a later GPU test where his own ear decides.
- Voice now: edge-tts `ar-EG-ShakirNeural` (Egyptian, male), fallbacks `ar-EG-SalmaNeural` then `ar-SA-HamedNeural`. Set in `newsflow/pipeline.py` (EDGE_VOICE_DEFAULT) and in the workflow env `NEWSFLOW_TTS_VOICE`. Reason: the old default, Hamed, is a Saudi voice; the channel speaks Egyptian. UNTESTED BY EAR and number reading untested; revert is one line in each file. Note: edge-tts is an unofficial client of Microsoft's Edge read-aloud service (its license shows as "Other"); Microsoft publishes no free commercial terms for that route, so treat it as a risk to replace when a clearly licensed voice is good enough.
- Cairo-TTS: pip package is MIT, but the Hugging Face weights repo returned HTTP 401 on 2026-11-26 (private, gated or removed), so it cannot be tested. Re-check periodically.
- Open-weight candidates found (none judged by ear): Habibi-TTS Egyptian specialised model (Apache-2.0 per the author's license answer on https://huggingface.co/SWivid/Habibi-TTS/discussions/1, the unified model is CC-BY-NC-SA; needs a GPU in practice); Nabra-82M Egyptian (Apache-2.0 label, 82M, runs on CPU, one male voice, the card says slightly dull; dataset license not stated); NAMAA-Egyptian-TTS (MIT, 0.5B, GPU); VoiceTut-TTS (Apache-2.0, GPU, card reports Egyptian WER 0.40). Not safe for monetized use: models whose card says non-commercial or asks for permission (some Habibi fine-tunes, lahgtna-omnivoice, XTTS).
- Standing task: the build agent re-checks new Arabic and Egyptian TTS or cloning releases every 3 days and reports only a material improvement.

## 17. Intro ident (owner decision 2026-11-26, not built yet)
Brand-led, not face-forward: a short branded ident (radar ring, wordmark, gold bar, palette A), 2 to 3 seconds. His face is an optional element only. The hook rule (section 18) wins on order: the ident, if used, comes AFTER the first promise line, never before it.

## 18. Platform rules from the owner (2026-11-26) and how they are encoded
1. Suggested/Browse-first packaging: curiosity plus a clear promise in the title and thumbnail; keywords only as natural words in the description. `wealthradar_audit/packaging.py` `title_problems()` checks length (100), repeated words, stray punctuation and hashtags (3 at most). It is a mechanical check; whether the promise is real is a human and fact-check call.
2. Hook rule (template constraint): the first 5 to 10 seconds state the result. `newsflow/hook_rule.py` rejects an opening with a greeting, channel intro or "before we start" and one over 23 words. `validate_story_plan` in `newsflow/scriptwriter.py` now rejects Short plans whose hook breaks it (the story is skipped). For audit episodes call `packaging.script_hook_problems(first_line)` on the finished narration before render; it also requires a number. This call is NOT yet wired into a render step for audit episodes (they have no pipeline wiring yet): whoever wires the render must call it.
3. A/B protocol: `launch_checklist.md` is written into every audit package. Test & Compare is Studio-only and manual; the decision metric is average view duration (and viewer satisfaction), not CTR alone.
4. Accuracy and disclosure: all numbers come from the sourced snapshot, sources go in the description. The upload body now sets `status.containsSyntheticMedia = true` (`upload_status_body` in `newsflow/pipeline.py`; off only with NEWSFLOW_DECLARE_SYNTHETIC=false). The field is documented at https://developers.google.com/youtube/v3/docs/videos (added in the 2024-10-30 API revision, https://developers.google.com/youtube/data/revision_history). NOT verified against a live upload; the checklist makes the owner confirm "Altered content: Yes" in Studio. YouTube's own rule on what must be disclosed: https://support.google.com/youtube/answer/14328491 (the owner chose to disclose TTS narration).
5. Per-video scorecard: `scorecard.csv` template (retention at 30 s, where it dips, average view duration, watch time, Suggested and Browse versus Search traffic). Filled by hand after Dec 1 when Analytics has data; an automatic weekly pull needs the YouTube Analytics read scope (owner decision then, section 15).

## 19. Pickup for Dec 1 (the build agent that wrote this expires 2026-11-27)
State: PR #91 (branch video-quality-upgrade) is OPEN and must NOT be merged by an agent; the owner merges. Every commit used `[skip ci]` because Actions minutes were used up until Dec 1. Nothing on the branch has run in Actions since these changes, so the first run is the real test.
Dec 1 verification checklist, in order:
1. Confirm Actions minutes reset (repo Settings, Billing). Do not change repo visibility, do not create accounts.
2. Run `quality.yml` on the branch. Expect failures only from the 3 old known errors (test_predictions ledger, two test_production_method_contract tests) that came from a partial checkout; in a full checkout they may pass. Anything else is new: fix it before going on.
3. Render-minute measurement: dispatch `newsflow.yml` with `private_test=true` and `dry_run=false` once, then write down the total job minutes and the minutes of the render step (Actions run page, each step shows its duration). Replace the guessed ranges in section 13 with that number. Billing counts rounded-up minutes per job.
4. In that run's logs check: the LLM chain used a model (Groq first), the trend radar ran with Tavily signals, b-roll came from Pexels or Pixabay (Pexels key is unverified; Pixabay CDN returned HTTP 429 from the sandbox, so confirm the real download), and `[VOICE_READY] Edge neural voice ar-EG-ShakirNeural` appears (a different voice name means the fallback ran).
5. Open the output video and the thumbnails and look at them. Listen to the narration; the owner confirms the voice (Shakir was the recommended pick; Salma and Hamed are the alternatives).
6. Upload PRIVATE only. In Studio check "Altered content" shows Yes (section 18, item 4). Upload `thumb_A.jpg` and `thumb_B.jpg` under Test & Compare.
7. Run the manual `comment-desk.yml` once after the first comments exist and review `output/comment_drafts.md`. Nothing is posted by the tool.
8. Report what failed as it is. Do not claim the pipeline works until step 3 to 6 have passed.
