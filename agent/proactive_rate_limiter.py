"""Proactive (client-side) rate limiter keyed by (provider, model).

Sits before the HTTP request and blocks until the configured RPM / TPM
windows have enough tokens available.  This prevents 429 errors entirely
for providers with strict free-tier limits (e.g. Gemini free tier:
5 RPM on gemini-2.5-pro).

Config lives under ``providers.<name>.model_limits``:

    providers:
      gemini:
        model_limits:
          gemini-2.5-pro:
            rpm: 5
            tpm: 60000
          gemini-2.0-flash:
            rpm: 10
            tpm: 100000

Both ``rpm`` and ``tpm`` are optional — set whichever dimension applies.
If neither is set for a model, the limiter is a no-op for that model.
"""

import logging
import threading
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# ── Sliding-window bucket ────────────────────────────────────────────


class _ModelBucket:
    """Thread-safe sliding-window tracker for a single (provider, model) pair."""

    __slots__ = ("rpm", "tpm", "_timestamps", "_token_counts", "_lock")

    def __init__(self, rpm: int | None, tpm: int | None):
        self.rpm = rpm
        self.tpm = tpm
        self._timestamps: list[float] = []
        self._token_counts: list[int] = []
        self._lock = threading.Lock()

    def _prune(self, now: float, window: float = 60.0) -> None:
        cutoff = now - window
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.pop(0)
            self._token_counts.pop(0)

    @property
    def request_count(self) -> int:
        return len(self._timestamps)

    @property
    def token_count(self) -> int:
        return sum(self._token_counts)

    def record(self, now: float, tokens: int) -> None:
        with self._lock:
            self._timestamps.append(now)
            self._token_counts.append(tokens)
            self._prune(now)

    def wait_time(self, now: float, tokens: int) -> float:
        """Return seconds to sleep before the request can proceed.

        Returns 0.0 if the request can fire immediately.
        Caller must hold no lock — this reads snapshot data.
        """
        with self._lock:
            self._prune(now)
            delay = 0.0

            # RPM check
            if self.rpm is not None and self.request_count >= self.rpm:
                oldest = self._timestamps[0]
                needed = (oldest + 60.0) - now
                delay = max(delay, max(0.0, needed))

            # TPM check
            if self.tpm is not None and (self.token_count + tokens) > self.tpm:
                deficit = (self.token_count + tokens) - self.tpm
                freed = 0
                for ts, tc in zip(self._timestamps, self._token_counts):
                    freed += tc
                    if freed >= deficit:
                        needed = (ts + 60.0) - now
                        delay = max(delay, max(0.0, needed))
                        break

            return delay


# ── Global registry ──────────────────────────────────────────────────

_buckets: dict[tuple[str, str], _ModelBucket] = {}
_buckets_lock = threading.Lock()


def _normalize_model_key(model: str) -> str:
    """Normalize model name for bucket keying.

    Strips provider prefixes (e.g. 'google/gemini-2.5-pro' -> 'gemini-2.5-pro')
    so the same model matched regardless of how it appears in the wire name.
    """
    m = model.strip().lower()
    for prefix in ("google/", "openai/", "anthropic/", "mistral/", "meta/"):
        if m.startswith(prefix):
            m = m[len(prefix):]
    return m


def _resolve_bucket(provider: str, model: str, config: dict[str, Any]) -> _ModelBucket | None:
    """Resolve or create the bucket for (provider, model) from config."""
    norm_model = _normalize_model_key(model)
    key = (provider, norm_model)

    if key in _buckets:
        return _buckets[key]

    with _buckets_lock:
        if key in _buckets:
            return _buckets[key]

        rpm = None
        tpm = None

        providers_cfg = config.get("providers", {})
        if isinstance(providers_cfg, dict):
            provider_cfg = providers_cfg.get(provider, {})
            if isinstance(provider_cfg, dict):
                model_limits = provider_cfg.get("model_limits", {})
                if isinstance(model_limits, dict):
                    model_cfg = model_limits.get(norm_model)
                    if model_cfg is None:
                        # prefix match: longest matching key
                        best_prefix = ""
                        for mk in model_limits:
                            if norm_model.startswith(mk) and len(mk) > len(best_prefix):
                                best_prefix = mk
                        if best_prefix:
                            model_cfg = model_limits[best_prefix]

                    if isinstance(model_cfg, dict):
                        rpm_raw = model_cfg.get("rpm")
                        tpm_raw = model_cfg.get("tpm")
                        if isinstance(rpm_raw, (int, float)):
                            rpm = int(rpm_raw)
                        if isinstance(tpm_raw, (int, float)):
                            tpm = int(tpm_raw)

        bucket = _ModelBucket(rpm, tpm)
        _buckets[key] = bucket
        return bucket


