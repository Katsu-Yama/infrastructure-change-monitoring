import io
import unittest
import urllib.error
from unittest.mock import patch

from scripts.pair_store import PairStore


class PairStoreRetryTests(unittest.TestCase):
    def setUp(self):
        self.store = object.__new__(PairStore)
        self.store.url = 'https://example.supabase.co'
        self.store.headers = {'apikey': 'test-only'}

    @patch('scripts.pair_store.time.sleep')
    @patch('scripts.pair_store.urllib.request.urlopen')
    def test_upload_retries_same_upsert_after_520(self, open_url, sleep):
        open_url.side_effect = [urllib.error.HTTPError('https://example.supabase.co', 520, '', {}, None),
                                io.BytesIO(b'{}')]
        self.assertEqual(self.store.request('/storage/v1/object/private/pair.zip', b'zip',
            method='POST', extra={'x-upsert': 'true'}), {})
        self.assertEqual(open_url.call_count, 2)
        self.assertIs(open_url.call_args_list[0].args[0], open_url.call_args_list[1].args[0])
        sleep.assert_called_once_with(2)

    @patch('scripts.pair_store.time.sleep')
    @patch('scripts.pair_store.urllib.request.urlopen')
    def test_creation_and_auth_errors_are_not_retried(self, open_url, sleep):
        for code, method in [(520, 'POST'), (403, 'GET')]:
            open_url.reset_mock()
            open_url.side_effect = urllib.error.HTTPError('https://example.supabase.co', code, '', {}, None)
            with self.assertRaises(urllib.error.HTTPError):
                self.store.request('/storage/v1/bucket', {'name': 'private'}, method=method)
            self.assertEqual(open_url.call_count, 1)
        sleep.assert_not_called()

    @patch('scripts.pair_store.time.sleep')
    @patch('scripts.pair_store.urllib.request.urlopen')
    def test_persistent_failure_has_finite_retry_budget(self, open_url, sleep):
        open_url.side_effect = urllib.error.HTTPError('https://example.supabase.co', 503, '', {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            self.store.request('/rest/v1/mikawa_interferograms')
        self.assertEqual(open_url.call_count, 4)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 5, 10])
