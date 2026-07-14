// Karnataka's approximate bounding box, used to project real district
// lat/lon coordinates onto the dashboard's 0-100 SVG viewBox. This keeps
// the existing hotspot map visual (a 100x100 relative-position field)
// while driving marker placement from real backend data instead of the
// hand-picked mock x/y values that used to live in the frontend.
const LAT_MIN = 11.5;
const LAT_MAX = 18.6;
const LON_MIN = 74.0;
const LON_MAX = 78.6;

export function latLonToXY(lat, lon) {
  const x = ((lon - LON_MIN) / (LON_MAX - LON_MIN)) * 100;
  const y = 100 - ((lat - LAT_MIN) / (LAT_MAX - LAT_MIN)) * 100;
  return {
    x: Math.min(96, Math.max(4, x)),
    y: Math.min(96, Math.max(4, y)),
  };
}
