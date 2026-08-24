from __future__ import annotations

import unittest
from unittest.mock import patch

from src.assistant_personal.infrastructure.security.rate_limiter import (
    RateLimitExceededError,
    SlidingWindowRateLimiter,
)


class SlidingWindowRateLimiterTests(unittest.TestCase):
    def test_allows_requests_up_to_the_max_within_the_window(self) -> None:
        limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60.0)

        limiter.check("client-a")
        limiter.check("client-a")
        limiter.check("client-a")  # no debe lanzar, es la tercera de un máximo de 3

    def test_rejects_the_request_that_exceeds_the_max(self) -> None:
        limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60.0)
        limiter.check("client-a")
        limiter.check("client-a")

        with self.assertRaises(RateLimitExceededError):
            limiter.check("client-a")

    def test_tracks_each_key_independently(self) -> None:
        limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60.0)
        limiter.check("client-a")

        limiter.check("client-b")  # no debe lanzar, es una clave distinta

        with self.assertRaises(RateLimitExceededError):
            limiter.check("client-a")

    def test_old_hits_fall_out_of_the_window_and_free_up_capacity(self) -> None:
        limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=10.0)
        with patch("time.monotonic", return_value=1000.0):
            limiter.check("client-a")

        with patch("time.monotonic", return_value=1000.0), self.assertRaises(RateLimitExceededError):
            limiter.check("client-a")

        with patch("time.monotonic", return_value=1011.0):
            limiter.check("client-a")  # ya pasaron los 10s de ventana, no debe lanzar

    def test_rejects_a_non_positive_max_requests(self) -> None:
        with self.assertRaises(ValueError):
            SlidingWindowRateLimiter(max_requests=0, window_seconds=60.0)


if __name__ == "__main__":
    unittest.main()
