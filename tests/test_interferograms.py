import importlib.util
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
from scripts.clip_pair import SUFFIXES, clip_archive, unpack_clipped
from scripts.assets import contains
from scripts.sentinel import pair_id


class AssetAndManifestTests(unittest.TestCase):
    def test_polygon_holes_and_multipolygons(self):
        geometry = {'type': 'Polygon', 'coordinates': [
            [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
            [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]]}
        self.assertTrue(contains(geometry, {'lon': .5, 'lat': .5}))
        self.assertFalse(contains(geometry, {'lon': 1.5, 'lat': 1.5}))
        self.assertFalse(contains(geometry, {'lon': 5, 'lat': 5}))

    def test_pair_ids_are_ordered_and_stable(self):
        self.assertEqual(pair_id('first', 'second'), pair_id('first', 'second'))
        self.assertNotEqual(pair_id('first', 'second'), pair_id('second', 'first'))
        self.assertEqual(len(pair_id('first', 'second')), 32)

    def test_zip_path_traversal_is_rejected(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive: archive.writestr('../bad.tif', b'not a raster')
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(RuntimeError): unpack_clipped(stream.getvalue(), Path(temp) / 'data')


@unittest.skipUnless(importlib.util.find_spec('rasterio'), 'requires requirements-insar.txt')
class InterferogramTests(unittest.TestCase):
    def test_clip_preserves_georeference_and_required_bands(self):
        import rasterio
        from rasterio.io import MemoryFile
        from rasterio.transform import from_origin
        from rasterio.warp import transform_bounds
        bbox = [137.295, 34.725, 137.3, 34.73]
        left, bottom, right, top = transform_bounds('EPSG:4326', 'EPSG:32653', *bbox)
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / 'source.zip'
            with zipfile.ZipFile(raw, 'w') as archive:
                for suffix in SUFFIXES:
                    values = np.ones((100, 100), dtype='float32')
                    with MemoryFile() as memory:
                        with memory.open(driver='GTiff', width=100, height=100, count=1,
                            crs='EPSG:32653', transform=from_origin(left - 200, top + 200, 20, 20),
                            dtype='float32') as image: image.write(values, 1)
                        archive.writestr('product/S1_TEST' + suffix, memory.read())
                archive.writestr('product/S1_TEST.txt', 'test sidecar')
            result = clip_archive(raw, bbox)
            dest = Path(temp) / 'clipped'; unpack_clipped(result, dest)
            self.assertEqual(len(list(dest.glob('*.tif'))), 7)
            with rasterio.open(dest / 'S1_TEST_corr_clipped.tif') as image:
                self.assertEqual(image.crs.to_epsg(), 32653)
                self.assertLess(image.width, 100)
                self.assertEqual(image.transform.a, 20)
                self.assertTrue(np.all(image.read(1) == 1))


if __name__ == '__main__': unittest.main()
