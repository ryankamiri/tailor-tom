"""Discord webhook notifications for Celery task failures.

Uses stdlib urllib only. If DISCORD_WEBHOOK_URL is unset, no requests are made.
All embed content is truncated to Discord's documented limits so the message always sends.
"""

import json
import logging
import urllib.request
import urllib.error
from urllib.parse import urlparse
from typing import Any, Optional

from tailor_tom.config import settings

logger = logging.getLogger(__name__)

# Dedupe key prefix and TTL (30 days) for terminal-failure alerts
DISCORD_FAILED_ALERT_KEY_PREFIX = "discord:failed-alert:"
DISCORD_FAILED_ALERT_TTL_DAYS = 30
DISCORD_FAILED_ALERT_TTL_SECONDS = DISCORD_FAILED_ALERT_TTL_DAYS * 24 * 3600

# Discord embed color: red
EMBED_COLOR_ERROR = 0xFF0000

DISCORD_EMBED_TITLE_MAX = 256
DISCORD_EMBED_DESCRIPTION_MAX = 4096
DISCORD_EMBED_FIELD_NAME_MAX = 256
DISCORD_EMBED_FIELD_VALUE_MAX = 1024
DISCORD_EMBED_TOTAL_CHARS_MAX = 6000  # sum of title + description + all field names + all field values


def _truncate(s: str, max_len: int, suffix: str = "...") -> str:
    """Truncate string to max_len, appending suffix only if truncated."""
    if len(s) <= max_len:
        return s
    return s[: max_len - len(suffix)] + suffix


def _webhook_target_for_logs(url: str) -> str:
    """Redacted webhook target for logs (host + webhook id only)."""
    try:
        parsed = urlparse(url)
        host = parsed.netloc or "unknown-host"
        parts = [p for p in parsed.path.split("/") if p]
        # Expected: /api/webhooks/{id}/{token}
        webhook_id = parts[2] if len(parts) >= 4 and parts[0] == "api" and parts[1] == "webhooks" else "unknown-id"
        return f"{host}/api/webhooks/{webhook_id}/<redacted>"
    except Exception:
        return "<invalid-webhook-url>"


def _http_error_body_preview(err: urllib.error.HTTPError, max_len: int = 400) -> str:
    """Best-effort error body extraction for webhook debugging."""
    try:
        raw = err.read()
        if not raw:
            return ""
        body = raw.decode("utf-8", errors="replace")
        return _truncate(" ".join(body.split()), max_len)
    except Exception:
        return ""


