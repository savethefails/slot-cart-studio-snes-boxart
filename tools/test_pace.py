"""ScreenScraper's limits, against a fake server. Run from tools/: python3 -m unittest test_pace"""

import io
import threading
import time
import unittest
import urllib.error
from email.message import Message
from unittest import mock

import harvest


def http_error(code, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers['Retry-After'] = str(retry_after)
    return urllib.error.HTTPError('https://api.screenscraper.fr/x', code, 'nope', headers, io.BytesIO())


class Replies:
    """A urlopen that answers from a list: bytes are a 200, an int an HTTP error code, a tuple
    (code, retry_after) an error with that header."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.times = []

    def __call__(self, url, timeout=None):
        self.times.append(time.monotonic())
        reply = self.replies.pop(0)
        if isinstance(reply, bytes):
            return io.BytesIO(reply)
        code, after = reply if isinstance(reply, tuple) else (reply, None)
        raise http_error(code, after)


class PaceTest(unittest.TestCase):
    def setUp(self):
        self.saved = harvest.PACE

    def tearDown(self):
        harvest.PACE = self.saved

    def test_requests_are_spaced_below_the_accounts_rate(self):
        pace = harvest.Pace(per_min=600)  # one every 0.1s, so 0.12s with the margin
        self.assertAlmostEqual(pace.gap, 0.12)
        start = time.monotonic()
        for _ in range(4):
            pace.wait()
        self.assertGreaterEqual(time.monotonic() - start, 3 * 0.12 - 0.01)

    def test_threads_share_one_pace(self):
        pace = harvest.Pace(per_min=600)
        stamps = []
        lock = threading.Lock()

        def go():
            pace.wait()
            with lock:
                stamps.append(time.monotonic())

        threads = [threading.Thread(target=go) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        stamps.sort()
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        self.assertTrue(all(g >= 0.12 - 0.02 for g in gaps), gaps)

    def test_the_days_allowance_is_never_overrun(self):
        pace = harvest.Pace(per_min=60000, day_left=2)
        pace.wait()
        pace.wait()
        with self.assertRaises(harvest.QuotaSpent):
            pace.wait()
        self.assertEqual(pace.used, 2)

    def test_a_429_waits_as_long_as_retry_after_says_then_carries_on(self):
        harvest.PACE = harvest.Pace(per_min=60000)
        replies = Replies((429, 1), b'{"ok": 1}')
        with mock.patch('urllib.request.urlopen', replies):
            self.assertEqual(harvest.call('jeuInfos.php', {}), {'ok': 1})
        self.assertGreaterEqual(replies.times[1] - replies.times[0], 0.95)

    def test_a_429_without_retry_after_backs_off_and_holds_every_thread(self):
        harvest.PACE = harvest.Pace(per_min=60000)
        with mock.patch('urllib.request.urlopen', Replies(429, b'img' * 100)):
            with mock.patch.object(harvest.PACE, 'hold') as hold:
                self.assertEqual(harvest.fetch('https://x/media.png'), b'img' * 100)
        hold.assert_called_once_with(30)

    def test_quota_codes_stop_the_run_without_retrying(self):
        for code in (430, 431):
            harvest.PACE = harvest.Pace(per_min=60000)
            replies = Replies(code, b'never')
            with mock.patch('urllib.request.urlopen', replies):
                with self.assertRaises(harvest.QuotaSpent):
                    harvest.fetch('https://x/media.png')
            self.assertEqual(len(replies.times), 1, code)

    def test_a_closed_or_refusing_api_stops_the_run_without_retrying(self):
        for code in (401, 403, 423, 426):
            harvest.PACE = harvest.Pace(per_min=60000)
            replies = Replies(code, b'never')
            with mock.patch('urllib.request.urlopen', replies):
                with self.assertRaises(harvest.Refused):
                    harvest.call('jeuInfos.php', {})
            self.assertEqual(len(replies.times), 1, code)

    def test_an_unknown_rom_is_an_answer(self):
        harvest.PACE = harvest.Pace(per_min=60000)
        with mock.patch('urllib.request.urlopen', Replies(404)):
            self.assertIsNone(harvest.call('jeuInfos.php', {}))

    def test_image_downloads_count_against_the_day_like_api_calls(self):
        harvest.PACE = harvest.Pace(per_min=60000, day_left=2)
        with mock.patch('urllib.request.urlopen', Replies(b'{}', b'img' * 100, b'img' * 100)):
            harvest.call('jeuInfos.php', {})
            harvest.fetch('https://x/media.png')
            with self.assertRaises(harvest.QuotaSpent):
                harvest.fetch('https://x/media.png')


if __name__ == '__main__':
    unittest.main()
