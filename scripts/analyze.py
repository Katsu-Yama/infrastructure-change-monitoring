"""Conservative, reproducible displacement screening; no structural safety labels."""
from __future__ import annotations

import datetime as dt
import math
import numpy as np


def fit_series(dates, values, config):
    valid = [(dt.date.fromisoformat(d), float(v)) for d, v in zip(dates, values)
             if v is not None and math.isfinite(v)]
    if len(valid) < config['min_observations']:
        return {'quality': 'insufficient', 'observations': len(valid)}
    valid.sort()
    if (valid[-1][0] - valid[0][0]).days < config['min_span_days']:
        return {'quality': 'short_span', 'observations': len(valid)}
    t = np.array([(d - valid[0][0]).days / 365.25 for d, _ in valid])
    y = np.array([v for _, v in valid])
    # Theil-Sen median of pairwise slopes is robust to individual phase outliers.
    slopes = [(y[j] - y[i]) / (t[j] - t[i]) for i in range(len(t))
              for j in range(i + 1, len(t)) if t[j] - t[i] >= 0.5]
    if not slopes:
        return {'quality': 'short_span', 'observations': len(valid)}
    velocity = float(np.median(slopes))
    intercept = float(np.median(y - velocity * t))
    residual = float(1.4826 * np.median(np.abs(y - (intercept + velocity * t))))
    slope_mad = float(1.4826 * np.median(np.abs(np.array(slopes) - velocity)))
    threshold = config['candidate_velocity_mm_year']
    potential = abs(velocity) >= threshold and abs(velocity) >= 2 * slope_mad
    quality = 'usable' if residual <= config['max_residual_mm'] else 'noisy'
    return {'quality': quality, 'observations': len(valid),
            'first_observed': valid[0][0].isoformat(), 'last_observed': valid[-1][0].isoformat(),
            'velocity_mm_year': round(velocity, 3), 'residual_mm': round(residual, 3),
            'slope_spread_mm_year': round(slope_mad, 3),
            'change_mm': round(float(y[-1] - y[0]), 3),
            'potential': bool(potential and quality == 'usable')}


def analyze(points, sources, config, report_date=None):
    today = report_date or dt.datetime.now(dt.timezone.utc).date()
    results = []
    for source in sources:
        fits = [fit_series(source['dates'], values, config) for values in source['values']]
        lookup = {(p['row'], p['col']): i for i, p in enumerate(points)}
        for i, (point, fit) in enumerate(zip(points, fits)):
            same_sign = []
            if fit.get('potential'):
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        j = lookup.get((point['row'] + dr, point['col'] + dc))
                        if j is not None and j != i and fits[j].get('potential'):
                            if fits[j]['velocity_mm_year'] * fit['velocity_mm_year'] > 0:
                                same_sign.append(points[j]['id'])
            stale = (today - dt.date.fromisoformat(fit['last_observed'])).days > config['max_observation_age_days'] if fit.get('last_observed') else True
            status = 'insufficient'
            if fit['quality'] == 'usable':
                status = 'candidate' if fit.get('potential') and len(same_sign) >= config['min_neighbor_support'] else 'watch' if fit.get('potential') else 'no_significant_trend'
            elif fit['quality'] == 'noisy':
                status = 'noisy'
            results.append({**point, **fit, 'source_id': source['id'], 'direction': source['direction'],
                            'status': status, 'stale': stale, 'neighbor_support': len(same_sign),
                            'resolution_m': source['resolution_m'], 'asset_ids': [],
                            'asset_match': 'unverified', 'series': source['values'][i]})
    # Spatial suppression: neighbouring cells from the same source are one task,
    # not independent confirmations. Retain all points in the full report.
    ranked = sorted([p for p in results if p['status'] == 'candidate'],
                    key=lambda p: abs(p['velocity_mm_year']), reverse=True)
    selected = []
    for point in ranked:
        if any(p['source_id'] == point['source_id'] and abs(p['row'] - point['row']) <= 2
               and abs(p['col'] - point['col']) <= 2 for p in selected):
            continue
        selected.append(point)
        if len(selected) >= config['max_candidates']:
            break
    west, south, east, north = config['bbox']
    area = (east - west) * (north - south) * 111.32 ** 2 * math.cos(math.radians((south + north) / 2))
    public_sources = [{k: v for k, v in s.items() if k != 'values'} for s in sources]
    last_observed = max(d for s in sources for d in s['dates'])
    return {'schema_version': 1, 'aoi': {k: config[k] for k in ('id', 'name', 'bbox', 'asset_types')},
            'area_km2': round(area, 2), 'report_month': today.strftime('%Y-%m'),
            'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'last_observed': last_observed,
            'stale': (today - dt.date.fromisoformat(last_observed)).days > config['max_observation_age_days'],
            'mode': 'published_insar_baseline', 'operational_monthly_insar': False,
            'thresholds': {k: v for k, v in config.items() if k.startswith(('min_', 'max_')) or k.startswith('candidate_')},
            'sources': public_sources, 'points': results,
            'candidate_ids': [f"{p['source_id']}:{p['id']}" for p in selected],
            'summary': {'grid_points': len(points), 'source_count': len(sources),
                        'usable_grid_points': len({p['id'] for p in results if p['quality'] == 'usable'}),
                        'usable_points': sum(p['quality'] == 'usable' for p in results),
                        'candidate_count': len(selected)},
            'limitations': [
                '現在は国土地理院の公開済みInSAR成果を利用した広域履歴評価。新規Sentinel-1の月次処理は未接続。',
                '約90mのデータは個別の橋梁取付部・護岸等を分離できない。施設台帳との照合・現地検証は未実施。',
                '衛星視線方向の変位であり、沈下量や安全性を直接判定しない。',
                '候補しきい値は未校正。水面・低品質域は欠測、ゼロ変位として扱わない。',
                '地震時変動・広域地殻変動は提供元の処理で除去されている。地震後の被害把握には使えない。']}
