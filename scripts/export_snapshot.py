"""Read the latest published report before a web-only deployment.

Fail on a configured database error instead of replacing a newer report with
the old bundled baseline. Only the public read key is required.
"""
import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path


def main():
    url = os.environ['SUPABASE_URL'].rstrip('/')
    if not re.fullmatch(r'https://[a-z0-9]+\.supabase\.co', url):
        raise ValueError('Invalid Supabase URL')
    key = os.environ['SUPABASE_PUBLISHABLE_KEY']
    headers = {'apikey': key}
    if not key.startswith('sb_publishable_'):
        headers['Authorization'] = 'Bearer ' + key
    query = '/rest/v1/mikawa_reports?select=payload&published=eq.true&order=report_month.desc&limit=1'
    with urllib.request.urlopen(urllib.request.Request(url + query, headers=headers), timeout=60) as response:
        rows = json.load(response)
    if not rows:
        print('No published database report yet; using explicitly labelled historical baseline')
        return
    report = rows[0]['payload']
    if report.get('schema_version') != 1 or report.get('aoi', {}).get('id') != 'mikawa-jinno' or not report.get('points'):
        raise RuntimeError('Invalid database snapshot; previous deployment is preserved')
    output = Path('output'); output.mkdir(exist_ok=True)
    content = json.dumps(report, ensure_ascii=False, allow_nan=False).encode('utf-8')
    (output / 'report.json').write_bytes(content)
    (output / 'published.json').write_text(json.dumps({
        'payload_digest': hashlib.sha256(content).hexdigest()}), encoding='utf-8')
    print('Bundled published database report ' + report['report_month'])


if __name__ == '__main__':
    main()
