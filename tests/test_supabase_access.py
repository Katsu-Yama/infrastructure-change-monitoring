import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from scripts.verify_supabase import main


class PublicAccessVerifierTests(unittest.TestCase):
    def run_verifier(self, insecure_rpc=False, exposed_private=False):
        def response(request, timeout):
            path = request.full_url.split('/rest/v1/')[1]
            if path.startswith('mikawa_reports?'):
                stream = io.BytesIO(b'[{"report_month":"2026-10-01","published":true}]')
                stream.status = 200
                return stream
            if path.startswith('rpc/'):
                self.assertEqual(json.loads(request.data), {'document': {}})
                status, code = (400, 'P0001') if insecure_rpc else (404, 'PGRST202')
            elif exposed_private and path.startswith('mikawa_interferograms?'):
                stream = io.BytesIO(b'[]'); stream.status = 200
                return stream
            else:
                status, code = 401, '42501'
            raise urllib.error.HTTPError(request.full_url, status, 'test response', {},
                io.BytesIO(json.dumps({'code': code}).encode()))
        with patch.dict(os.environ, {'SUPABASE_URL': 'https://example.supabase.co',
                'SUPABASE_PUBLISHABLE_KEY': 'sb_publishable_test'}), \
                patch('scripts.verify_supabase.urllib.request.urlopen', side_effect=response):
            main()

    def test_anonymous_denials_and_hidden_admin_function_pass(self):
        self.run_verifier()

    def test_executable_admin_function_is_not_mistaken_for_permission_denial(self):
        with self.assertRaises(RuntimeError): self.run_verifier(insecure_rpc=True)

    def test_private_table_visibility_fails_even_when_empty(self):
        with self.assertRaises(RuntimeError): self.run_verifier(exposed_private=True)
