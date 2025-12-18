import React, { useEffect, useState } from 'react';
import { listSensors } from '../api/analyticsApi';

export default function SensorSelector({ selected, onChange }) {
  const [sensors, setSensors] = useState([]);
  const [filter, setFilter] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true); setError('');
    try {
      const data = await listSensors();
      setSensors(data.sensors || []);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  useEffect(()=>{ load(); }, []);

  const toggle = (name) => {
    if (selected.includes(name)) onChange(selected.filter(s=>s!==name));
    else onChange([...selected, name]);
  };

  const filtered = sensors.filter(s => !filter || s.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="sensor-selector">
      <div className="d-flex align-items-center gap-2 mb-2">
        <strong className="small mb-0">Sensors</strong>
        <input className="form-control form-control-sm" style={{maxWidth:200}} placeholder="Filter" value={filter} onChange={e=>setFilter(e.target.value)} />
        <button className="btn btn-sm btn-outline-secondary" type="button" onClick={load} disabled={loading}>{loading? '…' : 'Reload'}</button>
        {selected.length>0 && <span className="badge bg-primary">{selected.length} selected</span>}
      </div>
      {error && <div className="alert alert-warning py-1 px-2 small mb-2">{error}</div>}
      <div className="border rounded p-2 bg-light" style={{maxHeight:150, overflow:'auto'}}>
        {filtered.map(name => {
          const active = selected.includes(name);
          return (
            <button key={name} type="button" onClick={()=>toggle(name)} className={`btn btn-sm me-1 mb-1 ${active? 'btn-primary':'btn-outline-secondary'}`} style={{fontSize:'0.7rem'}}>{name}</button>
          );
        })}
        {filtered.length===0 && <div className="text-muted small">No sensors match filter.</div>}
      </div>
    </div>
  );
}