# ── Public API ───────────────────────────────────────────────────────

def wait_for_rate_limit_sync(
    provider: str,
    model: str,
    config: dict[str, Any],
    estimated_tokens: int = 0,
) -> float:
    """Synchronous: block until rate limits allow the request to proceed.

    Returns the total seconds waited (0.0 if no wait was needed).
    Uses time.sleep() — safe to call from worker threads.
    """
    bucket = _resolve_bucket(provider, model, config)
    if bucket is None:
        return 0.0

    # Quick no-lock check: if both limits are None, nothing to throttle
    if bucket.rpm is None and bucket.tpm is None:
        return 0.0

    total_waited = 0.0
    max_iterations = 20

    for _ in range(max_iterations):
        now = time.monotonic()
        delay = bucket.wait_time(now, estimated_tokens)

        if delay <= 0:
            bucket.record(now, estimated_tokens)
            return total_waited

        sleep_time = min(delay, 120.0)
        if sleep_time > 0:
            logger.debug(
                "Rate limit throttle: provider=%s model=%s waiting %.1fs "
                "(rpm=%s/%s tpm=%s/%s)",
                provider,
                _normalize_model_key(model),
                sleep_time,
                bucket.request_count,
                bucket.rpm,
                bucket.token_count,
                bucket.tpm,
            )
            time.sleep(sleep_time)
            total_waited += sleep_time

    now = time.monotonic()
    bucket.record(now, estimated_tokens)
    logger.warning(
        "Rate limit throttle exhausted wait iterations for %s/%s — proceeding anyway",
        provider,
        _normalize_model_key(model),
    )
    return total_waited


async def wait_for_rate_limit_async(
    provider: str,
    model: str,
    config: dict[str, Any],
    estimated_tokens: int = 0,
) -> float:
    """Async version for contexts that have an event loop.

    Returns the total seconds waited (0.0 if no wait was needed).
    """
    import asyncio

    bucket = _resolve_bucket(provider, model, config)
    if bucket is None:
        return 0.0

    if bucket.rpm is None and bucket.tpm is None:
        return 0.0

    total_waited = 0.0
    max_iterations = 20

    for _ in range(max_iterations):
        now = time.monotonic()
        delay = bucket.wait_time(now, estimated_tokens)

        if delay <= 0:
            bucket.record(now, estimated_tokens)
            return total_waited

        sleep_time = min(delay, 120.0)
        if sleep_time > 0:
            logger.debug(
                "Rate limit throttle: provider=%s model=%s waiting %.1fs",
                provider,
                _normalize_model_key(model),
                sleep_time,
            )
            await asyncio.sleep(sleep_time)
            total_waited += sleep_time

    now = time.monotonic()
    bucket.record(now, estimated_tokens)
    logger.warning(
        "Rate limit throttle exhausted wait iterations for %s/%s",
        provider,
        _normalize_model_key(model),
    )
    return total_waited


# ── Utilities ────────────────────────────────────────────────────────

def reset_bucket(provider: str = None, model: str = None) -> None:
    """Reset tracked state for testing or manual reset."""
    keys_to_clear = []
    for key in _buckets:
        k_provider, k_model = key
        if provider is not None and k_provider != provider:
            continue
        if model is not None and _normalize_model_key(k_model) != _normalize_model_key(model):
            continue
        keys_to_clear.append(key)

    for key in keys_to_clear:
        del _buckets[key]


def get_bucket_stats(provider: str, model: str) -> dict | None:
    """Return current bucket stats for debugging."""
    key = (provider, _normalize_model_key(model))
    bucket = _buckets.get(key)
    if bucket is None:
        return None
    return {
        "request_count": bucket.request_count,
        "token_count": bucket.token_count,
        "rpm_limit": bucket.rpm,
        "tpm_limit": bucket.tpm,
    }
