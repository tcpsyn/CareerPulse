import json
import logging
from datetime import datetime, timezone, timedelta
from html import escape

logger = logging.getLogger(__name__)


async def generate_digest(db, min_score: int = 60, hours: int = 24) -> dict:
    """Generate a digest of new high-scoring jobs from the last N hours."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    cursor = await db.db.execute("""
        SELECT j.*, js.match_score, js.match_reasons
        FROM jobs j
        JOIN job_scores js ON j.id = js.job_id
        WHERE js.match_score >= ? AND j.created_at >= ? AND j.dismissed = 0
        ORDER BY js.match_score DESC
        LIMIT 20
    """, (min_score, cutoff))
    rows = await cursor.fetchall()
    jobs = []
    for row in rows:
        d = dict(row)
        if d.get("match_reasons"):
            d["match_reasons"] = json.loads(d["match_reasons"])
        jobs.append(d)

    subject = f"CareerPulse: {len(jobs)} new match{'es' if len(jobs) != 1 else ''}"

    plain = f"CareerPulse Daily Digest\n"
    plain += f"{len(jobs)} new job match{'es' if len(jobs) != 1 else ''} in the last {hours} hours\n\n"

    for j in jobs:
        score = j.get("match_score", "?")
        plain += f"[{score}/100] {j['title']} at {j['company']}\n"
        loc = j.get("location", "")
        if loc:
            plain += f"  Location: {loc}\n"
        sal_min = j.get("salary_min")
        sal_max = j.get("salary_max")
        if sal_min and sal_max:
            plain += f"  Salary: ${sal_min:,} - ${sal_max:,}\n"
        plain += f"  {j['url']}\n\n"

    html = _render_html_digest(jobs, hours)

    return {
        "subject": subject,
        "body": plain,
        "html": html,
        "job_count": len(jobs),
        "jobs": [{
            "id": j["id"],
            "title": j["title"],
            "company": j["company"],
            "location": j.get("location", ""),
            "match_score": j.get("match_score"),
            "url": j["url"],
        } for j in jobs],
    }


def _render_html_digest(jobs: list[dict], hours: int) -> str:
    count = len(jobs)
    rows = ""
    for j in jobs:
        score = j.get("match_score", "?")
        title = escape(j.get("title", ""))
        company = escape(j.get("company", ""))
        location = escape(j.get("location", ""))
        url = escape(j.get("url", ""))
        salary = ""
        if j.get("salary_min") and j.get("salary_max"):
            salary = f"${j['salary_min']:,} - ${j['salary_max']:,}"

        score_color = "#22c55e" if score >= 80 else "#eab308" if score >= 60 else "#ef4444"

        rows += f"""
        <tr style="border-bottom:1px solid #e5e7eb">
          <td style="padding:12px 8px;text-align:center">
            <span style="background:{score_color};color:#fff;padding:4px 8px;border-radius:4px;font-weight:bold">{score}</span>
          </td>
          <td style="padding:12px 8px">
            <a href="{url}" style="color:#2563eb;text-decoration:none;font-weight:600">{title}</a><br>
            <span style="color:#6b7280">{company}</span>
            {f'<br><span style="color:#9ca3af;font-size:0.875em">{location}</span>' if location else ''}
            {f'<br><span style="color:#059669;font-size:0.875em">{salary}</span>' if salary else ''}
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#1f2937">
  <h2 style="color:#2563eb;margin-bottom:4px">CareerPulse Digest</h2>
  <p style="color:#6b7280;margin-top:0">{count} new match{'es' if count != 1 else ''} in the last {hours} hours</p>
  <table style="width:100%;border-collapse:collapse">
    <thead>
      <tr style="border-bottom:2px solid #e5e7eb">
        <th style="padding:8px;text-align:center;width:60px">Score</th>
        <th style="padding:8px;text-align:left">Job</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  {f'<p style="color:#9ca3af;font-size:0.875em;margin-top:24px">Sent by CareerPulse</p>' if count else '<p style="color:#6b7280">No new matches found. Check back later!</p>'}
</body>
</html>"""


async def send_digest(db) -> bool:
    """Generate and send digest email using saved email settings."""
    from app.emailer import send_email

    settings = await db.get_email_settings()
    if not settings or not settings.get("digest_enabled"):
        return False
    if not settings.get("smtp_host") or not settings.get("to_address"):
        logger.warning("Digest enabled but SMTP host or to_address not configured")
        return False

    schedule = settings.get("digest_schedule", "daily")
    hours = 24 if schedule == "daily" else 168
    min_score = settings.get("digest_min_score", 60)

    digest = await generate_digest(db, min_score=min_score, hours=hours)
    if digest["job_count"] == 0:
        logger.info("No jobs for digest, skipping email")
        return False

    to_address = settings["to_address"]
    success = await send_email(
        settings,
        to=to_address,
        subject=digest["subject"],
        body_text=digest["body"],
        body_html=digest["html"],
    )
    if success:
        logger.info(f"Digest sent to {to_address}: {digest['job_count']} jobs")
    return success
