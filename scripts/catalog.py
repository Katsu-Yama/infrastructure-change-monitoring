"""Daily light collection of new observations; monthly phase processing is separate."""
import datetime as dt
import json
import os
import urllib.request
from pathlib import Path

from scripts.asf_retry import catalog_request


def main():
    import asf_search as asf
    from shapely.geometry import box, shape
    aoi = json.loads(Path('config/mikawa.json').read_text(encoding='utf-8'))
    area = box(*aoi['bbox'])
    now = dt.datetime.now(dt.timezone.utc)
    products = catalog_request(asf.search, platform=asf.PLATFORM.SENTINEL1, processingLevel=asf.PRODUCT_TYPE.BURST,
        beamMode=asf.BEAMMODE.IW, polarization=asf.POLARIZATION.VV, intersectsWith=area.wkt,
        start=(now - dt.timedelta(days=45)).isoformat(), end=now.isoformat(), maxResults=500)
    if len(products) >= 500: raise RuntimeError('Acquisition catalog truncated')
    scenes = []
    for product in products:
        if not shape(product.geometry).covers(area): continue
        p = product.properties
        scenes.append({'id': p['sceneName'], 'observed_at': p['startTime'], 'direction': p['flightDirection'],
                       'burst_id': p.get('burst', {}).get('fullBurstID') or p.get('fullBurstID')})
    scenes.sort(key=lambda p: p['observed_at'])
    document = {'aoi_id': aoi['id'], 'checked_at': now.isoformat(), 'payload': {
        'scenes': scenes, 'count': len(scenes), 'last_observed': scenes[-1]['observed_at'] if scenes else None}}
    url = os.environ['SUPABASE_URL'].rstrip('/')
    if not url.startswith('https://') or not url.endswith('.supabase.co'): raise ValueError('Invalid Supabase URL')
    key = os.environ['SUPABASE_SECRET_KEY']
    headers = {'apikey': key, 'Content-Type': 'application/json', 'Prefer': 'resolution=merge-duplicates,return=minimal'}
    if not key.startswith('sb_secret_'): headers['Authorization'] = 'Bearer ' + key
    request = urllib.request.Request(url + '/rest/v1/mikawa_catalog?on_conflict=aoi_id',
        json.dumps(document).encode(), headers, method='POST')
    with urllib.request.urlopen(request, timeout=60) as response: response.read()
    query = url + '/rest/v1/mikawa_catalog?aoi_id=eq.' + aoi['id'] + '&select=payload'
    with urllib.request.urlopen(urllib.request.Request(query, headers=headers), timeout=30) as response:
        stored = json.load(response)
    if not stored or stored[0]['payload'] != document['payload']: raise RuntimeError('Catalog readback failed')
    print(json.dumps({'count': len(scenes), 'last_observed': document['payload']['last_observed']}))


if __name__ == '__main__': main()
