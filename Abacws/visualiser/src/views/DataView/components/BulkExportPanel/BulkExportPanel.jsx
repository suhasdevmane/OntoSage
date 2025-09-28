import { useState, useMemo, useEffect } from 'react';
import { useDevices } from '../../../../hooks';
import { useTimeContext } from '../../../../hooks/useTimeContext';

// Simple helper to build file names
function buildFileBase(devices, from, to) {
  const ts = new Date().toISOString().replace(/[:.]/g,'-');
  const devPart = devices.length === 1 ? devices[0] : `${devices.length}-devices`;
  return `${devPart}_${from}-${to}_${ts}`;
}

export function BulkExportPanel({ onRequestExport, running, progress, total, onCancel, strategy }) {
  const devices = useDevices() || [];
  const time = useTimeContext();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState([]); // array of device names
  const [format, setFormat] = useState('json'); // 'json' | 'csv'
  const [filterFloor, setFilterFloor] = useState('all');

  const floors = useMemo(() => {
    const set = new Set();
    devices.forEach(d => { if (d.floor !== undefined) set.add(d.floor); });
    return Array.from(set).sort((a,b)=>a-b);
  }, [devices]);

  const filteredDevices = useMemo(() => {
    return devices.filter(d => filterFloor === 'all' || String(d.floor) === String(filterFloor));
  }, [devices, filterFloor]);

  // Restore selection on open first time
  useEffect(()=> {
    if (open) {
      try {
        const raw = localStorage.getItem('bulkExportSelection');
        if (raw) {
          const arr = JSON.parse(raw);
          if (Array.isArray(arr) && arr.length) setSelected(arr.filter(n => devices.some(d=>d.name===n)));
          else if (!arr || !arr.length) { // default all if configured
            setSelected(devices.map(d=>d.name));
          }
        } else {
          setSelected(devices.map(d=>d.name));
        }
      } catch(_) {
        setSelected(devices.map(d=>d.name));
      }
    }
  }, [open, devices]);

  // Persist selection changes
  useEffect(()=> {
    try { localStorage.setItem('bulkExportSelection', JSON.stringify(selected)); } catch(_){}
  }, [selected]);

  function toggle(name) {
    setSelected(sel => sel.includes(name) ? sel.filter(s => s!==name) : [...sel, name]);
  }

  function selectAll() {
    setSelected(filteredDevices.map(d=>d.name));
  }
  function clearAll() { setSelected([]); }

  const from = time?.from || (Date.now()-12*60*60*1000);
  const to = time?.to || Date.now();
  const baseName = buildFileBase(selected, from, to);

  function handleExport() {
    if (!selected.length) return;
    onRequestExport?.({ devices: selected, from, to, format, baseName });
  }

  return (
    <section className="bulk-export-panel" style={{marginTop:16}}>
      <header style={{display:'flex',justifyContent:'space-between',alignItems:'center',cursor:'pointer'}} onClick={()=> setOpen(o=>!o)}>
        <h2 style={{fontSize:14,margin:0}}>Bulk Export</h2>
        <span style={{fontSize:12,color:'#9ca3af'}}>{open? '−':'+'}</span>
      </header>
      {open && (
        <div style={{marginTop:8,border:'1px solid #374151',padding:8,borderRadius:4,background:'#1f2937'}}>
          <div style={{display:'flex',flexWrap:'wrap',gap:8,alignItems:'center',fontSize:12}}>
            <label>Floor:
              <select value={filterFloor} onChange={e=> setFilterFloor(e.target.value)} style={{marginLeft:4}}>
                <option value='all'>All</option>
                {floors.map(f=> <option key={f} value={String(f)}>{f}</option>)}
              </select>
            </label>
            <label>Format:
              <select value={format} onChange={e=> setFormat(e.target.value)} style={{marginLeft:4}}>
                <option value='json'>JSON</option>
                <option value='csv'>CSV</option>
              </select>
            </label>
            <button onClick={selectAll} style={miniBtn}>Select All</button>
            <button onClick={clearAll} style={miniBtn}>Clear</button>
            <span style={{marginLeft:'auto'}}>Selected: {selected.length}</span>
          </div>
          <ul style={{listStyle:'none',margin:'8px 0',padding:0,maxHeight:160,overflow:'auto',display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(140px,1fr))',gap:4}}>
            {filteredDevices.map(d => (
              <li key={d.name} style={{border:'1px solid #374151',borderRadius:4,background: selected.includes(d.name)? '#2563eb':'#111827'}}>
                <label style={{display:'flex',alignItems:'center',gap:4,fontSize:11,padding:'4px 6px',cursor:'pointer'}}>
                  <input type='checkbox' checked={selected.includes(d.name)} onChange={()=> toggle(d.name)} />
                  <span className='text-capitalize'>{d.name}</span>
                </label>
              </li>
            ))}
            {!filteredDevices.length && <li style={{fontSize:11,color:'#9ca3af'}}>No devices</li>}
          </ul>
          <div style={{display:'flex',flexWrap:'wrap',gap:8,alignItems:'center'}}>
            <span style={{fontSize:11,color:'#9ca3af'}}>Window: {new Date(from).toISOString()} → {new Date(to).toISOString()}</span>
            {running ? (
              <>
                <span style={{fontSize:11}}>Progress: {progress}/{total} ({strategy})</span>
                <button onClick={onCancel} style={{...miniBtn,background:'#b91c1c'}}>Cancel</button>
              </>
            ) : (
              <button disabled={!selected.length} onClick={handleExport} style={{...miniBtn,padding:'6px 12px',background: selected.length? '#10b981':'#374151'}}>Export {format.toUpperCase()}</button>
            )}
            <span style={{fontSize:10,color:'#6b7280'}}>{baseName}.{format}</span>
          </div>
        </div>
      )}
    </section>
  );
}

const miniBtn = { background:'#374151',color:'#fff',border:'1px solid #4b5563',padding:'4px 8px',borderRadius:4,cursor:'pointer',fontSize:11 };
