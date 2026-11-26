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
6. Create the keys file: in the folder, create a text file named `.env` with three lines: `PEXELS_API_KEY=`, `GROQ_API_KEY=`, `TAVILY_API_KEY=` followed by each key. The keys come from his secure vault links, never from chat. Never share or upload this file.
7. Check the machine: `python local/run_local.py --check`. It must print `[LOCAL_PREFLIGHT_OK]`.
8. Render: `python local/run_local.py`. Results are in the `output` folder; the minutes taken are saved in `output/local_render_log.json`.
Optional, same look as Actions: put NotoSansArabic-Regular.ttf and NotoSansArabic-Bold.ttf in a folder named `fonts` next to `local`. Without them Windows fonts (Segoe UI, Arial) are used; Arabic shows, the letter shapes differ slightly.

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

Radar-to-topic path (owner-approved 2026-11-26):
- Radar signals that match no collected story can become candidate episode topics, so the radar finds topics and does not only re-rank them. The cap is `NEWSFLOW_RADAR_TOPICS_MAX` (default 3, 0 turns it off).
- Editorial filter, from the owner's standing rule that the channel format is "what did it cost people" and not plain news (example: "الحريق كلف التجار كام؟"). A candidate needs ALL of these:
  1. A real article URL from Tavily, not already among the collected stories, and no collected story covers the same headline.
  2. A clear money angle (`money_angle()` in `newsflow/trend_radar.py`): an explicit amount with a currency or billion/million in the title; or a cost, loss, price, tax, fee, wage, tariff or similar term in the title; or an amount in the snippet together with an economy or market headline. A headline like a fire, a match or a speech with no money in it is dropped.
  3. The normal editorial `relevance()` check (direct finance terms, no sport, no generic politics). The candidate gets the neutral category "رادار الترند", so there is no finance-category shortcut.
- A candidate is then an ordinary story: lookback window, `select_stories`, original-article extraction, and the same fact-check gates. A story whose original article cannot be read or verified is not produced. The money-angle word lists are in the code and are easy to extend after the first real runs.
- Tested: unit tests for accept, reject, matched-signal, cap, off switch and selection, plus a run of `collect()` with a mocked radar. Not run against live Tavily results yet, so the real hit rate is unknown until the Dec 1 run.
