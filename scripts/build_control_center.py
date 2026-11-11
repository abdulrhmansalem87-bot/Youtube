from __future__ import annotations

import html
import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

API = "https://api.github.com"
REPO = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ["GITHUB_TOKEN"]
OUT = Path(os.environ.get("DASHBOARD_OUTPUT", "control-center"))
OUT.mkdir(parents=True, exist_ok=True)


def api(path: str) -> dict:
    request = urllib.request.Request(
        API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def safe(value: object) -> str:
    return html.escape(str(value if value is not None else "—"))


def main() -> None:
    payload = api(f"/repos/{REPO}/actions/runs?per_page=30")
    runs = payload.get("workflow_runs", [])
    rows = []
    counts = {"success": 0, "failure": 0, "in_progress": 0, "other": 0}
    details = []
    for run in runs:
        name = run.get("name", "Workflow")
        if name not in {"NewsFlow pipeline", "WealthRadar Shorts", "WealthRadar Shorts Batch", "Quality checks"}:
            continue
        conclusion = run.get("conclusion") or run.get("status") or "unknown"
        if conclusion in counts:
            counts[conclusion] += 1
        else:
            counts["other"] += 1
        jobs_data = api(f"/repos/{REPO}/actions/runs/{run['id']}/jobs?per_page=100")
        jobs = jobs_data.get("jobs", [])
        job_html = ", ".join(
            f"{safe(job.get('name'))}: <b>{safe(job.get('conclusion') or job.get('status'))}</b>"
            for job in jobs
        ) or "No job details"
        created = run.get("created_at", "")
        try:
            cairo_time = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(ZoneInfo("Africa/Cairo")).strftime("%Y-%m-%d %H:%M")
        except Exception:
            cairo_time = created
        url = run.get("html_url", "#")
        rows.append(
            "<tr>"
            f"<td>{safe(cairo_time)}</td><td>{safe(name)}</td>"
            f"<td><span class='status {safe(conclusion)}'>{safe(conclusion)}</span></td>"
            f"<td>{job_html}</td>"
            f"<td><a href='{safe(url)}' target='_blank' rel='noopener'>فتح التشغيل</a></td>"
            "</tr>"
        )
        details.append(f"| {cairo_time} | {name} | {conclusion} | [التفاصيل]({url}) |")

    cards = "".join(
        f"<article><small>{label}</small><strong>{counts[key]}</strong></article>"
        for key, label in [
            ("success", "ناجح"), ("failure", "فاشل"),
            ("in_progress", "قيد التشغيل"), ("other", "حالات أخرى")
        ]
    )
    table = "".join(rows) or "<tr><td colspan='5'>لا توجد تشغيلات مسجلة بعد.</td></tr>"
    generated = datetime.now(ZoneInfo("Africa/Cairo")).strftime("%Y-%m-%d %H:%M:%S")
    document = f"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WealthRadar Control Center</title>
<style>
:root{{color-scheme:dark;--bg:#081321;--panel:#102238;--line:#24415d;--gold:#d9b66f;--muted:#9fb2c6}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(145deg,#07111e,#10243a);color:#edf4fb;font-family:Tahoma,Arial,sans-serif;padding:22px}}
main{{max-width:1100px;margin:auto}}header{{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}}
h1{{margin:0;color:var(--gold);font-size:clamp(24px,4vw,38px)}}p,small{{color:var(--muted)}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}}
article,.table-wrap{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px}}article strong{{display:block;font-size:32px;margin-top:8px}}
.table-wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;min-width:760px}}th,td{{padding:13px;text-align:right;border-bottom:1px solid var(--line);vertical-align:top}}th{{color:var(--gold)}}
.status{{padding:4px 9px;border-radius:20px;background:#31445a}}.success{{color:#75e0ae;background:#123c31}}.failure{{color:#ff9d9d;background:#4a2028}}.in_progress{{color:#f6d47d;background:#493c1d}}
a{{color:var(--gold)}}footer{{margin-top:18px;color:var(--muted);font-size:12px}}
@media(max-width:650px){{body{{padding:14px}}.cards{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><main>
<header><div><h1>WealthRadar</h1><p>مركز متابعة التشغيل والإنتاج والنشر</p></div><div>آخر تحديث: {safe(generated)} بتوقيت القاهرة</div></header>
<section class="cards">{cards}</section>
<section class="table-wrap"><h2>آخر التشغيلات</h2><table><thead><tr><th>التوقيت</th><th>المسار</th><th>الحالة</th><th>تفاصيل المهام</th><th>الرابط</th></tr></thead><tbody>{table}</tbody></table></section>
<footer>لوحة خاصة مبنية من GitHub Actions. النجاح هنا يعني نجاح المهمة التقنية فقط؛ لا يعني نشر فيديو علناً. حالة النشر لا تُثبت إلا برابط YouTube ومعرّف الفيديو وحالة الخصوصية.</footer>
</main></body></html>"""
    (OUT / "index.html").write_text(document, encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("# WealthRadar Control Center\n\n")
            handle.write(f"آخر تحديث بتوقيت القاهرة: **{generated}**\n\n")
            handle.write("| ناجح | فاشل | قيد التشغيل | أخرى |\n|---:|---:|---:|---:|\n")
            handle.write(f"| {counts['success']} | {counts['failure']} | {counts['in_progress']} | {counts['other']} |\n\n")
            handle.write("| الوقت (القاهرة) | المسار | الحالة | التفاصيل |\n|---|---|---|---|\n")
            handle.write("\n".join(details) if details else "| — | — | لا توجد تشغيلات | — |")
            handle.write("\n\n**تنبيه:** نجاح workflow لا يثبت النشر العام؛ يلزم Video ID ورابط يوتيوب والتحقق من الخصوصية.\n")
    print(f"Dashboard generated: {OUT / 'index.html'}")


if __name__ == "__main__":
    main()
