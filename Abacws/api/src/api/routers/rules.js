const express = require('express');
const store = require('../datastore');

const router = express.Router();

function ensurePostgres(res){
  if(store.engine !== 'postgres') { res.status(501).json({ error: 'Rules not supported for this engine' }); return false; }
  return true;
}

// List all rules
router.get('/', async (_req,res,next)=>{ try { if(!ensurePostgres(res)) return; const list = await store.listRules(); res.json(list); } catch(e){ next(e); } });

// Get single rule
router.get('/:id', async (req,res,next)=>{ try { if(!ensurePostgres(res)) return; const r = await store.getRule(Number(req.params.id)); if(!r) return res.status(404).json({ error: 'Not found' }); res.json(r); } catch(e){ next(e); } });

// Create rule
router.post('/', async (req,res,next)=>{ try { if(!ensurePostgres(res)) return; const created = await store.createRule(req.body||{}); if(created.error) return res.status(400).json({ error: created.error }); res.status(201).json(created); } catch(e){ next(e); } });

// Update rule
router.patch('/:id', async (req,res,next)=>{ try { if(!ensurePostgres(res)) return; const updated = await store.updateRule(Number(req.params.id), req.body||{}); if(updated?.error) return res.status(400).json({ error: updated.error }); if(!updated) return res.status(404).json({ error: 'Not found' }); res.json(updated); } catch(e){ next(e); } });

// Delete rule
router.delete('/:id', async (req,res,next)=>{ try { if(!ensurePostgres(res)) return; await store.deleteRule(Number(req.params.id)); res.json({ ok: true }); } catch(e){ next(e); } });

// Evaluate rules for a device now (ad-hoc)
router.get('/device/:deviceName/evaluate', async (req,res,next)=>{ try { if(!ensurePostgres(res)) return; const out = await store.evaluateRulesForDevice(req.params.deviceName); res.json(out); } catch(e){ next(e); } });

module.exports = router;
