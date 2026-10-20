import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.export_snapshot import main


class SnapshotTests(unittest.TestCase):
    def invoke(self, rows):
        response = io.BytesIO(json.dumps(rows).encode())
        with patch.dict(os.environ, {'SUPABASE_URL': 'https://example.supabase.co',
                'SUPABASE_PUBLISHABLE_KEY': 'sb_publishable_test'}), \
                patch('scripts.export_snapshot.urllib.request.urlopen', return_value=response):
            main()

    def test_latest_snapshot_has_exact_database_provenance(self):
        report = {'schema_version': 1, 'aoi': {'id': 'mikawa-jinno'},
                  'report_month': '2026-10', 'points': [{'id': 'test'}]}
        with tempfile.TemporaryDirectory() as temporary, contextlib.chdir(temporary):
            self.invoke([{'payload': report}])
            content = Path('output/report.json').read_bytes()
            marker = json.loads(Path('output/published.json').read_text())
            self.assertEqual(json.loads(content), report)
            self.assertEqual(marker['payload_digest'], hashlib.sha256(content).hexdigest())

    def test_empty_database_does_not_invent_a_report(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.chdir(temporary):
            self.invoke([])
            self.assertFalse(Path('output/report.json').exists())

    def test_invalid_database_report_is_not_published(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.chdir(temporary):
            with self.assertRaises(RuntimeError): self.invoke([{'payload': {'points': []}}])
            self.assertFalse(Path('output/report.json').exists())
