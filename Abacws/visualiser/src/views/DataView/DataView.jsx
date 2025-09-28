import "./DataView.scss";
import { DeviceDetails, FloorSelector, GraphContainer, QueryPanel, BulkExportPanel } from "./components/index.js";
import { DeviceCreateModal } from '../../components';
import { useBulkHistoryExport } from '../../hooks';
import { DataPanel } from '../../components/index.js';
import { useDeviceData, useDeviceHistory, useDeviceInfo } from "../../hooks/index.js";
import { useState, useEffect } from "react";
import { useSelectedDevice, useSelectedFloor } from "../../three/index.js";
import { useTimeContext, TIME_PRESETS } from '../../hooks';

export function DataView({ hidden }) {
  const [tabIndex, setTabIndex] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [createPos, setCreatePos] = useState(null);

  // Listen for 3D scene double‑click create requests
  useEffect(()=> {
    const handler = (e) => {
      const pos = e.detail?.position;
      if(pos) {
        setCreatePos(pos);
        setCreateOpen(true);
      }
    };
    window.addEventListener('abacws:device-create-request', handler);
    return () => window.removeEventListener('abacws:device-create-request', handler);
  }, []);

  const deviceName = useSelectedDevice();
  const [floor, setFloor] = useSelectedFloor();

  const deviceInfo = useDeviceInfo(deviceName);
  const deviceData = useDeviceData(deviceName);
  const deviceHistory = useDeviceHistory(deviceName);

  const [graphOptions, setGraphOptions] = useState({ deviceName: undefined, field: undefined });
  const className = hidden ? "data-container hidden" : "data-container";
  const time = useTimeContext();
  const bulk = useBulkHistoryExport();

  function TimeControls() {
    if(!time) return null;
    const { mode, setMode, relativeMs, setRelativeMs, from, to, setRange, live } = time;
    return (
      <div style={{display:'flex',flexWrap:'wrap',gap:6,alignItems:'center',margin:'6px 0 10px',fontSize:12}}>
        <div style={{display:'flex',gap:4}}>
          <button onClick={()=> setMode('relative')} style={btnStyle(mode==='relative')}>Window</button>
          <button onClick={()=> setMode('range')} style={btnStyle(mode==='range')}>Range</button>
          <button onClick={()=> setMode('live')} style={btnStyle(mode==='live')}>Live</button>
        </div>
        {mode==='relative' || mode==='live' ? (
          <div style={{display:'flex',gap:4,flexWrap:'wrap'}}>
            {TIME_PRESETS.map(p => (
              <button key={p.label} onClick={()=> setRelativeMs(p.ms)} style={chipStyle(relativeMs===p.ms)}>{p.label}</button>
            ))}
          </div>
        ) : null}
        {mode==='range' && (
          <div style={{display:'flex',gap:4,flexWrap:'wrap'}}>
            <label style={{display:'flex',flexDirection:'column',fontSize:10}}>From
              <input type="datetime-local" value={toLocalInput(from)} onChange={e=> setRange(r=> ({...r, from: new Date(e.target.value).getTime()}))} />
            </label>
            <label style={{display:'flex',flexDirection:'column',fontSize:10}}>To
              <input type="datetime-local" value={toLocalInput(to)} onChange={e=> setRange(r=> ({...r, to: new Date(e.target.value).getTime()}))} />
            </label>
          </div>
        )}
        {live && <span style={{color:'#10b981',fontSize:11}}>Live updating…</span>}
      </div>
    );
  }

  function btnStyle(active){
    return {padding:'4px 8px',cursor:'pointer',background: active? '#374151':'#1f2937',border:'1px solid #374151',color:'#fff',fontSize:11,borderRadius:4};
  }
  function chipStyle(active){
    return {padding:'3px 6px',cursor:'pointer',background: active? '#2563eb':'#1e3a8a',border:'none',color:'#fff',fontSize:11,borderRadius:4};
  }
  function toLocalInput(ts){
    const d = new Date(ts); const off = d.getTimezoneOffset(); const local = new Date(d.getTime()-off*60000); return local.toISOString().slice(0,16);
  }

  return (
    <>
    <div className={className}>
      <article className="data-panel">
        <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:12}}>
          <h1 style={{margin:0}}>Abacws Data Visualiser</h1>
          <span style={{fontSize:11,color:'#9ca3af'}}>Double‑click in 3D space to add a device</span>
        </div>
        <FloorSelector current={floor} onSelect={(i) => { setFloor(i); }} />
        <div className="tabs">
          <div className="selectors">
            <div className={tabIndex === 0 ? "selector active" : "selector"} onClick={() => { setTabIndex(0); }}>Data</div>
            <div className={tabIndex === 1 ? "selector active" : "selector"} onClick={() => { setTabIndex(1); }}>Query</div>
          </div>
          <div className={tabIndex === 0 ? "tab active" : "tab"}>
            <TimeControls />
            <DeviceDetails onViewHistory={(deviceName, field) => { setGraphOptions({ deviceName, field }); }} device={deviceInfo} data={deviceData} />
            <GraphContainer history={deviceHistory} options={graphOptions} />
            <div style={{marginTop:12}}>
              <h2 style={{fontSize:14,margin:'12px 0 4px'}}>External Time‑Series</h2>
              <DataPanel deviceName={deviceName} />
            </div>
            <BulkExportPanel
              onRequestExport={(cfg)=> bulk.runExport(cfg)}
              running={bulk.running}
              progress={bulk.progress}
              total={bulk.total}
              strategy={bulk.strategy}
              onCancel={bulk.cancel}
            />
            {bulk.error && <div style={{color:'#ef4444',fontSize:11,marginTop:4}}>Error: {bulk.error}</div>}
          </div>
          <div className={tabIndex === 1 ? "tab active" : "tab"}>
            <QueryPanel />
          </div>
        </div>
      </article>
    </div>
    <DeviceCreateModal open={createOpen} initialPosition={createPos} onClose={()=> { setCreateOpen(false); setCreatePos(null); }} onCreated={(d)=> { /* could auto-select; leave for now */ }} />
    </>
  );
}

// Listen globally for double-click create requests
export function useCreateDeviceFromScene(setCreateOpen, setCreatePos) {
  useEffect(()=> {
    const handler = (e) => {
      const pos = e.detail?.position; if(!pos) return;
      setCreatePos(pos);
      setCreateOpen(true);
    };
    window.addEventListener('abacws:device-create-request', handler);
    return () => window.removeEventListener('abacws:device-create-request', handler);
  }, [setCreateOpen, setCreatePos]);
}
