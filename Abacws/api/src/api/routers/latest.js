const express = require('express');
const store = require('../datastore');

const router = express.Router();

function ensurePostgres(res) {
  if (store.engine !== 'postgres') {
    res.status(501).json({ error: 'Latest endpoint not supported for this engine' });
    return false;
  }
  return true;
}

router.get('/', async (req, res, next) => {
  try {
    if(!ensurePostgres(res)) return;
    const days = Math.min(Number(req.query.lookbackDays)||7, 30);
    const data = await store.fetchLatestForAllMappings(days);
    res.json(data);
  } catch(e){ next(e); }
});

module.exports = router;