def notify_terminal_failure_once(
    redis_client: Any,
    kind: str,
    entity_id: str,
    task_name: str,
    error_message: str,
    *,
    queue: Optional[str] = None,
    company_name: Optional[str] = None,
    passes_done: Optional[int] = None,
    status_source: Optional[str] = None,
    admin_url: Optional[str] = None,
) -> None:
    """Send at most one Discord alert per entity (job or conversion) for terminal failures.

    If DISCORD_WEBHOOK_URL is unset, no-op. Uses Redis SETNX with TTL (30 days) so only
    the first failure for a given ID sends; duplicate failures within TTL are skipped.
    """
    url = (settings.discord_webhook_url or "").strip()
    if not url:
        return
    webhook_target = _webhook_target_for_logs(url)
    if kind == "optimize_job":
        dedupe_key = f"{DISCORD_FAILED_ALERT_KEY_PREFIX}job:{entity_id}"
    elif kind == "docx_conversion":
        dedupe_key = f"{DISCORD_FAILED_ALERT_KEY_PREFIX}conversion:{entity_id}"
    else:
        dedupe_key = f"{DISCORD_FAILED_ALERT_KEY_PREFIX}{kind}:{entity_id}"
    try:
        created = redis_client.set(
            dedupe_key,
            "1",
            nx=True,
            ex=DISCORD_FAILED_ALERT_TTL_SECONDS,
        )
    except Exception as e:
        logger.warning("[discord_webhook] Dedupe key set failed for %s %s: %s", kind, entity_id, e)
        created = True
    if not created:
        logger.info(
            "[discord_webhook] alert_kind=%s entity_id=%s dedupe_hit=True skipping send",
            kind,
            entity_id,
        )
        return
    title = _truncate("Terminal failure", DISCORD_EMBED_TITLE_MAX)
    task_safe = _truncate(task_name, DISCORD_EMBED_FIELD_VALUE_MAX)
    err_safe = _truncate(error_message, DISCORD_EMBED_FIELD_VALUE_MAX)
    description = _truncate(f"`{task_safe}` ended in failed state.", DISCORD_EMBED_DESCRIPTION_MAX)
    fields = [
        {"name": _truncate("Kind", DISCORD_EMBED_FIELD_NAME_MAX), "value": _truncate(kind, DISCORD_EMBED_FIELD_VALUE_MAX), "inline": True},
        {"name": _truncate("ID", DISCORD_EMBED_FIELD_NAME_MAX), "value": _truncate(entity_id, DISCORD_EMBED_FIELD_VALUE_MAX), "inline": True},
        {"name": _truncate("Task", DISCORD_EMBED_FIELD_NAME_MAX), "value": task_safe, "inline": True},
        {"name": _truncate("Error", DISCORD_EMBED_FIELD_NAME_MAX), "value": err_safe, "inline": False},
    ]
    if queue:
        fields.append({"name": _truncate("Queue", DISCORD_EMBED_FIELD_NAME_MAX), "value": _truncate(queue, DISCORD_EMBED_FIELD_VALUE_MAX), "inline": True})
    if company_name:
        fields.append({"name": _truncate("Company", DISCORD_EMBED_FIELD_NAME_MAX), "value": _truncate(company_name, DISCORD_EMBED_FIELD_VALUE_MAX), "inline": True})
    if passes_done is not None:
        fields.append({"name": _truncate("Passes", DISCORD_EMBED_FIELD_NAME_MAX), "value": str(passes_done), "inline": True})
    if status_source:
        fields.append({"name": _truncate("Status source", DISCORD_EMBED_FIELD_NAME_MAX), "value": _truncate(status_source, DISCORD_EMBED_FIELD_VALUE_MAX), "inline": True})
    if admin_url:
        fields.append({
            "name": _truncate("Admin trace", DISCORD_EMBED_FIELD_NAME_MAX),
            "value": _truncate(f"[View full stack trace]({admin_url})", DISCORD_EMBED_FIELD_VALUE_MAX),
            "inline": False,
        })
    embed = {
        "title": title,
        "description": description,
        "color": EMBED_COLOR_ERROR,
        "fields": fields,
    }
    total_chars = len(embed["title"]) + len(embed["description"]) + sum(len(f.get("name", "")) + len(f.get("value", "")) for f in embed["fields"])
    if total_chars > DISCORD_EMBED_TOTAL_CHARS_MAX:
        overflow = total_chars - DISCORD_EMBED_TOTAL_CHARS_MAX
        new_err_len = max(50, len(err_safe) - overflow)
        embed["fields"][3]["value"] = _truncate(error_message, new_err_len)
    payload = {"embeds": [embed]}
    body = json.dumps(payload).encode("utf-8")
    logger.info(
        "[discord_webhook] terminal_alert_attempt kind=%s entity_id=%s target=%s payload_bytes=%s",
        kind,
        entity_id,
        webhook_target,
        len(body),
    )
    try:
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "TailorTom-Worker-Webhook/1.0 (+https://tailortom.org)",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status not in (200, 204):
                logger.warning("[discord_webhook] Unexpected status %s from Discord webhook", resp.status)
        logger.info(
            "[discord_webhook] alert_kind=%s entity_id=%s dedupe_hit=False send_success=True",
            kind,
            entity_id,
        )
    except urllib.error.HTTPError as e:
        body_preview = _http_error_body_preview(e)
        if e.code in (401, 403):
            logger.warning(
                "[discord_webhook] Discord webhook returned %s (check URL/token); alert not sent. target=%s reason=%s body=%s",
                e.code,
                webhook_target,
                getattr(e, "reason", ""),
                body_preview or "<empty>",
            )
        else:
            logger.exception("[discord_webhook] Failed to send terminal failure notification")
        logger.info(
            "[discord_webhook] alert_kind=%s entity_id=%s dedupe_hit=False send_success=False",
            kind,
            entity_id,
        )
    except Exception:
        logger.exception("[discord_webhook] Failed to send terminal failure notification")
        logger.info(
            "[discord_webhook] alert_kind=%s entity_id=%s dedupe_hit=False send_success=False",
            kind,
            entity_id,
        )


