import json
import unittest
from unittest.mock import patch

from worker.discord_webhook import notify_terminal_failure_once


class FakeRedis:
    def __init__(self):
        self.calls = []

    def set(self, key, value, nx=False, ex=None):
        self.calls.append({"key": key, "value": value, "nx": nx, "ex": ex})
        return True


class DiscordWebhookAlertTests(unittest.TestCase):
    def test_terminal_failure_includes_extra_fields_and_fingerprint_ttl(self):
        redis = FakeRedis()
        sent_payloads = []

        class FakeResponse:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def fake_urlopen(req, timeout):
            sent_payloads.append(json.loads(req.data.decode("utf-8")))
            return FakeResponse()

        with patch("worker.discord_webhook.settings.discord_webhook_url", "https://discord.com/api/webhooks/123/token"), \
             patch("worker.discord_webhook.urllib.request.urlopen", side_effect=fake_urlopen):
            notify_terminal_failure_once(
                redis,
                kind="optimize_job",
                entity_id="job123",
                task_name="optimize_resume_task",
                error_message="Long bullets: 1",
                extra_fields={"Pages": "1 -> 1", "Long bullets": "2 -> 1"},
                dedupe_fingerprint="abc123",
            )

        self.assertEqual(redis.calls[0]["key"], "discord:failed-alert:optimize_job:fingerprint:abc123")
        self.assertEqual(redis.calls[0]["ex"], 6 * 3600)
        fields = sent_payloads[0]["embeds"][0]["fields"]
        self.assertIn({"name": "Pages", "value": "1 -> 1", "inline": True}, fields)
        self.assertIn({"name": "Long bullets", "value": "2 -> 1", "inline": True}, fields)

    def test_terminal_failure_uses_entity_dedupe_ttl_without_fingerprint(self):
        redis = FakeRedis()

        with patch("worker.discord_webhook.settings.discord_webhook_url", ""):
            notify_terminal_failure_once(
                redis,
                kind="docx_conversion",
                entity_id="conversion123",
                task_name="convert_docx_task",
                error_message="Unicode character",
            )

        self.assertEqual(redis.calls, [])

        with patch("worker.discord_webhook.settings.discord_webhook_url", "https://discord.com/api/webhooks/123/token"), \
             patch("worker.discord_webhook.urllib.request.urlopen") as urlopen:
            class FakeResponse:
                status = 204

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            urlopen.return_value = FakeResponse()
            notify_terminal_failure_once(
                redis,
                kind="docx_conversion",
                entity_id="conversion123",
                task_name="convert_docx_task",
                error_message="Unicode character",
            )

        self.assertEqual(redis.calls[0]["key"], "discord:failed-alert:conversion:conversion123")
        self.assertEqual(redis.calls[0]["ex"], 30 * 24 * 3600)


if __name__ == "__main__":
    unittest.main()
