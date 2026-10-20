"""Publish one verified report to Supabase. Privileged key remains in CI only."""
import argparse
import hashlib
import json
import os
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', default='output/report.json')
    args = parser.parse_args()
    url = os.environ['SUPABASE_URL'].rstrip('/')
    key = os.environ['SUPABASE_SECRET_KEY']
    if not url.startswith('https://') or not url.endswith('.supabase.co'):
        raise ValueError('A Supabase HTTPS URL is required')
    report = json.loads(Path(args.report).read_text(encoding='utf-8'))
    if report.get('schema_version') != 1 or not report.get('points') or not report.get('input_digest'):
        raise ValueError('Invalid or empty report: refusing to publish')
    headers = {'apikey': key, 'Content-Type': 'application/json'}
    if not key.startswith('sb_secret_'):
        headers['Authorization'] = 'Bearer ' + key
    request = urllib.request.Request(url + '/rest/v1/rpc/publish_mikawa_report',
        json.dumps({'document': report}, ensure_ascii=False, allow_nan=False).encode(), headers, method='POST')
    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.load(response)
    if result.get('stored') is not True:
        raise RuntimeError('Database did not confirm publication')
    # Read after write: verify that the stored input digest matches the pipeline.
    query = url + '/rest/v1/mikawa_reports?select=input_digest,payload&report_month=eq.' + report['report_month'] + '-01'
    with urllib.request.urlopen(urllib.request.Request(query, headers=headers), timeout=30) as response:
        rows = json.load(response)
    if len(rows) != 1 or rows[0]['input_digest'] != report['input_digest'] or rows[0]['payload'] != report:
        raise RuntimeError('Database readback failed')
    digest = hashlib.sha256(Path(args.report).read_bytes()).hexdigest()
    Path('output/published.json').write_text(json.dumps({'payload_digest': digest}), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
