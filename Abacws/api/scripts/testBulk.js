// Simple runtime test for bulk history endpoint
(async () => {
  try {
    const devices = await fetch('http://localhost:5000/api/devices').then(r=>r.json());
    console.log('Device count:', devices.length);
    if(!devices.length) return;
    const target = devices.slice(0,2).map(d=>d.name);
    const body = { devices: target, from: 0, to: Date.now(), format: 'json' };
    const bulk = await fetch('http://localhost:5000/api/devices/history/bulk', {
      method:'POST', headers:{ 'Content-Type':'application/json' }, body: JSON.stringify(body)
    }).then(r=> r.json());
    console.log('Bulk devices returned:', bulk.devices.length);
    for(const d of bulk.devices){
      console.log(`  ${d.device} history length:`, d.history.length);
    }
    // CSV fetch
    const csv = await fetch('http://localhost:5000/api/devices/history/bulk', {
      method:'POST', headers:{ 'Content-Type':'application/json' }, body: JSON.stringify({ ...body, format: 'csv' })
    }).then(r=> r.text());
    console.log('CSV sample (first 5 lines):');
    console.log(csv.split('\n').slice(0,5).join('\n'));
  } catch (e) {
    console.error('Test bulk failed', e);
    process.exitCode = 1;
  }
})();
