"""Clip HyP3 rasters on their native grid; keep phase/coherence/components metadata."""
import io
import math
import zipfile
from pathlib import PurePosixPath


SUFFIXES = ('_unw_phase.tif', '_corr.tif', '_conncomp.tif', '_water_mask.tif',
            '_dem.tif', '_lv_theta.tif', '_lv_phi.tif')


def clip_archive(archive_path, bbox):
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds, transform

    output = io.BytesIO()
    found = set()
    with zipfile.ZipFile(archive_path) as source, zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as target:
        for name in source.namelist():
            suffix = next((suffix for suffix in SUFFIXES if name.endswith(suffix)), None)
            basename = PurePosixPath(name).name
            if suffix:
                found.add(suffix)
                with MemoryFile(source.read(name)) as memory, memory.open() as dataset:
                    left, bottom, right, top = transform_bounds('EPSG:4326', dataset.crs, *bbox)
                    window = from_bounds(left, bottom, right, top, dataset.transform)
                    # Expand a few pixels to avoid rounding away shoreline cells.
                    x = max(0, math.floor(window.col_off) - 2)
                    y = max(0, math.floor(window.row_off) - 2)
                    width = min(dataset.width - x, math.ceil(window.width) + 4)
                    height = min(dataset.height - y, math.ceil(window.height) + 4)
                    if width <= 0 or height <= 0:
                        raise RuntimeError('Interferogram does not cover the AOI')
                    window = Window(x, y, width, height)
                    data = dataset.read(window=window)
                    profile = dataset.profile.copy()
                    profile.update(width=width, height=height, transform=transform(window, dataset.transform), compress='deflate')
                    with MemoryFile() as clipped:
                        with clipped.open(**profile) as dest:
                            dest.write(data)
                            dest.update_tags(**dataset.tags())
                        target.writestr(basename.replace('.tif', '_clipped.tif'), clipped.read())
            elif basename.endswith('.txt'):
                # MintPy's HyP3 importer reads the product's sidecar parameter file.
                content = source.read(name)
                if len(content) < 1024 * 1024:
                    target.writestr(basename, content)
    if found != set(SUFFIXES):
        raise RuntimeError('Incomplete HyP3 product: missing ' + ', '.join(set(SUFFIXES) - found))
    return output.getvalue()


def unpack_clipped(archive, directory):
    # Stored archives use flat filenames only. Never extract arbitrary paths.
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        total = sum(info.file_size for info in source.infolist())
        if total > 40 * 1024 ** 2:
            raise RuntimeError('Uncompressed clipped archive exceeds cap')
        for info in source.infolist():
            if info.is_dir() or info.filename != PurePosixPath(info.filename).name:
                raise RuntimeError('Unexpected archive path')
            (directory / info.filename).write_bytes(source.read(info))
