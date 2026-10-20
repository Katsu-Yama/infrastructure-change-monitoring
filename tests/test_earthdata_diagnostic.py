import contextlib
import io
import unittest
from unittest.mock import patch

try:
    import requests
    from scripts.diagnose_earthdata import DiagnosticSession, error_types
except ImportError:
    requests = None


@unittest.skipIf(requests is None, 'requires optional Sentinel-1 dependencies')
class DiagnosticTests(unittest.TestCase):
    def test_trace_excludes_query_headers_and_body(self):
        secret = 'NEVER_PRINT_THIS'
        response = requests.Response(); response.status_code = 200
        request = requests.Request('GET', 'https://cumulus.asf.alaska.edu/login?code=' + secret,
            headers={'Authorization': 'Bearer ' + secret}).prepare()
        output = io.StringIO()
        with patch.object(requests.Session, 'send', return_value=response) as send, contextlib.redirect_stdout(output):
            DiagnosticSession().send(request)
        self.assertNotIn(secret, output.getvalue())
        self.assertIn('host=cumulus.asf.alaska.edu status=200', output.getvalue())
        self.assertEqual(send.call_args.kwargs['timeout'], (10, 25))

    def test_failure_trace_never_prints_exception_text(self):
        failure = requests.ConnectionError('SECRET_IN_EXCEPTION')
        output = io.StringIO()
        request = requests.Request('GET', 'https://urs.earthdata.nasa.gov/').prepare()
        with patch.object(requests.Session, 'send', side_effect=failure), contextlib.redirect_stdout(output):
            with self.assertRaises(requests.ConnectionError):
                DiagnosticSession().send(request)
        self.assertNotIn('SECRET_IN_EXCEPTION', output.getvalue())
        self.assertIn('ConnectionError', output.getvalue())

    def test_foreign_hosts_and_write_methods_are_blocked(self):
        for method, url in [('POST', 'https://hyp3-api.asf.alaska.edu/jobs'),
                            ('GET', 'https://example.org/'), ('GET', 'http://urs.earthdata.nasa.gov/')]:
            with patch.object(requests.Session, 'send') as send:
                with self.assertRaises(ValueError):
                    DiagnosticSession().send(requests.Request(method, url).prepare())
                send.assert_not_called()

    def test_nested_errors_include_types_only(self):
        inner = TimeoutError('SECRET_TIMEOUT')
        outer = requests.ConnectionError(inner)
        self.assertEqual(error_types(outer), 'ConnectionError > TimeoutError')
