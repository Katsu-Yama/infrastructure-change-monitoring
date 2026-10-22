import datetime as dt
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image
from scripts.collect import Client, DownloadError, decode_png, grid, pixel
from scripts.analyze import analyze, fit_series

CONFIG = json.loads(Path('config/mikawa.json').read_text(encoding='utf-8'))


class PipelineTests(unittest.TestCase):
    def test_png_sign_units_nodata_and_alpha(self):
        image = Image.new('RGBA', (256, 256), (128, 0, 0, 255))
        image.putpixel((0, 0), (0, 0, 100, 255))  # -1mm
        image.putpixel((1, 0), (255, 255, 156, 255))  # +1mm
        image.putpixel((2, 0), (0, 0, 0, 255))  # genuine zero
        image.putpixel((3, 0), (0, 0, 0, 0))  # transparent missing
        stream = io.BytesIO(); image.save(stream, format='PNG')
        values = decode_png(stream.getvalue())
        self.assertEqual(list(values[0, :3]), [-1, 1, 0])
        self.assertTrue(np.isnan(values[0, 3]))
        self.assertTrue(np.isnan(values[1, 0]))

    def test_grid_area_and_coordinates(self):
        points = grid(CONFIG)
        self.assertGreater(len(points), 400)
        west, south, east, north = CONFIG['bbox']
        self.assertTrue(all(west < p['lon'] < east and south < p['lat'] < north for p in points))
        self.assertEqual(pixel(0, 0, 0), (128, 128))

    def test_long_term_fit_handles_outlier_and_missing(self):
        dates = [(dt.date(2020, 1, 1) + dt.timedelta(days=180 * i)).isoformat() for i in range(15)]
        values = [-8 * (dt.date.fromisoformat(d) - dt.date(2020, 1, 1)).days / 365.25 for d in dates]
        values[4] = 150; values[8] = None
        fit = fit_series(dates, values, CONFIG)
        self.assertAlmostEqual(fit['velocity_mm_year'], -8, places=2)
        self.assertTrue(fit['potential'])
        self.assertEqual(fit['observations'], 14)

    def test_missing_is_not_stable(self):
        self.assertEqual(fit_series(['2020-01-01'] * 15, [None] * 15, CONFIG)['quality'], 'insufficient')

    def test_spatial_and_age_gates(self):
        points = [{'id': f'{r}-{c}', 'row': r, 'col': c, 'lon': 137.3, 'lat': 34.73} for r in range(3) for c in range(3)]
        dates = [f'{year}-01-01' for year in range(2010, 2026)]
        values = [[-8 * i for i in range(len(dates))] for _ in points]
        sources = [{'id': 'test', 'dates': dates, 'values': values, 'direction': 'descending', 'resolution_m': 90}]
        result = analyze(points, sources, CONFIG, dt.date(2026, 10, 20))
        self.assertEqual(result['summary']['candidate_count'], 1)
        self.assertTrue(result['stale'])
        self.assertFalse(result['operational_monthly_insar'])
        self.assertGreaterEqual(result['area_km2'], 18.8)
        self.assertLessEqual(result['area_km2'], 19.1)
        self.assertTrue(all(p['stale'] for p in result['points']))

    def test_single_isolated_pixel_is_not_candidate(self):
        points = [{'id': '1', 'row': 0, 'col': 0, 'lon': 137.3, 'lat': 34.73}]
        sources = [{'id': 'test', 'dates': [f'{y}-01-01' for y in range(2010, 2026)],
                    'values': [[-8 * i for i in range(16)]], 'direction': 'descending', 'resolution_m': 90}]
        result = analyze(points, sources, CONFIG, dt.date(2026, 10, 20))
        self.assertEqual(result['summary']['candidate_count'], 0)
        self.assertEqual(result['points'][0]['status'], 'watch')

    def test_unexpected_network_host_rejected(self):
        client = Client(cache=Path('.cache/test'))
        with self.assertRaises(DownloadError):
            client.get('http://127.0.0.1/metadata')
        with self.assertRaises(DownloadError):
            client.get('https://example.com/tile.png')


if __name__ == '__main__':
    unittest.main()
