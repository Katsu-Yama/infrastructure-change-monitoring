"""Associate observations with user-supplied polygons, without inventing facilities."""
import json
from pathlib import Path


def inside_ring(lon, lat, ring):
    inside = False
    j = len(ring) - 1
    for i, (x, y) in enumerate(ring):
        x2, y2 = ring[j]
        if (y > lat) != (y2 > lat) and lon < (x2 - x) * (lat - y) / (y2 - y) + x:
            inside = not inside
        j = i
    return inside


def contains(geometry, point):
    polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
    return any(inside_ring(point['lon'], point['lat'], polygon[0])
               and not any(inside_ring(point['lon'], point['lat'], hole) for hole in polygon[1:])
               for polygon in polygons)


def associate(report, config):
    path = Path(config['asset_registry'])
    collection = json.loads(path.read_text(encoding='utf-8'))
    assets = collection['features']
    for feature in assets:
        props = feature['properties']
        if not all(props.get(key) for key in ('id', 'name', 'asset_type')) or props['asset_type'] not in config['asset_types']:
            raise ValueError('Asset registry needs id, name and one of the four supported asset types')
        if feature['geometry']['type'] not in ('Polygon', 'MultiPolygon'):
            raise ValueError('Asset footprints must be polygons')
    for point in report['points']:
        matches = [f for f in assets if contains(f['geometry'], point)]
        point['asset_ids'] = [f['properties']['id'] for f in matches]
        point['asset_names'] = [f['properties']['name'] for f in matches]
        point['asset_match'] = 'footprint_association_only' if matches else 'unverified'
    report['assets'] = assets
    report['summary']['registered_assets'] = len(assets)
    report['summary']['verified_assets'] = sum(f['properties'].get('verified') is True for f in assets)
    return report
