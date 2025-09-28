import { useEffect, useState, useCallback } from 'react';
import { useCreateDevice } from '../../hooks';

export function DeviceCreateModal({ open, onClose, onCreated, initialPosition }) {
  const { createDevice, loading, error } = useCreateDevice();
  const [name, setName] = useState('');
  const [type, setType] = useState('');
  const [floor, setFloor] = useState(0);
  const [pinned, setPinned] = useState(false);
  const [position, setPosition] = useState({ x:0, y:70, z:0 });
  const [pickMode, setPickMode] = useState(false);
  const [clientError, setClientError] = useState(null);
  const [fromScene, setFromScene] = useState(false);

  const reset = () => {
    setName(''); setType(''); setFloor(0); setPinned(false); setPosition({x:0,y:70,z:0}); setClientError(null); setPickMode(false);
  };

  useEffect(()=> { if(!open) reset(); }, [open]);

  // When opening with an initialPosition (from double-click), prefill and mark fromScene
  useEffect(()=> {
    if(open && initialPosition) {
      setPosition(initialPosition);
      setFromScene(true);
      // Auto-suggest a unique device name if empty (device-<n>)
      if(!name) {
        try {
          const cacheRaw = localStorage.getItem('__abacws_next_device_id');
          let next = cacheRaw ? Number(cacheRaw) : 1;
          if(Number.isNaN(next) || next < 1) next = 1;
          setName(`device-${next}`);
          localStorage.setItem('__abacws_next_device_id', String(next+1));
        } catch(_){}
      }
    } else if(open && !initialPosition) {
      setFromScene(false);
    }
  }, [open, initialPosition, name]);

  // Listen for pick events from 3D scene (will add event dispatch in Graphics later)
  useEffect(()=> {
    if(!pickMode) return;
    const handler = (e) => {
      const { x,y,z } = e.detail || {}; if (typeof x==='number' && typeof y==='number' && typeof z==='number') {
        setPosition({ x: Math.round(x), y: Math.round(y), z: Math.round(z) });
        setPickMode(false);
      }
    };
    window.addEventListener('abacws:pick-position', handler);
    return () => window.removeEventListener('abacws:pick-position', handler);
  }, [pickMode]);

  // Toggle global pick flag so Graphics can know to capture clicks
  useEffect(()=> {
    if (pickMode) window.__ABACWS_PICK_POSITION__ = true; else delete window.__ABACWS_PICK_POSITION__;
  }, [pickMode]);

  const validate = useCallback(()=> {
    if (!name.trim()) return 'Name required';
    if (Number.isNaN(Number(floor))) return 'Floor invalid';
    const { x,y,z } = position; if ([x,y,z].some(v => typeof v !== 'number' || Number.isNaN(v))) return 'Position invalid';
    return null;
  }, [name, floor, position]);

  const submit = async (e) => {
    e.preventDefault();
    const ve = validate();
    if (ve) { setClientError(ve); return; }
    const payload = { name: name.trim(), type: type.trim() || undefined, floor: Number(floor), position, pinned };
    const res = await createDevice(payload);
    if (res.ok) { onCreated?.(res.device); onClose?.(); }
  };

  if (!open) return null;

  return (
    <div style={backdropStyle} onMouseDown={(e)=> { if(e.target === e.currentTarget) onClose?.(); }}>
      <form style={modalStyle} onSubmit={submit} onKeyDown={(e)=> { if(e.key==='Escape'){ e.stopPropagation(); onClose?.(); } }}>
        <h2 style={{margin:'0 0 8px',fontSize:16}}>Create Device</h2>
        <div style={row}><label>Name<input value={name} onChange={e=> setName(e.target.value)} required/></label></div>
        <div style={row}><label>Type<input value={type} onChange={e=> setType(e.target.value)} placeholder='(optional)'/></label></div>
        <div style={row}><label>Floor<input type='number' value={floor} onChange={e=> setFloor(e.target.value)} required/></label></div>
        <fieldset style={{border:'1px solid #374151',padding:8,borderRadius:6}}>
          <legend style={{fontSize:12}}>Position (x,y,z)</legend>
          <div style={{display:'flex',gap:8}}>
            <label style={coordLabel}>X<input type='number' value={position.x} onChange={e=> setPosition(p=> ({...p,x:Number(e.target.value)}))}/></label>
            <label style={coordLabel}>Y<input type='number' value={position.y} onChange={e=> setPosition(p=> ({...p,y:Number(e.target.value)}))}/></label>
            <label style={coordLabel}>Z<input type='number' value={position.z} onChange={e=> setPosition(p=> ({...p,z:Number(e.target.value)}))}/></label>
          </div>
          {!fromScene && (
            <button type='button' onClick={()=> setPickMode(p=>!p)} style={pickBtnStyle}>{pickMode? 'Click ground… (ESC to cancel)':'Pick from 3D'}</button>
          )}
          {fromScene && <div style={{fontSize:10,color:'#9ca3af',marginTop:6}}>Picked by double‑click at these coordinates.</div>}
        </fieldset>
        <label style={{display:'flex',alignItems:'center',gap:6,fontSize:12,marginTop:8}}>
          <input type='checkbox' checked={pinned} onChange={e=> setPinned(e.target.checked)}/> Pinned
        </label>
        {clientError && <div style={errStyle}>{clientError}</div>}
        {error && !clientError && <div style={errStyle}>{error}</div>}
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:8,marginTop:12}}>
          <div style={{fontSize:10,color:'#6b7280',maxWidth:180}}>{fromScene? 'You can adjust coords or floor before saving.' : 'Tip: double‑click in 3D to prefill coordinates.'}</div>
          <div style={{display:'flex',gap:8}}>
            <button type='button' onClick={()=> { onClose?.(); }} style={secondaryBtn}>Cancel</button>
            <button type='submit' disabled={loading} style={primaryBtn}>{loading? 'Creating…':'Create'}</button>
          </div>
        </div>
      </form>
    </div>
  );
}

const backdropStyle = { position:'fixed',inset:0,background:'rgba(0,0,0,.55)',display:'flex',alignItems:'center',justifyContent:'center',zIndex:10000 };
const modalStyle = { width:380,maxWidth:'90%',background:'#111827',border:'1px solid #374151',borderRadius:8,padding:16,color:'#fff',font:'13px system-ui',boxShadow:'0 8px 28px rgba(0,0,0,.5)' };
const row = { marginBottom:8,display:'flex',flexDirection:'column',gap:4,fontSize:12 };
const coordLabel = { display:'flex',flexDirection:'column',fontSize:11,flex:1 };
const primaryBtn = { background:'#10b981',color:'#fff',border:'none',padding:'6px 14px',borderRadius:4,cursor:'pointer',fontSize:12 };
const secondaryBtn = { background:'#374151',color:'#fff',border:'none',padding:'6px 14px',borderRadius:4,cursor:'pointer',fontSize:12 };
const pickBtnStyle = { marginTop:8,background:'#2563eb',color:'#fff',border:'none',padding:'4px 10px',borderRadius:4,cursor:'pointer',fontSize:11 };
const errStyle = { background:'#7f1d1d',color:'#fff',padding:'6px 8px',borderRadius:4,fontSize:11,marginTop:8 };
