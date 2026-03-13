import re
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import aiosmtplib

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def extract_emails_from_text(text: str) -> list[str]:
    return list(set(EMAIL_PATTERN.findall(text)))


def draft_application_email(
    to: Optional[str],
    company: str,
    position: str,
    cover_letter: str,
    sender_name: str,
    sender_email: str,
) -> Optional[dict]:
    if not to:
        return None
    return {
        "to": to,
        "subject": f"Application: {position} at {company} - {sender_name}",
        "body": f"{cover_letter}\n\nBest regards,\n{sender_name}\n{sender_email}",
    }


async def find_contact_emails(domain: str) -> list[str]:
    import httpx

    common_paths = ["/careers", "/jobs", "/contact", "/about"]
    found = []
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            for path in common_paths:
                try:
                    resp = await client.get(f"https://{domain}{path}")
                    if resp.status_code == 200:
                        found.extend(extract_emails_from_text(resp.text))
                except Exception:
                    continue
    except Exception as e:
        logger.error(f"Contact email search failed for {domain}: {e}")
    return list(set(found))


async def send_email(
    smtp_settings: dict,
    to: str | list[str],
    subject: str,
    body_text: str,
    body_html: str | None = None,
) -> bool:
    if isinstance(to, str):
        to = [to]

    from_addr = smtp_settings.get("from_address", "")

    msg = MIMEMultipart("alternative")
    msg["From"] = from_addr
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject

    msg.attach(MIMEText(body_text, "plain"))
    if body_html:
        msg.attach(MIMEText(body_html, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=smtp_settings["smtp_host"],
            port=smtp_settings.get("smtp_port", 587),
            username=smtp_settings.get("smtp_username", ""),
            password=smtp_settings.get("smtp_password", ""),
            use_tls=smtp_settings.get("smtp_use_tls", True),
            recipients=to,
        )
        logger.info(f"Email sent to {to}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to}: {e}")
        return False


async def send_application_email(smtp_settings: dict, email_draft: dict) -> bool:
    return await send_email(
        smtp_settings,
        to=email_draft["to"],
        subject=email_draft["subject"],
        body_text=email_draft["body"],
    )
