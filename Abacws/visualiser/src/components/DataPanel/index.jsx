import React from 'react';
import { useTimeSeries, useMappings, useDataSources } from '../../hooks';
import { apiFetch } from '../../api';

// Simple sparkline polyline from series [{ts, ...}]
function Sparkline({ series, primary }) {
  if (!series?.length || !primary) return <div style={{opacity:.5}}>No data</div>;
  const points = series.map((d,i)=>({ x:i, y: d[primary] })).filter(p=> typeof p.y === 'number');
  if(!points.length) return <div style={{opacity:.5}}>No numeric data</div>;
  const ys = points.map(p=>p.y);
  const min = Math.min(...ys); const max = Math.max(...ys);
  const range = max - min || 1;
  const norm = points.map(p=>({ x:p.x, y: 1 - (p.y - min)/range }));
  const w = 140; const h = 40;
  const step = w / Math.max(1, norm.length - 1);
  const path = norm.map((p,i)=>`${i===0?'M':'L'}${(i*step).toFixed(1)},${(p.y*h).toFixed(1)}`).join(' ');
  return (
    <svg width={w} height={h} style={{display:'block'}}>
      <path d={path} fill="none" stroke="#00ffaa" strokeWidth={2} />
    </svg>
  );
}

export const DataPanel = ({ deviceName }) => {
  const mappings = useMappings();
  const dataSources = useDataSources();
  const deviceMappings = mappings?.filter(m => m.device_name === deviceName) || [];
  const [mappingIndex, setMappingIndex] = React.useState(0);
  React.useEffect(()=> { setMappingIndex(0); }, [deviceName]);
  const mapping = deviceMappings[mappingIndex];
  const ts = useTimeSeries(deviceName || undefined, 3600_000, 20000);
  const primary = mapping?.primary_value_column || mapping?.value_columns?.[0];
  const [editing, setEditing] = React.useState(false);
  const [form, setForm] = React.useState(()=>({
    data_source_id: mapping?.data_source_id || '',
    table_name: mapping?.table_name || '',
    device_id_column: mapping?.device_id_column || '',
    device_identifier_value: mapping?.device_identifier_value || deviceName || '',
    timestamp_column: mapping?.timestamp_column || '',
    value_columns: mapping?.value_columns?.join(',') || '',
    primary_value_column: mapping?.primary_value_column || '',
    range_min: mapping?.range_min || '',
    range_max: mapping?.range_max || '',
    color_min: mapping?.color_min || '#1d4ed8',
    color_max: mapping?.color_max || '#ef4444'
  }));
  const [tables, setTables] = React.useState([]);
  const [columns, setColumns] = React.useState([]);
  const [loadingMeta, setLoadingMeta] = React.useState(false);
  const [apiKey, setApiKey] = React.useState(() => window.localStorage.getItem('abacws_api_key') || '');
  function updateApiKey(val){ setApiKey(val); window.localStorage.setItem('abacws_api_key', val); }

  React.useEffect(()=>{
    if(!editing) return; // Only load when editing
    async function loadTables() {
      if(!form.data_source_id) { setTables([]); return; }
      setLoadingMeta(true);
      try {
        const res = await apiFetch(`/api/datasources/${form.data_source_id}/tables`);
        setTables(res.body||[]);
      } catch(_) {}
      setLoadingMeta(false);
    }
    loadTables();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, form.data_source_id]);

  React.useEffect(()=>{
    if(!editing) return;
    async function loadColumns() {
      if(!form.data_source_id || !form.table_name) { setColumns([]); return; }
      setLoadingMeta(true);
      try {
        const res = await apiFetch(`/api/datasources/${form.data_source_id}/columns?table=${encodeURIComponent(form.table_name)}`);
        setColumns(res.body||[]);
      } catch(_) {}
      setLoadingMeta(false);
    }
    loadColumns();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, form.data_source_id, form.table_name]);

  function updateForm(patch) { setForm(f => ({...f, ...patch})); }

  async function saveMapping(e){
    e.preventDefault();
    const payload = {
      device_name: deviceName,
      data_source_id: Number(form.data_source_id),
      table_name: form.table_name,
      device_id_column: form.device_id_column,
      device_identifier_value: form.device_identifier_value,
      timestamp_column: form.timestamp_column,
      value_columns: form.value_columns.split(',').map(s=>s.trim()).filter(Boolean),
      primary_value_column: form.primary_value_column || undefined,
      range_min: form.range_min === '' ? undefined : Number(form.range_min),
      range_max: form.range_max === '' ? undefined : Number(form.range_max),
      color_min: form.color_min,
      color_max: form.color_max
    };
    try {
      let res;
      if(mapping) {
        res = await apiFetch(`/api/mappings/${mapping.id}`, 'PATCH', payload, apiKey? { 'x-api-key': apiKey } : undefined);
      } else {
        res = await apiFetch('/api/mappings', 'POST', payload, apiKey? { 'x-api-key': apiKey } : undefined);
      }
      if(!res.ok) {
        alert(res.body?.error || 'Failed to save mapping');
        return;
      }
      // Reload page data: crude approach (could refresh mappings hook via event)
      window.location.reload();
    } catch(err){
      alert('Error saving mapping');
      // eslint-disable-next-line no-console
      console.error(err);
    }
  }

  return (
    <div style={{display:'grid', gap:'8px'}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
        {!editing && (
          <button onClick={()=> setEditing(true)} style={{fontSize:12,padding:'4px 8px',cursor:'pointer'}}> {mapping? 'Edit Mapping' : 'Create Mapping'} </button>
        )}
        {editing && (
          <button onClick={()=> setEditing(false)} style={{fontSize:12,padding:'4px 8px',cursor:'pointer'}}>Cancel</button>
        )}
      </div>
      {editing && (
        <form onSubmit={saveMapping} style={{display:'grid',gap:6,fontSize:12,background:'#1f2937',padding:8,borderRadius:6}}>
          <div style={{display:'grid',gap:4}}>
            <label>Data Source
              <select value={form.data_source_id} onChange={e=> updateForm({data_source_id: e.target.value, table_name:'', timestamp_column:'', device_id_column:'', value_columns:'', primary_value_column:''})} style={{width:'100%'}} required>
                <option value="">Select…</option>
                {dataSources?.map(ds => <option key={ds.id} value={ds.id}>{ds.name||`DS ${ds.id}`}</option>)}
              </select>
            </label>
            <label>Table
              <select value={form.table_name} onChange={e=> updateForm({table_name:e.target.value, timestamp_column:'', device_id_column:'', value_columns:'', primary_value_column:''})} disabled={!form.data_source_id || loadingMeta} required>
                <option value="">{loadingMeta? 'Loading…' : 'Select…'}</option>
                {tables.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            <label>Device ID Column
              <select value={form.device_id_column} onChange={e=> updateForm({device_id_column:e.target.value})} disabled={!columns.length} required>
                <option value="">Select…</option>
                {columns.map(c => <option key={c.column_name} value={c.column_name}>{c.column_name}</option>)}
              </select>
            </label>
            <label>Device Identifier Value
              <input value={form.device_identifier_value} onChange={e=> updateForm({device_identifier_value:e.target.value})} required placeholder="e.g. sensor_001" />
            </label>
            <label>Timestamp Column
              <select value={form.timestamp_column} onChange={e=> updateForm({timestamp_column:e.target.value})} disabled={!columns.length} required>
                <option value="">Select…</option>
                {columns.map(c => <option key={c.column_name} value={c.column_name}>{c.column_name}</option>)}
              </select>
            </label>
            <label>Value Columns (comma list)
              <input value={form.value_columns} onChange={e=> updateForm({value_columns:e.target.value})} required placeholder="temp,humidity" />
            </label>
            <label>Primary Value Column (optional)
              <input value={form.primary_value_column} onChange={e=> updateForm({primary_value_column:e.target.value})} placeholder="temp" />
            </label>
            <label>Value Range Min (optional)
              <input type="number" value={form.range_min} onChange={e=> updateForm({range_min:e.target.value})} placeholder="auto" />
            </label>
            <label>Value Range Max (optional)
              <input type="number" value={form.range_max} onChange={e=> updateForm({range_max:e.target.value})} placeholder="auto" />
            </label>
            <label>Color Min
              <input type="color" value={form.color_min} onChange={e=> updateForm({color_min:e.target.value})} />
            </label>
            <label>Color Max
              <input type="color" value={form.color_max} onChange={e=> updateForm({color_max:e.target.value})} />
            </label>
          </div>
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
            <small style={{opacity:.7}}>API Key:</small>
            <input type="password" value={apiKey} onChange={e=> updateApiKey(e.target.value)} placeholder="x-api-key" style={{fontSize:11,padding:'2px 4px'}} />
            <button type="submit" style={{padding:'4px 10px',cursor:'pointer'}}>Save</button>
          </div>
        </form>
      )}
      {!editing && !mapping && <div style={{fontSize:12,opacity:.75}}>No mapping yet for this device.</div>}
      {!editing && mapping && (
        <>
          {deviceMappings.length > 1 && (
            <div style={{display:'flex',gap:4,alignItems:'center'}}>
              <span style={{fontSize:11,opacity:.7}}>Mapping:</span>
              <select value={mappingIndex} onChange={e=> setMappingIndex(Number(e.target.value))} style={{fontSize:11}}>
                {deviceMappings.map((m,i)=><option key={m.id} value={i}>{m.table_name}:{m.device_identifier_value}</option>)}
              </select>
            </div>
          )}
          <div style={{fontSize:12,opacity:.8}}>
            <strong>Table:</strong> {mapping.table_name} · <strong>Columns:</strong> {mapping.value_columns.join(', ')}
          </div>
          <Sparkline series={ts?.series||[]} primary={primary} />
          {ts?.series?.length && (
            <div style={{display:'grid', gap:4, fontSize:12}}>
              <div style={{opacity:.7}}>Latest:</div>
              {(() => {
                const last = ts.series[ts.series.length-1];
                if(!last) return null;
                return mapping.value_columns.map(col => <div key={col}>{col}: {last[col] === undefined? '—' : last[col]}</div>);
              })()}
            </div>
          )}
        </>
      )}
    </div>
  );
};
