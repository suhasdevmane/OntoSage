import { useEffect, useState } from 'react';
import { useTimeContext } from './useTimeContext';
import { apiFetch } from '../api';

// Fetch mapping definitions (raw list)
export function useMappings() {
  const [data, setData] = useState();
  useEffect(() => {
    apiFetch('/api/mappings')
      .then(r => {
        const body = r.body;
        setData(Array.isArray(body) ? { body } : { body: [] });
      })
      .catch(() => { setData({ body: [] }); });
  }, []);
  return data?.body;
}

export function useDataSources() {
  const [data, setData] = useState();
  useEffect(() => {
    apiFetch('/api/datasources')
      .then(r => {
        const body = r.body;
        setData(Array.isArray(body) ? { body } : { body: [] });
      })
      .catch(()=> { setData({ body: [] }); });
  }, []);
  return data?.body;
}

// Poll latest values for all mapped devices
export function useLatestValues(pollMs = 15000) {
  const [res, setRes] = useState();
  useEffect(() => {
    let active = true;
    const run = () => apiFetch('/api/latest').then(r => { if(active) setRes(r); }).catch(()=>{});
    const id = setInterval(run, pollMs);
    run();
    return () => { active = false; clearInterval(id); };
  }, [pollMs]);
  return res?.body || {};
}

// Per-device time series window (defaults last hour)
export function useTimeSeries(deviceName, windowMs = 3600_000, pollMs = 30000) {
  // If TimeContext present, override window and cadence.
  const time = useTimeContext();
  const [state, setState] = useState();
  useEffect(() => {
    if(!deviceName) return;
    let active = true;
    const load = () => {
      const to = time?.to || Date.now();
      const from = time?.from || (to - windowMs);
      apiFetch(`/api/mappings/device/${encodeURIComponent(deviceName)}/timeseries?from=${from}&to=${to}`)
        .then(r => { if(active) setState(r.body); })
        .catch(()=>{});
    };
    const interval = time?.live ? 5000 : (time?.mode === 'relative' ? 20000 : pollMs);
    const id = setInterval(load, interval);
    load();
    return () => { active = false; clearInterval(id); };
  }, [deviceName, windowMs, pollMs, time]);
  return state; // { mapping, series }
}
