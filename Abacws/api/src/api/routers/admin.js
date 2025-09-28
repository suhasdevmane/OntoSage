const express = require('express');
const { API_KEY, COORDS_NORMALIZED, DB_ENGINE } = require('../constants');
const storeModule = require('../datastore');

// We keep a mutable flag representing whether datastore operations are allowed when engine is not 'disabled'.
let forcedDisabled = false;

function requireApiKey(req, res, next) {
  const key = req.headers['x-api-key'] || req.query.api_key;
  if (!key || key !== API_KEY) return res.status(401).json({ error: 'Unauthorized' });
  next();
}

const router = express.Router();

router.get('/db/status', (req, res) => {
  res.json({ engine: storeModule.engine, forcedDisabled, coords_normalized: !!COORDS_NORMALIZED });
});

router.post('/db/disable', requireApiKey, (req, res) => {
  forcedDisabled = true;
  res.status(200).json({ disabled: true });
});

router.post('/db/enable', requireApiKey, (req, res) => {
  forcedDisabled = false;
  res.status(200).json({ disabled: false });
});

// Coordinate normalization migration (legacy -> baked-in) dry run or execute
// POST /api/admin/migrate/coords?dryRun=true
router.post('/migrate/coords', requireApiKey, async (req,res) => {
  if(DB_ENGINE !== 'postgres') return res.status(501).json({ error: 'Only supported in postgres mode' });
  if(COORDS_NORMALIZED) return res.status(409).json({ error: 'Already normalized (set COORDS_NORMALIZED=false to re-run manually)' });
  const dryRun = String(req.query.dryRun||'false') === 'true';
  if(!storeModule.migrateLegacyCoordinates) return res.status(500).json({ error: 'Migration function unavailable' });
  const result = await storeModule.migrateLegacyCoordinates(dryRun);
  res.json({ dryRun, ...result, next: dryRun ? 'Re-run without dryRun to apply. Then set COORDS_NORMALIZED=true in environment and remove legacy offset client-side.' : 'Set COORDS_NORMALIZED=true and redeploy frontend without legacy offset.' });
});

// Export helpers for other middleware (e.g., to short-circuit writes)
module.exports = { router, isDatastoreForcedDisabled: () => forcedDisabled };