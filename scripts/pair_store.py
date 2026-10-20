"""Private, bounded Supabase persistence for clipped interferograms."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request


class PairStore:
    def __init__(self, options):
        self.url = os.environ['SUPABASE_URL'].rstrip('/')
        key = os.environ['SUPABASE_SECRET_KEY']
        if not self.url.startswith('https://') or not self.url.endswith('.supabase.co'):
            raise ValueError('Invalid Supabase URL')
        self.headers = {'apikey': key}
        if not key.startswith('sb_secret_'):
            self.headers['Authorization'] = 'Bearer ' + key
        self.bucket = options['storage_bucket']
        self.limit = options['storage_limit_mb'] * 1024 ** 2
        self.rows = self.request('/rest/v1/mikawa_interferograms?select=*&limit=1000')
        self.records = {r['id']: r for r in self.rows}
        self.used = sum(r['content_bytes'] for r in self.rows)
        if len(self.rows) >= 1000:
            raise RuntimeError('Storage inventory limit reached; refusing incomplete quota calculation')

    def prune(self, active_ids, cutoff):
        obsolete = [r for r in self.rows if r['id'] not in active_ids and r['last_observed'] < cutoff]
        for record in obsolete:
            expected = 'v1/' + record['id'] + '.zip'
            if record['object_path'] != expected:
                raise RuntimeError('Unexpected retained object path; refusing deletion')
            self.request('/storage/v1/object/' + self.bucket,
                         {'prefixes': [expected]}, method='DELETE')
            self.request('/rest/v1/mikawa_interferograms?id=eq.' + record['id'], method='DELETE')
            self.used -= record['content_bytes']
            self.records.pop(record['id'], None)

    def request(self, path, data=None, method='GET', extra=None, binary=False):
        headers = {**self.headers, **(extra or {})}
        if data is not None and not isinstance(data, bytes):
            data = json.dumps(data).encode()
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=90) as response:
            result = response.read(6 * 1024 ** 2)
        return result if binary else json.loads(result) if result else None

    def ensure_bucket(self):
        try:
            bucket = self.request('/storage/v1/bucket/' + self.bucket)
        except urllib.error.HTTPError as error:
            if error.code not in (400, 404):
                raise
            bucket = self.request('/storage/v1/bucket', {
                'id': self.bucket, 'name': self.bucket, 'public': False,
                'file_size_limit': 5242880, 'allowed_mime_types': ['application/zip']}, method='POST')
        if bucket.get('public'):
            raise RuntimeError('Interferogram bucket must be private')

    def has(self, pair_id):
        return pair_id in self.records

    def get(self, pair_id):
        record = self.records[pair_id]
        path = urllib.parse.quote(record['object_path'], safe='/')
        return self.request('/storage/v1/object/authenticated/' + self.bucket + '/' + path, binary=True)

    def put(self, pair, stack, archive):
        if len(archive) >= 5 * 1024 ** 2:
            raise RuntimeError('Clipped interferogram exceeds the 5MiB cap')
        if self.used + len(archive) > self.limit:
            raise RuntimeError('Free-storage budget exhausted; no paid storage will be used')
        object_path = 'v1/' + pair['id'] + '.zip'
        self.request('/storage/v1/object/' + self.bucket + '/' + object_path,
            archive, method='POST', extra={'Content-Type': 'application/zip', 'x-upsert': 'true'})
        record = {'id': pair['id'], 'first_observed': pair['first_date'],
                  'last_observed': pair['second_date'], 'burst_id': stack['burst_id'],
                  'direction': stack['direction'], 'content_bytes': len(archive),
                  'object_path': object_path, 'metadata': pair}
        self.request('/rest/v1/mikawa_interferograms?on_conflict=id', record,
            method='POST', extra={'Prefer': 'resolution=merge-duplicates,return=minimal'})
        self.records[pair['id']] = record
        self.used += len(archive)
