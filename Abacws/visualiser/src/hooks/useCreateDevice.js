import { useState, useCallback } from 'react';
import { apiFetch } from '../api';

function validate(payload) {
  if (!payload) return 'Missing payload';
  const { name, floor, position } = payload;
  if (!name || typeof name !== 'string') return 'Name required';
  if (floor === undefined || floor === null || Number.isNaN(Number(floor))) return 'Floor required';
  if (!position || typeof position !== 'object') return 'Position required';
  const { x,y,z } = position;
  if ([x,y,z].some(v => typeof v !== 'number' || Number.isNaN(v))) return 'Invalid position';
  return null;
}

export function useCreateDevice() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const createDevice = useCallback(async (payload) => {
    setError(null);
    const err = validate(payload);
    if (err) { setError(err); return { ok:false, error:err }; }
    setLoading(true);
    try {
      const res = await apiFetch('/api/devices', 'POST', payload);
      if (!res.ok) {
        const msg = res.body?.error || `Create failed (${res.status})`;
        setError(msg);
        return { ok:false, error: msg };
      }
      // Fire a custom event so 3D scene / other hooks can refresh devices list without tight coupling
      try { window.dispatchEvent(new CustomEvent('abacws:device-created', { detail: res.body })); } catch(_){ }
      setLoading(false);
      return { ok:true, device: res.body };
    } catch (e) {
      const msg = e.message || 'Network error';
      setError(msg);
      setLoading(false);
      return { ok:false, error: msg };
    }
  }, []);

  return { createDevice, loading, error };
}
