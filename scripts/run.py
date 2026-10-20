"""Monthly collection -> screening -> report. Failure never replaces last good data."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from scripts.analyze import analyze
from scripts.assets import associate
from scripts.assets import associate
from scripts.collect import Client, collect, grid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config/mikawa.json')
    parser.add_argument('--output', default='output')
    parser.add_argument('--bundle-baseline', action='store_true', help='Bundle actual observations into the static preview')
    parser.add_argument('--source', choices=['gsi', 'sentinel'], default='gsi')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    client = None
    if args.source == 'sentinel':
        from scripts.process_sentinel import collect_sentinel
        config['grid_spacing_m'] = 60
        config['min_span_days'] = 365
        points = grid(config)
        sources = collect_sentinel(config, points)
    else:
        client = Client(max_mb=config['max_download_mb'], max_requests=config['max_requests'])
        points, sources = collect(config, client)
    report = analyze(points, sources, config)
    report = associate(report, config)
    if report['summary']['usable_grid_points'] < 20:
        raise RuntimeError('Too few usable observation cells; preserving the last good report')
    report = associate(report, config)
    if report['summary']['usable_grid_points'] < 20:
        raise RuntimeError('Too few usable observation cells; preserving the last good report')
    if args.source == 'sentinel':
        report['mode'] = 'sentinel1_burst_sbas_preliminary'
        report['operational_monthly_insar'] = True
        report['limitations'] = [
            'Sentinel-1 Burst InSAR（40m分解能・20m画素間隔）の暫定的なLOS評価。個別施設の損傷・安全判定ではない。',
            '共通の参照点に対する相対変位。参照点の物理的な安定性と施設台帳は未検証。',
            'DEM残差を補正し、連結成分・水面・時間コヒーレンスを検査。大気遅延は未補正で、偽の変動が残る可能性がある。',
            '現地測量・工事履歴・施設台帳と照合してから点検順序を決める。しきい値は未校正。']
    report['download'] = {'bytes': client.bytes, 'requests': client.requests} if client else {'mode': 'hyp3_basic_private_aois'}
    report['input_digest'] = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    temp = output / 'report.tmp'
    temp.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, separators=(',', ':')), encoding='utf-8')
    temp.replace(output / 'report.json')
    if args.bundle_baseline:
        Path('web/baseline.json').write_bytes((output / 'report.json').read_bytes())
    selected = set(report['candidate_ids'])
    fields = ['id', 'lat', 'lon', 'source_id', 'direction', 'velocity_mm_year', 'residual_mm', 'last_observed', 'status', 'stale', 'neighbor_support']
    with (output / 'candidates.csv').open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(p for p in report['points'] if f"{p['source_id']}:{p['id']}" in selected)
    print(json.dumps({'summary': report['summary'], 'last_observed': report['last_observed'], 'stale': report['stale'], 'download': report['download']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
