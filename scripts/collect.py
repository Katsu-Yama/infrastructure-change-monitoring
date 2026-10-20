"""Collect numeric GSI InSAR tiles, never infer displacement from colour legends.

Encoding follows GSI's public TSALoader in gsitsa_util.js: signed 24-bit,
0x800000 = nodata, value * -0.001 cm; output converted to mm.
Tile availability is not a measurement. All missing values stay null.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

ALLOWED_HOSTS = {"sarprod.gsi.go.jp", "insarmap.gsi.go.jp"}


class DownloadError(RuntimeError):
    pass


class Client:
    def __init__(self, cache=Path('.cache/gsi'), max_mb=80, max_requests=1800):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.limit = max_mb * 1024 * 1024
        self.max_requests = max_requests
        self.bytes = self.requests = 0
        self.lock = threading.Lock()

    def get(self, url, *, optional=False, fresh=False):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS:
            raise DownloadError('Unexpected data source host')
        key = self.cache / hashlib.sha256(url.encode()).hexdigest()
        if key.exists() and not fresh:
            return key.read_bytes()
        for attempt in range(3):
            with self.lock:
                self.requests += 1
                if self.requests > self.max_requests or self.bytes >= self.limit:
                    raise DownloadError('Free-operation download budget exhausted')
            request = urllib.request.Request(url, headers={'User-Agent': 'MikawaInSAR-MVP/1.0'})
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    if urllib.parse.urlparse(response.url).hostname not in ALLOWED_HOSTS:
                        raise DownloadError('Unexpected redirect host')
                    data = response.read(min(self.limit, 8 * 1024 * 1024) + 1)
                with self.lock:
                    self.bytes += len(data)
                    if self.bytes > self.limit or len(data) > 8 * 1024 * 1024:
                        raise DownloadError('Free-operation download budget exhausted')
                key.write_bytes(data)
                return data
            except urllib.error.HTTPError as error:
                if error.code == 404 and optional:
                    return None
                if error.code not in (429, 500, 502, 503, 504):
                    raise DownloadError(f'Source HTTP {error.code}: {parsed.path}') from None
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise DownloadError(f'Source unavailable: {parsed.hostname}') from None
            time.sleep(2 ** attempt)
        raise DownloadError('Source request failed after retries')

    def json(self, url, *, fresh=False):
        return json.loads(self.get(url, fresh=fresh))


def pixel(lon, lat, z):
    scale = 256 * 2 ** z
    x = (lon + 180) / 360 * scale
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * scale
    return math.floor(x), math.floor(y)


def decode_png(data):
    with Image.open(io.BytesIO(data)) as image:
        if image.size != (256, 256):
            raise DownloadError('Unexpected GSI tile dimensions')
        rgba = np.asarray(image.convert('RGBA'), dtype=np.int32)
    encoded = rgba[:, :, 0] * 65536 + rgba[:, :, 1] * 256 + rgba[:, :, 2]
    missing = (encoded == 8388608) | (rgba[:, :, 3] == 0)
    signed = np.where(encoded > 8388608, encoded - 16777216, encoded)
    values = signed.astype(float) * -0.01  # -0.001 cm => -0.01 mm
    values[missing] = np.nan
    return values


def grid(config):
    west, south, east, north = config['bbox']
    dlat = config['grid_spacing_m'] / 111320
    dlon = dlat / math.cos(math.radians((south + north) / 2))
    points = []
    row = 0
    lat = south + dlat / 2
    while lat < north:
        col = 0
        lon = west + dlon / 2
        while lon < east:
            points.append({'id': f'r{row:03d}c{col:03d}', 'lon': round(lon, 7),
                           'lat': round(lat, 7), 'row': row, 'col': col})
            col += 1
            lon += dlon
        row += 1
        lat += dlat
    return points


def leaves(obj):
    if isinstance(obj, list):
        for child in obj:
            yield from leaves(child)
    elif isinstance(obj, dict):
        if obj.get('type') == 'Layer' and '/tsa_path/' in obj.get('url', ''):
            yield obj
        for field in ('layers', 'entries'):
            yield from leaves(obj.get(field, []))


def samples(client, base, path, zoom, points):
    groups = {}
    result = [None] * len(points)
    for i, point in enumerate(points):
        x, y = pixel(point['lon'], point['lat'], zoom)
        groups.setdefault((x // 256, y // 256), []).append((i, x % 256, y % 256))

    def fetch(group):
        (x, y), indices = group
        url = f'{base}{path}/{zoom}/{x}/{y}.png'
        raw = client.get(url, optional=True)
        if raw is None:
            return []
        values = decode_png(raw)
        return [(i, float(values[py, px]) if np.isfinite(values[py, px]) else None)
                for i, px, py in indices]

    with ThreadPoolExecutor(max_workers=3) as pool:
        for rows in pool.map(fetch, groups.items()):
            for i, value in rows:
                result[i] = value
    return result


def collect(config, client):
    points = grid(config)
    # Probe all regional paths at AOI centre. Only paths with valid numeric rate
    # pixels are downloaded. A coloured browse tile is never used as data.
    candidates = []
    seen = set()
    # Port AOIs include water. A centre-only probe can reject valid land data.
    rows = max(p['row'] for p in points)
    cols = max(p['col'] for p in points)
    probe_points = [p for p in points if p['row'] in (0, rows // 2, rows)
                    and p['col'] in (0, cols // 2, cols)]
    for catalog in config['source_catalogs']:
        for layer in leaves(client.json(catalog, fresh=True)):
            if layer['id'] in seen:
                continue
            seen.add(layer['id'])
            base = layer['url'].split('{z}')[0]
            info = client.json(base + 'sartile_info.txt', fresh=True)
            if info.get('Type') != 'TSA' or info.get('TsUnit') != 'cm':
                raise DownloadError('GSI time series format or unit changed')
            if not info.get('Rate') or not info.get('TimeSeries'):
                continue
            probe = samples(client, base, info['Rate'], int(info['Zoom']), probe_points)
            if any(v is not None for v in probe):
                direction = 'descending' if '_dr_' in layer['url'].lower() or 'DR_' in layer['title'] else 'ascending'
                candidates.append((layer, base, info, direction))
    candidates.sort(key=lambda x: (x[2]['TimeSeries'][-1][0], len(x[2]['TimeSeries'])), reverse=True)
    sources = []
    for direction in ('descending', 'ascending'):
        chosen = [row for row in candidates if row[3] == direction][:config['max_sources_per_direction']]
        for layer, base, info, _ in chosen:
            dates = []
            series = []
            for ymd, path in sorted(info['TimeSeries']):
                dates.append(f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}')
                series.append(samples(client, base, path, int(info['Zoom']), points))
            sources.append({'id': layer['id'], 'name': layer['title'], 'direction': direction,
                            'kind': 'gsi_published_insar', 'resolution_m': 90,
                            'component': 'los_toward_satellite_positive', 'unit': 'mm',
                            'metadata_url': base + 'sartile_info.txt', 'dates': dates,
                            'values': np.asarray(series, dtype=object).T.tolist(),
                            'credit': '解析：国土地理院 原初データ所有：JAXA'})
    if not sources:
        raise DownloadError('No numeric GSI time series covers the AOI probe points; no report published')
    return points, sources