def notify_task_failure(
    task_name: str,
    task_id: str,
    exception: str,
    job_id: Optional[str] = None,
    conversion_id: Optional[str] = None,
) -> None:
    """POST a single embed to the configured Discord webhook for a task failure.

    If discord_webhook_url is unset or empty, returns without making a request.
    On any HTTP or network error, logs and does not raise.
    All text is truncated to Discord's limits so the webhook request succeeds.
    """
    url = (settings.discord_webhook_url or "").strip()
    if not url:
        return
    webhook_target = _webhook_target_for_logs(url)

    title = _truncate("Celery task failed", DISCORD_EMBED_TITLE_MAX)
    task_name_safe = _truncate(task_name, DISCORD_EMBED_FIELD_VALUE_MAX)
    task_id_safe = _truncate(task_id, DISCORD_EMBED_FIELD_VALUE_MAX)
    exc_safe = _truncate(exception, DISCORD_EMBED_FIELD_VALUE_MAX)
    description = _truncate(f"Task `{task_name_safe}` failed.", DISCORD_EMBED_DESCRIPTION_MAX)

    fields = [
        {"name": _truncate("Task", DISCORD_EMBED_FIELD_NAME_MAX), "value": task_name_safe, "inline": True},
        {"name": _truncate("Task ID", DISCORD_EMBED_FIELD_NAME_MAX), "value": task_id_safe, "inline": True},
        {"name": _truncate("Exception", DISCORD_EMBED_FIELD_NAME_MAX), "value": exc_safe, "inline": False},
    ]
    if job_id:
        fields.append({"name": _truncate("Job ID", DISCORD_EMBED_FIELD_NAME_MAX), "value": _truncate(job_id, DISCORD_EMBED_FIELD_VALUE_MAX), "inline": True})
    if conversion_id:
        fields.append({"name": _truncate("Conversion ID", DISCORD_EMBED_FIELD_NAME_MAX), "value": _truncate(conversion_id, DISCORD_EMBED_FIELD_VALUE_MAX), "inline": True})

    embed = {
        "title": title,
        "description": description,
        "color": EMBED_COLOR_ERROR,
        "fields": fields,
    }
    total_chars = len(embed["title"]) + len(embed["description"]) + sum(len(f.get("name", "")) + len(f.get("value", "")) for f in embed["fields"])
    if total_chars > DISCORD_EMBED_TOTAL_CHARS_MAX:
        overflow = total_chars - DISCORD_EMBED_TOTAL_CHARS_MAX
        new_exc_len = max(50, len(exc_safe) - overflow)
        embed["fields"][2]["value"] = _truncate(exception, new_exc_len)

    payload = {
        "embeds": [embed],
    }
    body = json.dumps(payload).encode("utf-8")
    logger.info(
        "[discord_webhook] task_failure_alert_attempt task=%s task_id=%s target=%s payload_bytes=%s",
        task_name_safe,
        task_id_safe,
        webhook_target,
        len(body),
    )

    try:
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "TailorTom-Worker-Webhook/1.0 (+https://tailortom.org)",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status not in (200, 204):
                logger.warning(
                    "[discord_webhook] Unexpected status %s from Discord webhook",
                    resp.status,
                )
    except urllib.error.HTTPError as e:
        body_preview = _http_error_body_preview(e)
        if e.code in (401, 403):
            logger.warning(
                "[discord_webhook] Discord webhook returned %s (check URL/token); task failure not reported there. target=%s reason=%s body=%s",
                e.code,
                webhook_target,
                getattr(e, "reason", ""),
                body_preview or "<empty>",
            )
        else:
            logger.exception("[discord_webhook] Failed to send task failure notification")
    except Exception:
        logger.exception("[discord_webhook] Failed to send task failure notification")
