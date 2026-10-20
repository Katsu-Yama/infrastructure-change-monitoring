"""Verify deployed anonymous REST access without inserting test records."""
import json
import os
import re
import urllib.error
import urllib.request


def main():
    url = os.environ['SUPABASE_URL'].rstrip('/')
    key = os.environ['SUPABASE_PUBLISHABLE_KEY']
    if not re.fullmatch(r'https://[a-z0-9]+\.supabase\.co', url):
        raise ValueError('Invalid Supabase URL')
    if not key.startswith('sb_publishable_'):
        raise ValueError('Use a publishable key for anonymous-access verification')
    headers = {'apikey': key, 'Content-Type': 'application/json'}

    def request(path, method='GET'):
        # Empty POST cannot satisfy the table's mandatory fields or RPC validator.
        # Even incorrectly permissive grants must not create a fixture record.
        data = (b'{"document":{}}' if path.startswith('rpc/') else b'{}') if method == 'POST' else None
        req = urllib.request.Request(url + '/rest/v1/' + path,
                                     data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    status, reports = request('mikawa_reports?select=report_month,published&limit=24')
    if status != 200 or not isinstance(reports, list) or any(not row['published'] for row in reports):
        raise RuntimeError('Published report read failed or unpublished report was exposed')
    checks = [('mikawa_reports', 'POST'), ('rpc/publish_mikawa_report', 'POST'),
              ('mikawa_interferograms?select=id&limit=1', 'GET'),
              ('mikawa_catalog?select=aoi_id&limit=1', 'GET')]
    for path, method in checks:
        status, body = request(path, method)
        # PostgREST can omit functions unavailable to anon from its API schema.
        inaccessible_rpc = path.startswith('rpc/') and status == 404 and body.get('code') == 'PGRST202'
        denied = status in (401, 403) and body.get('code') == '42501'
        if not (denied or inaccessible_rpc):
            raise RuntimeError(f'Expected permission denial: {method} {path}, got HTTP {status}')
    print(json.dumps({'published_reports': len(reports), 'anonymous_read': 'PASS',
                      'anonymous_write_and_rpc_denied': 'PASS', 'private_reads_denied': 'PASS'}))


if __name__ == '__main__':
    main()
