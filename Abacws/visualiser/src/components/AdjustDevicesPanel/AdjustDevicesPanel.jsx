import React, { useEffect, useMemo, useRef, useState } from 'react';
import './AdjustDevicesPanel.scss';
import { useDevices } from '../../hooks/useDevice';
import { useSelectedDevice } from '../../three';
import { apiFetch } from '../../api';

// Lazy access to Graphics singleton (avoid direct import cycle)
function getGraphics() {
  try { return window.__ABACWS_GRAPHICS_INSTANCE__; } catch(_) { return undefined; }
}

export function AdjustDevicesPanel() {
  const devices = useDevices();
  const selected = useSelectedDevice();
  const [open, setOpen] = useState(true);
  const [mode, setMode] = useState('view'); // 'view' | 'adjust'
  const [activeName, setActiveName] = useState(null);
  const [draft, setDraft] = useState({ x: '', y: '', z: '' });
  const [saving, setSaving] = useState(false);
  const [hintShown, setHintShown] = useState(false);
  const toastRef = useRef(null);

  // Build quick lookup for device positions
  const deviceMap = useMemo(() => {
    const m = new Map();
    if (Array.isArray(devices)) devices.forEach(d => m.set(d.name, d));
    return m;
  }, [devices]);

  // Expose Graphics instance globally once (first mount) for panel use
  useEffect(() => {
    // Graphics singleton is created elsewhere; attach when available
    if (!window.__ABACWS_GRAPHICS_INSTANCE__ && window.GraphicsSharedInstance) {
      window.__ABACWS_GRAPHICS_INSTANCE__ = window.GraphicsSharedInstance;
    }
  }, []);

  // Initialize draft when active changes
  useEffect(() => {
    if (!activeName) return;
    const dev = deviceMap.get(activeName);
    if (dev?.position) {
      setDraft({ x: dev.position.x, y: dev.position.y, z: dev.position.z });
      // Focus first input for quicker edits
      setTimeout(() => {
        try { toastRef.current?.querySelector('input[name="x"]').focus(); } catch(_){}
      }, 50);
    }
  }, [activeName, deviceMap]);

  // Live update mesh as draft changes (adjust mode only)
  useEffect(() => {
    if (mode !== 'adjust' || !activeName) return;
    const g = getGraphics();
    if (!g) return;
    const mesh = g.getDeviceMeshByName(activeName);
    if (!mesh) return;
    const { x, y, z } = draft;
    const valid = [x,y,z].every(v => v !== '' && !Number.isNaN(Number(v)));
    if (!valid) return;
    mesh.position.set(Number(x), Number(y), Number(z));
  }, [draft, mode, activeName]);

  // One time hint
  useEffect(() => {
    if (typeof localStorage === 'undefined') return;
    if (localStorage.getItem('__abacws_adjust_hint')) return;
    setHintShown(true);
    localStorage.setItem('__abacws_adjust_hint', '1');
    const t = setTimeout(() => setHintShown(false), 6000);
    return () => clearTimeout(t);
  }, []);

  const startAdjust = () => {
    setMode('adjust');
    if (!activeName && devices?.length) setActiveName(devices[0].name);
  };
  const cancelAdjust = () => {
    // Re-sync mesh to stored position if user cancels
    if (activeName) {
      const dev = deviceMap.get(activeName);
      const g = getGraphics();
      if (dev?.position && g) {
        const mesh = g.getDeviceMeshByName(activeName);
        if (mesh) mesh.position.set(dev.position.x, dev.position.y, dev.position.z);
      }
    }
    setMode('view');
  };

  async function savePosition() {
    if (!activeName) return;
    const { x, y, z } = draft;
    const valid = [x,y,z].every(v => v !== '' && !Number.isNaN(Number(v)));
    if (!valid) return;
    setSaving(true);
    try {
      const res = await apiFetch(`/api/devices/${encodeURIComponent(activeName)}`, 'PATCH', { position: { x:Number(x), y:Number(y), z:Number(z) } });
      if (!res.ok) throw new Error(res.body?.error || 'Failed');
      // Optionally lock (pin) automatically? we expose a toggle after save
      // Refresh internal device array (optimistic: patch local map)
      const dev = deviceMap.get(activeName);
      if (dev) dev.position = { x:Number(x), y:Number(y), z:Number(z) };
      setMode('view');
    } catch(e) {
      alert('Save failed: ' + e.message);
    } finally {
      setSaving(false);
    }
  }

  const panelClass = 'adjust-panel' + (open ? ' open' : '');

  return (
    <>
    {/* Floating handle for opening/closing at bottom-left */}
    <button
      className={"adjust-panel-toggle" + (open ? ' open' : '')}
      aria-label={open ? 'Collapse device panel' : 'Expand device panel'}
      onClick={() => setOpen(o=>!o)}
    >
      {open ? '⟨' : '⟩'}
    </button>
    <div className={panelClass} aria-label="Device Adjust Panel">
      <div className="ap-header">
        <div className="ap-title">Devices</div>
        <div className="ap-actions">
          {mode === 'view' && <button className="ap-btn" onClick={startAdjust} disabled={!devices?.length}>Adjust Devices</button>}
          {mode === 'adjust' && <>
            <button className="ap-btn" onClick={savePosition} disabled={saving}>Save</button>
            <button className="ap-btn secondary" onClick={cancelAdjust}>Cancel</button>
          </>}
        </div>
      </div>
      {open && (
        <div className="ap-body">
          {mode === 'view' && (
            <ul className="device-list">
              {Array.isArray(devices) && devices.map(d => (
                <li key={d.name} className={d.name === selected ? 'sel' : ''} title={d.name}>
                  <button onClick={() => { setActiveName(d.name); window.dispatchEvent(new CustomEvent('focus-device',{ detail:{ name:d.name } })); }}>
                    <span className="dot" />{d.name}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {mode === 'adjust' && (
            <div className="adjust-form" ref={toastRef}>
              <label className="row">
                <span>Device</span>
                <select value={activeName || ''} onChange={e=> setActiveName(e.target.value)}>
                  {Array.isArray(devices) && devices.map(d => <option key={d.name} value={d.name}>{d.name}</option>)}
                </select>
              </label>
              <div className="coords-grid">
                {['x','y','z'].map(axis => (
                  <label key={axis} className="coord-cell">
                    <span>{axis.toUpperCase()}</span>
                    <input
                      name={axis}
                      type="number"
                      value={draft[axis]}
                      onChange={e => setDraft(prev => ({ ...prev, [axis]: e.target.value }))}
                      step={axis === 'y' ? 1 : 1}
                    />
                  </label>
                ))}
              </div>
              <div className="live-note">Changes apply live to the 3D view. Click Save to persist.</div>
              <div className="form-footer">
                <button className="ap-btn" onClick={savePosition} disabled={saving}>Save Position</button>
                <button className="ap-btn secondary" onClick={cancelAdjust}>Cancel</button>
              </div>
            </div>
          )}
        </div>
      )}
      {hintShown && <div className="ap-hint">Adjust Mode: pick a device, edit X/Y/Z, then Save. ESC or Cancel to abort.</div>}
    </div>
    </>
  );
}
