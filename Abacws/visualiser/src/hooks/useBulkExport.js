import { useState, useCallback, useRef, useEffect } from 'react';

// Small helper to fetch JSON with abort support
async function fetchJSON(url, signal) {
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`Fetch failed ${res.status}`);
  return res.json();
}

function toISO(ts){ return new Date(ts).toISOString(); }

function buildCSV(devicesHistories) {
  // Flatten all records, prefix device
  const rows = [];
  const headerSet = new Set(['device','timestamp']);
  devicesHistories.forEach(({ device, history }) => {
    history.forEach(entry => {
      const row = { device, timestamp: toISO(entry.timestamp) };
      Object.entries(entry).forEach(([k,v]) => {
        if (k === 'timestamp') return;
        if (v && typeof v === 'object' && v.value !== undefined) {
          headerSet.add(`${k}.value`);
          row[`${k}.value`] = v.value;
          if (v.units) { headerSet.add(`${k}.units`); row[`${k}.units`] = v.units; }
        } else {
          headerSet.add(k);
          row[k] = typeof v === 'object' ? JSON.stringify(v) : v;
        }
      });
      rows.push(row);
    });
  });
  const headers = Array.from(headerSet);
  const csvLines = [headers.join(',')];
  rows.forEach(r => {
    const line = headers.map(h => {
      const val = r[h];
      if (val === undefined || val === null) return '';
      const s = String(val).replace(/"/g,'""');
      if (/[",\n]/.test(s)) return `"${s}"`;
      return s;
    }).join(',');
    csvLines.push(line);
  });
  return csvLines.join('\n');
}

export function useBulkHistoryExport({ defaultSelection = 'all', concurrency = 4 } = {}) {
  const [state, setState] = useState({ running:false, progress:0, total:0, error:null, strategy:'client' });
  const abortRef = useRef(null);
  const lastSelectionRef = useRef([]);

  // Persist last selection
  useEffect(()=> {
    if (lastSelectionRef.current.length) {
      try { localStorage.setItem('bulkExportSelection', JSON.stringify(lastSelectionRef.current)); } catch(_){}
    }
  }, [state.running]);

  function decideStrategy(devices, format) {
    // Heuristic now that server endpoint is implemented:
    //  - Use server for >20 devices always
    //  - Use server for CSV if >8 devices (header explosion & memory)
    //  - Otherwise keep client for responsiveness
    if (devices.length > 20) return 'server';
    if (format === 'csv' && devices.length > 8) return 'server';
    return 'client';
  }

  const cancel = useCallback(()=> {
    abortRef.current?.abort();
    setState(s=> ({ ...s, running:false, error: 'Cancelled' }));
  }, []);

  async function clientStrategy({ devices, from, to, format, baseName }) {
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ running:true, progress:0, total:devices.length, error:null, strategy:'client' });
    const results = [];
    let completed = 0;
    const queue = [...devices];
    async function worker() {
      while(queue.length) {
        const d = queue.shift();
        try {
          const url = `/api/devices/${encodeURIComponent(d)}/history?from=${from}&to=${to}`;
          const history = await fetchJSON(url, controller.signal);
          results.push({ device:d, history });
        } catch (e) {
          if (controller.signal.aborted) return; // silent
          throw e;
        } finally {
          completed += 1;
          setState(s=> ({ ...s, progress: completed }));
        }
      }
    }
    const workers = Array.from({ length: Math.min(concurrency, devices.length) }, () => worker());
    await Promise.all(workers);
    if (controller.signal.aborted) return; // Cancelled early

    if (format === 'json') {
      const blob = new Blob([JSON.stringify({ devices: results, window: { from, to } }, null, 2)], { type:'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${baseName}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    } else if (format === 'csv') {
      const csv = buildCSV(results);
      const blob = new Blob([csv], { type:'text/csv' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${baseName}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    }
    setState(s=> ({ ...s, running:false }));
  }

  async function serverStrategy({ devices, from, to, format, baseName }) {
    setState({ running:true, progress:0, total:1, error:null, strategy:'server' });
    try {
      const res = await fetch('/api/devices/history/bulk', {
        method:'POST',
        headers:{ 'Content-Type':'application/json' },
        body: JSON.stringify({ devices, from, to, format })
      });
      if (!res.ok) throw new Error(`Server bulk failed ${res.status}`);
      if (format === 'json') {
        const json = await res.json();
        const blob = new Blob([JSON.stringify(json, null, 2)], { type:'application/json' });
        const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `${baseName}.json`; a.click(); URL.revokeObjectURL(a.href);
      } else {
        const text = await res.text();
        const blob = new Blob([text], { type:'text/csv' });
        const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `${baseName}.csv`; a.click(); URL.revokeObjectURL(a.href);
      }
      setState(s=> ({ ...s, running:false, progress:1 }));
    } catch (e) {
      setState(s=> ({ ...s, running:false, error: e.message || String(e) }));
    }
  }

  const runExport = useCallback(async ({ devices, from, to, format='json', baseName }) => {
    if (!devices?.length) return;
    lastSelectionRef.current = devices;
    const strategy = decideStrategy(devices, format);
    try {
      if (strategy === 'server') {
        await serverStrategy({ devices, from, to, format, baseName });
      } else {
        await clientStrategy({ devices, from, to, format, baseName });
      }
    } catch (e) {
      setState(s=> ({ ...s, running:false, error: e.message || String(e) }));
    }
  }, []);

  return { ...state, runExport, cancel };
}
