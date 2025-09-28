import { useEffect, useState } from 'react';
import { apiFetch } from '../api';

export function useHealth(pollMs = 10000) {
  const [health, setHealth] = useState();
  useEffect(() => {
    let cancelled = false;
    let timer;
    const run = async () => {
      try {
        const res = await apiFetch('/api/health');
        if (!cancelled) setHealth(res.body);
      } catch (e) {
        if (!cancelled) setHealth({ status: 'error', error: e.message });
      }
      timer = setTimeout(run, pollMs);
    };
    run();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [pollMs]);
  return health;
}

export async function toggleDatastore(disable, apiKey) {
  const path = disable ? '/api/admin/db/disable' : '/api/admin/db/enable';
  const headers = apiKey ? { 'x-api-key': apiKey } : {};
  return apiFetch(path, { method: 'POST', headers });
}