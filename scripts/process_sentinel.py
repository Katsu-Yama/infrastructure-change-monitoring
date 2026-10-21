"""Fresh Sentinel-1 -> free HyP3 burst interferograms -> MintPy SBAS -> AOI series.

Requires Earthdata and Supabase secrets. No secret or full-scene SAR is public.
All remote jobs are checked by their existing ID; no restart on a poll timeout.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import subprocess
import sys
import time
import tempfile
from pathlib import Path

import numpy as np

from scripts.clip_pair import clip_archive, unpack_clipped
from scripts.pair_store import PairStore
from scripts.sentinel import JOB_NAME, prepare


def align_and_reference(directory, bbox, options):
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import reproject, Resampling, transform

    files = sorted(directory.glob('*/*_unw_phase_clipped.tif'))
    if len(files) < 12:
        raise RuntimeError('Too few interferograms for time-series analysis')
    bounds = []; crs = None
    for file in files:
        with rasterio.open(file) as image:
            if crs is not None and image.crs != crs:
                raise RuntimeError('Mixed map projections in one SBAS stack')
            crs = image.crs; bounds.append(image.bounds)
    spacing = 20
    left = math.ceil(max(b.left for b in bounds) / spacing) * spacing
    right = math.floor(min(b.right for b in bounds) / spacing) * spacing
    bottom = math.ceil(max(b.bottom for b in bounds) / spacing) * spacing
    top = math.floor(min(b.top for b in bounds) / spacing) * spacing
    width, height = int((right - left) / spacing), int((top - bottom) / spacing)
    if min(width, height) <= 0:
        raise RuntimeError('No common spatial overlap')
    transform_out = from_origin(left, top, spacing, spacing)
    for file in directory.glob('*/*_clipped.tif'):
        with rasterio.open(file) as src:
            profile = src.profile.copy(); data = src.read(1)
            profile.update(width=width, height=height, transform=transform_out, nodata=0)
            dest = np.zeros((height, width), dtype=data.dtype)
            reproject(data, dest, src_transform=src.transform, src_crs=src.crs,
                dst_transform=transform_out, dst_crs=crs, src_nodata=src.nodata,
                dst_nodata=0, resampling=Resampling.nearest)
        with rasterio.open(file, 'w', **profile) as dst:
            dst.write(dest, 1)
    minimum = np.ones((height, width), dtype=float)
    for file in files:
        for suffix in ('_corr_clipped.tif', '_water_mask_clipped.tif', '_conncomp_clipped.tif'):
            other = Path(str(file).replace('_unw_phase_clipped.tif', suffix))
            with rasterio.open(other) as src:
                values = src.read(1)
            valid = np.isfinite(values)
            if suffix.startswith('_corr'):
                values = np.where(valid & (values >= 0) & (values <= 1), values, 0)
            else:
                values = valid & (values > 0)
            minimum = np.minimum(minimum, values)
    if options.get('reference_lat_lon'):
        lat, lon = options['reference_lat_lon']
        xs, ys = transform('EPSG:4326', crs, [lon], [lat])
        col = int((xs[0] - left) / spacing); row = int((top - ys[0]) / spacing)
        if not 0 <= row < height or not 0 <= col < width:
            raise RuntimeError('Reference point is outside the common overlap')
        method = 'configured_reference'
    else:
        row, col = np.unravel_index(np.argmax(minimum), minimum.shape)
        method = 'automatic_maximum_minimum_coherence_unverified'
    if not np.isfinite(minimum[row, col]) or minimum[row, col] < 0.35:
        raise RuntimeError('No common coherent land reference point across all pairs')
    # Keep only the unwrapped component connected to the same spatial reference.
    # A separate disconnected quay is not treated as a referenced measurement.
    for file in files:
        prefix = str(file).replace('_unw_phase_clipped.tif', '')
        with rasterio.open(prefix + '_conncomp_clipped.tif') as src: components = src.read(1)
        with rasterio.open(prefix + '_water_mask_clipped.tif') as src: land = src.read(1)
        with rasterio.open(prefix + '_corr_clipped.tif') as src: coherence = src.read(1)
        label = components[row, col]
        invalid = (components != label) | (land == 0) | (coherence < 0.3) | ~np.isfinite(coherence)
        for suffix in ('_unw_phase_clipped.tif', '_corr_clipped.tif'):
            with rasterio.open(prefix + suffix, 'r+') as dst:
                data = dst.read(1); data[invalid | ~np.isfinite(data)] = 0; dst.write(data, 1)
    lon, lat = transform(crs, 'EPSG:4326', [left + (col + .5) * spacing], [top - (row + .5) * spacing])
    return {'row': int(row), 'col': int(col), 'lat': lat[0], 'lon': lon[0], 'method': method,
            'verified': bool(options.get('reference_verified')), 'crs': crs.to_string()}


def mintpy_source(directory, stack, points, options, reference):
    import h5py
    from rasterio.warp import transform

    work = directory.parent / 'mintpy'
    work.mkdir(parents=True, exist_ok=True)
    config = work / 'smallbaseline.cfg'
    fields = {'unwFile': 'unw_phase', 'corFile': 'corr', 'connCompFile': 'conncomp',
              'demFile': 'dem', 'incAngleFile': 'lv_theta', 'azAngleFile': 'lv_phi',
              'waterMaskFile': 'water_mask'}
    settings = ['mintpy.load.processor = hyp3']
    settings += [f'mintpy.load.{key} = {directory.resolve().as_posix()}/*/*_{suffix}_clipped.tif' for key, suffix in fields.items()]
    settings += [f"mintpy.reference.yx = {reference['row']},{reference['col']}",
                 'mintpy.troposphericDelay.method = no', 'mintpy.deramp = no',
                 'mintpy.topographicResidual = yes', 'mintpy.network.coherenceBased = no',
                 'mintpy.plot = no']
    config.write_text('\n'.join(settings) + '\n', encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'scripts.mintpy_entry', str(config), '--dir', str(work)],
                   check=True, timeout=3600)
    corrected = work / 'timeseries_demErr.h5'
    if not corrected.exists():
        raise RuntimeError('MintPy did not produce the DEM-error-corrected time series')
    closure_file = work / 'numTriNonzeroIntAmbiguity.h5'
    if not closure_file.exists():
        raise RuntimeError('Missing phase-closure quality diagnostic; refusing unchecked output')
    with h5py.File(closure_file) as quality:
        closure = quality['mask'][:]
    xs, ys = transform('EPSG:4326', reference['crs'], [p['lon'] for p in points], [p['lat'] for p in points])
    with h5py.File(corrected) as src, h5py.File(work / 'temporalCoherence.h5') as quality:
        unit = src.attrs.get('UNIT', 'm')
        if isinstance(unit, bytes): unit = unit.decode()
        if unit != 'm': raise RuntimeError('Unexpected MintPy displacement units')
        dates = [d.decode() if isinstance(d, bytes) else str(d) for d in src['date'][:]]
        dates = [f'{d[:4]}-{d[4:6]}-{d[6:8]}' for d in dates]
        cube = src['timeseries'][:]
        coherence = quality['temporalCoherence'][:]
        x0, y0 = float(src.attrs['X_FIRST']), float(src.attrs['Y_FIRST'])
        dx, dy = float(src.attrs['X_STEP']), float(src.attrs['Y_STEP'])
        values = []
        for x, y in zip(xs, ys):
            c = math.floor((x - x0) / dx); r = math.floor((y - y0) / dy)
            if not 0 <= r < cube.shape[1] or not 0 <= c < cube.shape[2] or not np.isfinite(coherence[r, c]) or coherence[r, c] < options['min_temporal_coherence'] or not np.isfinite(closure[r, c]) or closure[r, c] != 0:
                values.append([None] * len(dates))
            else:
                values.append([round(float(v) * 1000, 3) if np.isfinite(v) else None for v in cube[:, r, c]])
    return {'id': 's1-burst-' + stack['burst_id'], 'name': 'Sentinel-1 Burst SBAS ' + stack['burst_id'],
            'direction': stack['direction'], 'kind': 'sentinel1_burst_sbas',
            'resolution_m': 40, 'pixel_spacing_m': 20, 'unit': 'mm',
            'component': 'los_toward_satellite_positive', 'dates': dates, 'values': values,
            'reference': reference, 'metadata_url': 'https://search.asf.alaska.edu/',
            'closure_quality': 'Only pixels with zero detected integer ambiguity in available triplets',
            'network': stack.get('network', {}),
            'credit': 'Contains modified Copernicus Sentinel data; processed by ASF HyP3 / MintPy',
            'corrections': 'DEM residual corrected; atmospheric delay not corrected; preliminary'}


def collect_sentinel(aoi, points):
    import hyp3_sdk as sdk
    options = json.loads(Path('config/sentinel.json').read_text(encoding='utf-8'))
    plan = prepare(aoi, options)
    print(json.dumps({'stage': 'plan', 'pair_count': plan['pair_count'],
        'stacks': [{'direction': s['direction'], 'observations': len(s['scenes']),
                    'last_observed': max(p['date'] for p in s['scenes']),
                    'pairs': len(s['pairs'])} for s in plan['stacks']]}), flush=True)
    Path('output').mkdir(exist_ok=True)
    Path('output/sentinel-plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    store = PairStore(options); store.ensure_bucket()
    active_ids = {pair['id'] for stack in plan['stacks'] for pair in stack['pairs']}
    cutoff = (dt.date.today() - dt.timedelta(days=options['history_days'] + 45)).isoformat()
    store.prune(active_ids, cutoff)
    hyp3 = sdk.HyP3('https://hyp3-api.asf.alaska.edu', username=os.environ['EARTHDATA_USERNAME'],
                   password=os.environ['EARTHDATA_PASSWORD'])
    existing = hyp3.find_jobs(name=JOB_NAME)
    pair_jobs = {tuple(j.job_parameters.get('granules', [])): j for j in existing}
    pending = {}; submitted = 0
    for stack in plan['stacks']:
        for pair in stack['pairs']:
            if store.has(pair['id']): continue
            job = pair_jobs.get((pair['first'], pair['second']))
            # Expired jobs are only regenerated when no persisted AOI product exists.
            if job is not None and (job.status_code == 'FAILED' or job.expired()): job = None
            if job is None:
                if submitted >= options['max_new_jobs_per_run']:
                    raise RuntimeError('New-job cap reached; completed/pending job IDs are preserved at ASF. Resume this workflow.')
                batch = hyp3.submit_insar_isce_burst_job(pair['first'], pair['second'],
                    name=JOB_NAME, looks='5x1', apply_water_mask=True)
                job = batch.jobs[0]; submitted += 1
            pending[job.job_id] = (job, pair, stack)
    deadline = time.monotonic() + 3600
    while pending:
        for job_id, (_, pair, stack) in list(pending.items()):
            job = hyp3.get_job_by_id(job_id)
            if job.status_code == 'FAILED': raise RuntimeError(f'HyP3 job failed: {job_id}')
            if job.status_code != 'SUCCEEDED': continue
            scratch = Path('.cache/hyp3'); scratch.mkdir(parents=True, exist_ok=True)
            # Full products can be large. Retain only the small persisted AOI zip.
            with tempfile.TemporaryDirectory(prefix=pair['id'] + '-', dir=scratch) as temporary:
                directory = Path(temporary)
                archives = job.download_files(directory)
                archive = next((Path(p) for p in archives if str(p).endswith('.zip')), None)
                if archive is None: raise RuntimeError(f'HyP3 job has no downloadable product: {job_id}')
                if not archive.resolve().is_relative_to(directory.resolve()):
                    raise RuntimeError('Downloaded product is outside its temporary directory')
                clipped = clip_archive(archive, aoi['bbox'])
                pair['hyp3_job_id'] = job_id
                store.put(pair, stack, clipped)
            del pending[job_id]
            print(f'Persisted AOI interferogram {pair["id"]}', flush=True)
        if pending:
            if time.monotonic() >= deadline:
                raise RuntimeError('HyP3 jobs still running; resume by their existing IDs. Last good report is preserved.')
            print(f'Waiting for {len(pending)} existing HyP3 jobs', flush=True)
            time.sleep(20)
    sources = []
    for stack in plan['stacks']:
        scratch = Path('output/sentinel'); scratch.mkdir(parents=True, exist_ok=True)
        # Each solve uses only this plan, never leftover pairs or old MintPy outputs.
        with tempfile.TemporaryDirectory(prefix=stack['burst_id'] + '-', dir=scratch) as temporary:
            directory = Path(temporary) / 'data'
            for pair in stack['pairs']:
                unpack_clipped(store.get(pair['id']), directory / pair['id'])
            reference = align_and_reference(directory, aoi['bbox'], options)
            sources.append(mintpy_source(directory, stack, points, options, reference))
    return sources
