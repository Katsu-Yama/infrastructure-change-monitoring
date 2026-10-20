"""Synthetic numerical integration check, never used as monitoring evidence."""
import datetime as dt
import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np


@unittest.skipUnless(importlib.util.find_spec('mintpy'), 'requires the scientific conda environment')
class ScientificRuntimeTests(unittest.TestCase):
    def test_mintpy_recovers_known_los_time_series(self):
        import rasterio
        from rasterio.transform import from_origin
        from rasterio.warp import transform
        from scripts.process_sentinel import align_and_reference, mintpy_source

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'data'
            directory.mkdir()
            dates = [dt.date(2024, 1, 1) + dt.timedelta(days=24 * i) for i in range(24)]
            rows, cols = np.indices((24, 24))
            # Reference velocity is zero; the target is +20 mm/year toward satellite.
            velocity = (rows + cols).astype('float32') / 1000
            wavelength = 299792458 / 5405000000
            grid = from_origin(710000, 3848000, 20, 20)
            index = 0
            for first in range(len(dates)):
                for second in range(first + 1, min(first + 3, len(dates))):
                    index += 1
                    name = f'S1_238623_IW2_{dates[first]:%Y%m%d}_{dates[second]:%Y%m%d}_VV_INT20_{index:04X}'
                    target = directory / f'pair{index:03}'
                    target.mkdir()
                    years = (dates[second] - dates[first]).days / 365.25
                    # HyP3 phase is away-positive; MintPy displacement is toward-positive.
                    phase = 3 - 4 * np.pi / wavelength * velocity * years
                    arrays = {
                        'unw_phase': phase, 'corr': np.full((24, 24), .95),
                        'conncomp': np.ones((24, 24)), 'water_mask': np.ones((24, 24)),
                        'dem': 10 + rows * .2, 'lv_theta': np.full((24, 24), .65),
                        'lv_phi': np.full((24, 24), -1.4),
                    }
                    for suffix, values in arrays.items():
                        with rasterio.open(target / f'{name}_{suffix}_clipped.tif', 'w',
                            driver='GTiff', width=24, height=24, count=1, dtype='float32',
                            crs='EPSG:32653', transform=grid, nodata=0) as image:
                            image.write(np.asarray(values, dtype='float32'), 1)
                    baseline = 50 * (np.sin(second) - np.sin(first))
                    metadata = {
                        'UTC time': 1000, 'Azimuth looks': 1, 'Range looks': 5,
                        'Earth radius at nadir': 6371000, 'Spacecraft height': 693000,
                        'Slant range near': 850000, 'Heading': -13,
                        'Unwrapping type': 'snaphu', 'Baseline': baseline,
                    }
                    (target / f'{name}.txt').write_text(
                        '\n'.join(f'{key}: {value}' for key, value in metadata.items()), encoding='utf-8')
            lon, lat = transform('EPSG:32653', 'EPSG:4326',
                [710010, 710210], [3847990, 3847790])
            options = {'reference_lat_lon': [lat[0], lon[0]],
                       'reference_verified': False, 'min_temporal_coherence': .7}
            reference = align_and_reference(directory, [], options)
            result = mintpy_source(directory, {'burst_id': 'synthetic', 'direction': 'ascending'},
                [{'lon': lon[1], 'lat': lat[1]}], options, reference)
            values = result['values'][0]
            self.assertTrue(all(value is not None for value in values))
            self.assertEqual(result['dates'], [date.isoformat() for date in dates])
            expected = .020 * (dates[-1] - dates[0]).days / 365.25 * 1000
            self.assertAlmostEqual(values[-1] - values[0], expected, delta=.2)


if __name__ == '__main__':
    unittest.main()
