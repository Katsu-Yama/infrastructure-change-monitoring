import unittest
from unittest.mock import Mock, patch

try:
    from asf_search.exceptions import ASFSearch4xxError, ASFSearch5xxError
except ImportError:
    ASFSearch4xxError = ASFSearch5xxError = None
from scripts.asf_retry import catalog_request


@unittest.skipIf(ASFSearch5xxError is None, 'requires optional Sentinel-1 dependencies')
class CatalogRetryTests(unittest.TestCase):
    @patch('scripts.asf_retry.time.sleep')
    def test_temporary_failure_retries_same_read(self, sleep):
        search = Mock(side_effect=[ASFSearch5xxError('upstream'), ['real result']])
        self.assertEqual(catalog_request(search, platform='SENTINEL-1'), ['real result'])
        self.assertEqual(search.call_count, 2)
        search.assert_called_with(platform='SENTINEL-1')
        sleep.assert_called_once_with(20)

    @patch('scripts.asf_retry.time.sleep')
    def test_persistent_failure_never_returns_empty_success(self, sleep):
        search = Mock(side_effect=ASFSearch5xxError('upstream'))
        with self.assertRaises(ASFSearch5xxError):
            catalog_request(search)
        self.assertEqual(search.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [20, 40])

    @patch('scripts.asf_retry.time.sleep')
    def test_client_error_is_not_retried(self, sleep):
        search = Mock(side_effect=ASFSearch4xxError('bad request'))
        with self.assertRaises(ASFSearch4xxError):
            catalog_request(search)
        search.assert_called_once()
        sleep.assert_not_called()
