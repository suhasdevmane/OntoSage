const express = require('express');
const store = require('../datastore');

const router = express.Router();

// Simple in-memory subscriber list (SSE is per-process; fine for single instance)
const clients = new Set();

// Helper to send an event to one client
function send(client, event, data){
  try {
    client.write(`event: ${event}\n`);
    client.write(`data: ${JSON.stringify(data)}\n\n`);
  } catch(_) { /* ignore */ }
}

// Broadcast helper
function broadcast(event, data){
  for(const c of clients) send(c, event, data);
}

// Periodic polling loop state
let loopStarted = false;
async function startLoop(){
  if(loopStarted) return; loopStarted = true;
  async function tick(){
    try {
      // Only work if there are subscribers
      if(clients.size){
        // External mapped latest values (batch)
        let external = {};
        try { external = await store.fetchLatestForAllMappings(); } catch(_) {}
        if(Object.keys(external).length){
          broadcast('latest', { type:'external-latest', data: external, ts: Date.now() });
        }
        // Evaluate rules for devices present in external batch (if postgres rules available)
        if(store.evaluateRulesForDevice){
          const deviceNames = Object.keys(external);
            for(const d of deviceNames){
              try {
                const triggered = await store.evaluateRulesForDevice(d);
                if(triggered.length) broadcast('rules', { type:'rule-trigger', device: d, events: triggered, ts: Date.now() });
              } catch(_) {}
            }
        }
      }
    } catch(e){ /* silent */ }
    setTimeout(tick, 8000); // 8s cadence (can tune)
  }
  tick();
}

router.get('/events', async (req,res) => {
  // Only supported when postgres engine active for now (external + rules); fallback still provides a stream structure
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Access-Control-Allow-Origin': '*'
  });
  res.write('\n');
  clients.add(res);
  // Initial heartbeat
  send(res, 'hello', { ts: Date.now(), engine: store.engine });
  startLoop();
  req.on('close', () => { clients.delete(res); });
});

// Lightweight ping endpoint to reveal subscriber count (debug)
router.get('/info', (_req,res)=>{ res.json({ subscribers: clients.size }); });

module.exports = router;
