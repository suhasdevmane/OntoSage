// Migration script: transform legacy device coordinates to normalized/aligned frame
// Usage (node): import JSON, apply delta (from localStorage cache or manual), output new JSON
// This does NOT modify backend; it's a helper to produce updated coordinates.

/**
 * run with: node scripts/migrateDeviceCoords.js devices.json > new-devices.json
 * Options:
 *   ALIGN_DELTA="dx,dy,dz"  (translation to add)
 *   SCALE_FACTOR=1.234       (uniform scale to apply BEFORE translation)
 */
const fs = require('fs');
const path = process.argv[2];
if (!path) {
  console.error('Usage: node migrateDeviceCoords.js <devices.json>');
  process.exit(1);
}
const raw = fs.readFileSync(path,'utf8');
let devices = JSON.parse(raw);
let delta;
const scaleFactor = process.env.SCALE_FACTOR ? Number(process.env.SCALE_FACTOR) : null;
if (process.env.ALIGN_DELTA) {
  const [dx,dy,dz] = process.env.ALIGN_DELTA.split(',').map(Number);
  delta = {dx,dy,dz};
} else {
  // default: read cache file if present
  const cacheFile = 'device-alignment-cache.json';
  if (fs.existsSync(cacheFile)) {
    const c = JSON.parse(fs.readFileSync(cacheFile,'utf8'));
    if (typeof c.dx === 'number') delta = c;
  }
}
if (!delta) {
  console.error('No alignment delta available. Provide ALIGN_DELTA env or device-alignment-cache.json');
  process.exit(2);
}

devices = devices.map(d => {
  if (d.position) {
    if (scaleFactor && !Number.isNaN(scaleFactor) && scaleFactor !== 1) {
      d.position.x *= scaleFactor;
      d.position.y *= scaleFactor;
      d.position.z *= scaleFactor;
    }
    d.position.x += delta.dx;
    d.position.y += delta.dy;
    d.position.z += delta.dz;
  }
  return d;
});
process.stdout.write(JSON.stringify(devices,null,2));
