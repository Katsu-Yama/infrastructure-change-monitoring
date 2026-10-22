// GSI tiles and the overlay share Web Mercator pixel coordinates.
export function world(lon, lat, z) {
  const n = 256 * 2 ** z;
  return [(lon + 180) / 360 * n, (1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * n];
}

export function fitViewport(bbox, width = 900, height = 620, padding = 30, maxZoom = 14) {
  if (!Array.isArray(bbox) || bbox.length !== 4 || !bbox.every(Number.isFinite)) throw Error('Invalid monitoring rectangle');
  const [west, south, east, north] = bbox;
  if (west >= east || south >= north || west < -180 || east > 180 || south < -85 || north > 85)
    throw Error('Invalid monitoring rectangle');
  for (let z = maxZoom; z >= 0; z--) {
    const bounds = [world(west, south, z), world(east, north, z)];
    if (bounds[1][0] - bounds[0][0] <= width - 2 * padding && bounds[0][1] - bounds[1][1] <= height - 2 * padding) {
      const centre = [(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2];
      return { z, bounds, corner: [centre[0] - width / 2, centre[1] - height / 2] };
    }
  }
  throw Error('Monitoring rectangle cannot fit in map');
}
