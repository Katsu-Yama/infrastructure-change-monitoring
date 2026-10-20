"""Prepare a real Sentinel-1 burst SBAS network and request free HyP3 Basic jobs.

Plan is unauthenticated/read-only. Submit requires a reviewed reference point,
Earthdata credentials, a fixed job cap, and only the HyP3 Basic endpoint.
Scientific processing uses MintPy; never annualizes an amplitude difference.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from scripts.asf_retry import catalog_request

JOB_NAME = 'mikawa-insar-burst-v1'


def pair_id(first, second):
    return hashlib.sha256((first + '\n' + second).encode()).hexdigest()[:32]


def prepare(aoi, options):
    import asf_search as asf
    from shapely.geometry import box, shape

    area = box(*aoi['bbox'])
    end = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)  # orbit availability
    start = end - dt.timedelta(days=options['history_days'])
    products = catalog_request(asf.search, platform=asf.PLATFORM.SENTINEL1,
        processingLevel=asf.PRODUCT_TYPE.BURST, beamMode=asf.BEAMMODE.IW,
        polarization=asf.POLARIZATION.VV, intersectsWith=area.wkt,
        start=start.isoformat(), end=end.isoformat(), maxResults=5000)
    if len(products) >= 5000:
        raise RuntimeError('Catalog truncated; refine AOI/time range before processing')
    groups = defaultdict(list)
    for product in products:
        p = product.properties
        if shape(product.geometry).covers(area):
            # Full burst ID identifies path + burst + swath, not acquisition ID.
            key = p.get('burst', {}).get('fullBurstID') or p.get('fullBurstID')
            if key:
                groups[(key, p['flightDirection'])].append(product)
    if not groups:
        raise RuntimeError('No single burst covers the AOI. Multi-burst processing is required.')
    # One stack per direction, ranked by temporal coverage and recency.
    stacks = []
    for direction in ('ASCENDING', 'DESCENDING'):
        candidates = [(k, v) for k, v in groups.items() if k[1] == direction]
        if not candidates:
            continue
        key, chosen = max(candidates, key=lambda item: (len(item[1]), max(p.properties['startTime'] for p in item[1])))
        # ASF computes perpendicular and temporal baselines relative to one scene.
        baseline = catalog_request(asf.baseline_search.stack_from_product, chosen[0])
        records = []
        for product in baseline:
            p = product.properties
            date = dt.datetime.fromisoformat(p['startTime'].replace('Z', '+00:00'))
            if not start <= date <= end or p.get('polarization') != 'VV':
                continue
            if not shape(product.geometry).covers(area):
                continue
            if p.get('perpendicularBaseline') is None:
                raise RuntimeError('Missing perpendicular baseline; refusing unchecked pairs')
            records.append({'name': p['sceneName'], 'date': date.date().isoformat(),
                            'perpendicular_baseline_m': float(p['perpendicularBaseline'])})
        records.sort(key=lambda p: p['date'])
        # Exact same dates cannot add an independent temporal constraint.
        records = list({r['date']: r for r in records}.values())
        pairs = []
        for i, first in enumerate(records):
            for second in records[i + 1:i + 3]:
                days = (dt.date.fromisoformat(second['date']) - dt.date.fromisoformat(first['date'])).days
                bperp = abs(second['perpendicular_baseline_m'] - first['perpendicular_baseline_m'])
                if 0 < days <= options['max_temporal_baseline_days'] and bperp <= options['max_perpendicular_baseline_m']:
                    pairs.append({'id': pair_id(first['name'], second['name']),
                                  'first': first['name'], 'second': second['name'],
                                  'first_date': first['date'], 'second_date': second['date'],
                                  'days': days, 'perpendicular_baseline_m': round(bperp, 2)})
        stacks.append({'burst_id': key[0], 'direction': direction.lower(), 'scenes': records, 'pairs': pairs})
    count = sum(len(s['pairs']) for s in stacks)
    if not count:
        raise RuntimeError('No valid SBAS pairs for the AOI')
    if count > options['max_pairs']:
        raise RuntimeError(f'{count} pairs exceed the configured free-storage cap; refine history before submission')
    return {'schema_version': 1, 'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'aoi': aoi['id'], 'bbox': aoi['bbox'], 'stacks': stacks,
            'pair_count': count, 'looks': options['looks'],
            'resolution_m': 40, 'pixel_spacing_m': 20,
            'reference_verified': options['reference_verified'],
            'requires': ['NASA Earthdata + ASF HyP3 Basic authorization',
                         'shared coherent reference (automatic or configured)', 'Supabase private storage'],
            'submitted': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['plan'])
    args = parser.parse_args()
    aoi = json.loads(Path('config/mikawa.json').read_text(encoding='utf-8'))
    options = json.loads(Path('config/sentinel.json').read_text(encoding='utf-8'))
    output = Path('output'); output.mkdir(exist_ok=True)
    if args.action == 'plan':
        result = prepare(aoi, options)
        (output / 'sentinel-plan.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: v for k, v in result.items() if k != 'stacks'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
