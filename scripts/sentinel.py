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


def connected_components(records, pairs):
    graph = {r['date']: set() for r in records}
    for pair in pairs:
        graph[pair['first_date']].add(pair['second_date'])
        graph[pair['second_date']].add(pair['first_date'])
    remaining = set(graph)
    components = []
    while remaining:
        pending = [min(remaining)]
        seen = set()
        while pending:
            date = pending.pop()
            if date not in seen:
                seen.add(date)
                pending.extend(graph[date] - seen)
        remaining -= seen
        components.append(seen)
    return components


def build_network(records, options):
    """Prefer short pairs; add bounded cross-component links when necessary.

    Bridge pairs face the same phase/coherence masks as every other pair. Keep
    their limits and any excluded dates in provenance, never join independent
    temporal reference frames as if they were one measured time series.
    """
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
    components = connected_components(records, pairs)
    component_of = {date: i for i, dates in enumerate(components) for date in dates}
    bridge_days = options.get('max_bridge_temporal_days', options['max_temporal_baseline_days'])
    bridge_baseline = options.get('max_bridge_perpendicular_m', options['max_perpendicular_baseline_m'])
    # Retain redundant cross-component links, enabling closure checks instead of
    # relying on a single untestable edge across a missing-acquisition interval.
    for i, first in enumerate(records):
        for second in records[i + 1:]:
            days = (dt.date.fromisoformat(second['date']) - dt.date.fromisoformat(first['date'])).days
            if days > bridge_days:
                break
            if component_of[first['date']] == component_of[second['date']]:
                continue
            bperp = abs(second['perpendicular_baseline_m'] - first['perpendicular_baseline_m'])
            if 0 < days and bperp <= bridge_baseline:
                pairs.append({'id': pair_id(first['name'], second['name']),
                    'first': first['name'], 'second': second['name'],
                    'first_date': first['date'], 'second_date': second['date'],
                    'days': days, 'perpendicular_baseline_m': round(bperp, 2), 'bridge': True})
    components = connected_components(records, pairs)
    latest = records[-1]['date']
    keep = next(c for c in components if latest in c)
    excluded = [r['date'] for r in records if r['date'] not in keep]
    records = [r for r in records if r['date'] in keep]
    pairs = [p for p in pairs if p['first_date'] in keep and p['second_date'] in keep]
    network = {'connected': True, 'bridge_pair_count': sum(bool(p.get('bridge')) for p in pairs),
        'max_bridge_temporal_days': bridge_days, 'max_bridge_perpendicular_m': bridge_baseline,
        'excluded_disconnected_dates': excluded}
    return records, pairs, network


def screen_stack(stack, rejected_ids, min_observations=12, min_span_days=365):
    """Exclude wholly incoherent pairs without inventing temporal links."""
    pairs = [p for p in stack['pairs'] if p['id'] not in rejected_ids]
    used = {p[k] for p in pairs for k in ('first_date', 'second_date')}
    records = [r for r in stack['scenes'] if r['date'] in used]
    latest = stack['scenes'][-1]['date']
    if latest not in used:
        raise RuntimeError('Latest observation has no coherent temporal link; refusing a falsely current report')
    keep = next(c for c in connected_components(records, pairs) if latest in c)
    records = [r for r in records if r['date'] in keep]
    pairs = [p for p in pairs if p['first_date'] in keep and p['second_date'] in keep]
    span = (dt.date.fromisoformat(records[-1]['date']) - dt.date.fromisoformat(records[0]['date'])).days
    if len(records) < min_observations or span < min_span_days:
        raise RuntimeError('Coherent network has insufficient connected history after quality screening')
    network = {**stack.get('network', {}), 'connected': True,
        'bridge_pair_count': sum(bool(p.get('bridge')) for p in pairs),
        'excluded_disconnected_dates': sorted(set(stack.get('network', {}).get('excluded_disconnected_dates', [])) |
            {r['date'] for r in stack['scenes'] if r['date'] not in keep}),
        'quality_excluded_pairs': [{'first_date': p['first_date'], 'second_date': p['second_date'],
            'reason': 'no_coherent_land_reference'} for p in stack['pairs'] if p['id'] in rejected_ids]}
    return {**stack, 'scenes': records, 'pairs': pairs, 'network': network}


def prepare(aoi, options):
    import asf_search as asf
    from shapely.geometry import box, shape

    area = box(*aoi['bbox'])
    # HyP3 checks restituted/precise orbit availability itself. A fixed delay
    # silently excluded recent processable acquisitions from the monthly report.
    end = dt.datetime.now(dt.timezone.utc)
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
        if not records:
            raise RuntimeError('No observations with usable orbit baselines')
        records, pairs, network = build_network(records, options)
        span = (dt.date.fromisoformat(records[-1]['date']) - dt.date.fromisoformat(records[0]['date'])).days
        if len(records) < aoi['min_observations'] or span < 365:
            raise RuntimeError(f'{direction}: connected latest observations do not cover a year with sufficient samples')
        stacks.append({'burst_id': key[0], 'direction': direction.lower(), 'scenes': records,
                       'pairs': pairs, 'network': network})
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
