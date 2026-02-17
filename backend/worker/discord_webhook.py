"""Discord webhook notifications for Celery task failures.

Uses stdlib urllib only. If DISCORD_WEBHOOK_URL is unset, no requests are made.
All embed content is truncated to Discord's documented limits so the message always sends.
"""

import json
import logging
import urllib.request
import urllib.error
from typing import Optional

from tailor_tom.config import settings

logger = logging.getLogger(__name__)

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

    try:
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status not in (200, 204):
                logger.warning(
                    "[discord_webhook] Unexpected status %s from Discord webhook",
                    resp.status,
                )
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            logger.warning(
                "[discord_webhook] Discord webhook returned %s (check URL/token); task failure not reported there.",
                e.code,
            )
        else:
            logger.exception("[discord_webhook] Failed to send task failure notification")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            logger.warning(
                "[discord_webhook] Discord webhook returned %s (check URL/token); task failure not reported there.",
                e.code,
            )
        else:
            logger.exception("[discord_webhook] Failed to send task failure notification")
    except Exception:
        logger.exception("[discord_webhook] Failed to send task failure notification")
