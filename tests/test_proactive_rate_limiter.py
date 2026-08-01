"""Tests for agent/proactive_rate_limiter.py"""

import time
import unittest
from unittest.mock import patch

from agent.proactive_rate_limiter import (
    _ModelBucket,
    _normalize_model_key,
    get_bucket_stats,
    reset_bucket,
    wait_for_rate_limit_sync,
)


class TestModelBucket(unittest.TestCase):
    def test_no_limits_means_no_wait(self):
        bucket = _ModelBucket(rpm=None, tpm=None)
        now = time.monotonic()
        self.assertEqual(bucket.wait_time(now, 1000), 0.0)

    def test_rpm_wait(self):
        now = time.monotonic()
        bucket = _ModelBucket(rpm=2, tpm=None)
        # First two requests should be fine
        self.assertEqual(bucket.wait_time(now, 0), 0.0)
        bucket.record(now, 100)
        self.assertEqual(bucket.wait_time(now, 0), 0.0)
        bucket.record(now, 100)
        # Third request should wait ~60s
        delay = bucket.wait_time(now, 0)
        self.assertGreater(delay, 55.0)
        self.assertLessEqual(delay, 60.0)

    def test_tpm_wait(self):
        now = time.monotonic()
        bucket = _ModelBucket(rpm=None, tpm=500)
        bucket.record(now, 300)
        bucket.record(now, 250)
        # Total is 550, limit is 500. Need to wait for oldest (300) to expire.
        delay = bucket.wait_time(now, 0)
        self.assertGreater(delay, 55.0)

    def test_tpm_with_request_tokens(self):
        now = time.monotonic()
        bucket = _ModelBucket(rpm=None, tpm=1000)
        bucket.record(now, 600)
        # New request of 500 tokens would exceed 1000 limit (600+500=1100)
        delay = bucket.wait_time(now, 500)
        self.assertGreater(delay, 0)
        # New request of 400 tokens fits (600+400=1000)
        delay = bucket.wait_time(now, 400)
        self.assertEqual(delay, 0.0)

    def test_prune_old_entries(self):
        now = time.monotonic()
        bucket = _ModelBucket(rpm=10, tpm=None)
        # Record a request 70s ago
        bucket.record(now - 70, 100)
        bucket._prune(now)
        self.assertEqual(bucket.request_count, 0)


class TestNormalizeModelKey(unittest.TestCase):
    def test_strips_google_prefix(self):
        self.assertEqual(_normalize_model_key("google/gemini-2.5-pro"), "gemini-2.5-pro")

    def test_lowercases(self):
        self.assertEqual(_normalize_model_key("Gemini-2.5-Pro"), "gemini-2.5-pro")

    def test_no_prefix_unchanged(self):
        self.assertEqual(_normalize_model_key("gemini-2.0-flash"), "gemini-2.0-flash")

    def test_strips_openai_prefix(self):
        self.assertEqual(_normalize_model_key("openai/gpt-4o"), "gpt-4o")


class TestWaitForRateLimitSync(unittest.TestCase):
    def setUp(self):
        reset_bucket()

    def test_no_config_means_no_wait(self):
        waited = wait_for_rate_limit_sync(
            provider="gemini",
            model="gemini-2.5-pro",
            config={},
            estimated_tokens=1000,
        )
        self.assertEqual(waited, 0.0)

    def test_rpm_throttling(self):
        reset_bucket()
        config = {
            "providers": {
                "gemini": {
                    "model_limits": {
                        "gemini-2.5-pro": {
                            "rpm": 2,
                        }
                    }
                }
            }
        }
        # First two calls should pass immediately
        self.assertAlmostEqual(wait_for_rate_limit_sync("gemini", "gemini-2.5-pro", config, 100), 0.0, places=1)
        self.assertAlmostEqual(wait_for_rate_limit_sync("gemini", "gemini-2.5-pro", config, 100), 0.0, places=1)

    def test_different_models_independent(self):
        reset_bucket()
        config = {
            "providers": {
                "gemini": {
                    "model_limits": {
                        "gemini-2.5-pro": {"rpm": 1},
                        "gemini-2.0-flash": {"rpm": 1},
                    }
                }
            }
        }
        # Use up gemini-2.5-pro's RPM
        wait_for_rate_limit_sync("gemini", "gemini-2.5-pro", config, 100)
        # gemini-2.0-flash should still be available
        waited = wait_for_rate_limit_sync("gemini", "gemini-2.0-flash", config, 100)
        self.assertAlmostEqual(waited, 0.0, places=1)

    def test_prefix_match(self):
        reset_bucket()
        config = {
            "providers": {
                "gemini": {
                    "model_limits": {
                        "gemini-2.5": {"rpm": 100},
                    }
                }
            }
        }
        # gemini-2.5-pro should match prefix "gemini-2.5"
        waited = wait_for_rate_limit_sync("gemini", "gemini-2.5-pro", config, 100)
        self.assertEqual(waited, 0.0)

    def test_bucket_stats(self):
        reset_bucket()
        config = {
            "providers": {
                "gemini": {
                    "model_limits": {
                        "gemini-2.5-pro": {"rpm": 5, "tpm": 60000}
                    }
                }
            }
        }
        wait_for_rate_limit_sync("gemini", "gemini-2.5-pro", config, 1000)
        stats = get_bucket_stats("gemini", "gemini-2.5-pro")
        self.assertIsNotNone(stats)
        self.assertEqual(stats["request_count"], 1)
        self.assertEqual(stats["token_count"], 1000)
        self.assertEqual(stats["rpm_limit"], 5)
        self.assertEqual(stats["tpm_limit"], 60000)


if __name__ == "__main__":
    unittest.main()
