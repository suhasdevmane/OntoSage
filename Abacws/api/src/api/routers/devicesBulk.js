const express = require('express');
const store = require('../datastore');
const { isDatastoreForcedDisabled } = require('./admin');

// Build CSV similar to frontend logic (keep in sync if fields evolve)
function toISO(ts){ return new Date(Number(ts)).toISOString(); }
function buildCSV(payload) {
  // payload: { devices: [ { device, history: [ entries ] } ], window:{from,to} }
  const rows = [];
  const headerSet = new Set(['device','timestamp']);
  for (const d of payload.devices) {
    const device = d.device;
    for (const entry of d.history) {
      const row = { device, timestamp: toISO(entry.timestamp) };
      for (const [k,v] of Object.entries(entry)) {
        if (k === 'timestamp') continue;
        if (v && typeof v === 'object' && v.value !== undefined) {
          headerSet.add(`${k}.value`);
            row[`${k}.value`] = v.value;
          if (v.units) { headerSet.add(`${k}.units`); row[`${k}.units`] = v.units; }
        } else {
          headerSet.add(k);
          row[k] = (v && typeof v === 'object') ? JSON.stringify(v) : v;
        }
      }
      rows.push(row);
    }
  }
  const headers = Array.from(headerSet);
  const lines = [headers.join(',')];
  for (const r of rows) {
    const line = headers.map(h => {
      const val = r[h];
      if (val === undefined || val === null) return '';
      const s = String(val).replace(/"/g,'""');
      if (/[",\n]/.test(s)) return `"${s}"`;
      return s;
    }).join(',');
    lines.push(line);
  }
  return lines.join('\n');
}

const router = express.Router();

router.post('/history/bulk', async (req, res, next) => {
  try {
    if (isDatastoreForcedDisabled && isDatastoreForcedDisabled()) {
      return res.status(503).json({ error: 'Datastore disabled' });
    }
    const { devices, from, to, format='json' } = req.body || {};
    if (!Array.isArray(devices) || !devices.length) return res.status(400).json({ error: 'devices array required' });
    if (devices.length > 200) return res.status(400).json({ error: 'Too many devices (max 200)' });
    const fromTs = Number(from) || 0;
    const toTs = Number(to) || Date.now();
    if (fromTs > toTs) return res.status(400).json({ error: 'from must be <= to' });
    const span = toTs - fromTs;
    const maxSpan = 1000 * 60 * 60 * 24 * 31; // 31 days
    if (span > maxSpan) return res.status(400).json({ error: 'Range too large (max 31 days)' });
    const limitPerDevice = 20000;
    const bundle = [];
    for (const name of devices) {
      if (typeof name !== 'string') continue;
      // Use store.deviceHistory (already descending order). If large we could stream later.
      const history = await store.deviceHistory(name, fromTs, toTs, limitPerDevice);
      bundle.push({ device: name, history });
    }
    const payload = { devices: bundle, window: { from: fromTs, to: toTs } };
    if (format === 'csv') {
      const csv = buildCSV(payload);
      res.setHeader('Content-Type', 'text/csv');
      res.setHeader('Content-Disposition', 'attachment; filename="devices-history.csv"');
      return res.status(200).send(csv);
    }
    return res.status(200).json(payload);
  } catch (e) {
    return next(e);
  }
});

module.exports = router;
