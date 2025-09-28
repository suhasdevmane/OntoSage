import React, { useMemo } from 'react';
import './DeviceDrawer.scss';
import { useSelectedDevice } from '../../three';
import { useDeviceInfo, useDeviceData, useDeviceHistory, useLatestValues, useTimeContext, useTimeSeries, useMappings } from '../../hooks';
import { Sparkline } from './Sparkline';

interface DrawerProps { onClose?: () => void; }

export const DeviceDrawer: React.FC<DrawerProps> = ({ onClose }) => {
  const name = useSelectedDevice();
  const info = useDeviceInfo(name);
  const latestLocal = useDeviceData(name); // internal payload
  const history = useDeviceHistory(name); // internal history aligned to TimeContext
  const latestExternal = useLatestValues(20000); // external latest values (all devices)
  const time = useTimeContext();
  const mappings = useMappings();
  const externalEntry = name ? latestExternal[name] : undefined;

  const sparkPoints = useMemo(() => {
    if(!history || !Array.isArray(history)) return undefined;
    const sample = history[0] || {};
    const key = Object.keys(sample).find(k => k !== 'timestamp' && typeof sample[k] === 'number');
    if(!key) return undefined;
    return history.slice().reverse().map(d => ({ timestamp: d.timestamp, value: d[key] }));
  }, [history]);

  const deviceMappings = useMemo(() => {
    if(!name || !Array.isArray(mappings)) return [];
    return mappings.filter(m => m.device_name === name);
  }, [mappings, name]);

  if(!name) return null;

  const pinned = info?.pinned;
  const headerTitle = info?.name || name;
  const modeLabel = time?.mode === 'live' ? 'Live' : time?.mode === 'range' ? 'Range' : 'Window';

  return (
    <aside className="device-drawer" aria-labelledby="drawer-title">
      <header>
        <div className="title-row">
          <h2 id="drawer-title" style={{fontSize:16,margin:0}}>{headerTitle}</h2>
          <div style={{display:'flex',gap:6}}>
            <button className="icon-btn" onClick={onClose}>Close</button>
          </div>
        </div>
        <div className="meta">
          <span>Type: {info?.type || '—'}</span>
          <span>Floor: {info?.floor ?? '—'}</span>
          <span>{pinned ? 'Pinned' : 'Movable'}</span>
          <span>{modeLabel}</span>
        </div>
      </header>
      <section className="section">
        <h3 style={{fontSize:13,margin:'0 0 4px'}}>Latest Internal</h3>
        {latestLocal ? (
          <table className="metrics-table">
            <thead><tr><th>Field</th><th>Value</th></tr></thead>
            <tbody>
              {Object.entries(latestLocal).map(([k,v]) => k === 'timestamp' ? null : (
                <tr key={k}><td>{k}</td><td>{typeof v === 'object' && v?.value !== undefined ? v.value : String(v)}</td></tr>
              ))}
            </tbody>
          </table>
        ) : <div className="empty">No data</div>}
        <div style={{marginTop:6,fontSize:10,opacity:.6}}>
          {latestLocal?.timestamp ? new Date(latestLocal.timestamp).toLocaleString() : ''}
        </div>
      </section>
      <section className="section">
        <h3 style={{fontSize:13,margin:'0 0 4px'}}>External Mapping</h3>
        {deviceMappings.length ? (
          <div style={{display:'flex',flexWrap:'wrap'}}>
            {deviceMappings.map(m => (
              <span className="mapping-badge" key={m.id}>#{m.id} {m.table_name}:{m.primary_value_column || m.value_columns?.[0]}</span>
            ))}
          </div>
        ) : <div className="empty">No mapping</div>}
        {externalEntry ? (
          <table className="metrics-table" style={{marginTop:6}}>
            <thead><tr><th>Field</th><th>Val</th></tr></thead>
            <tbody>
              {Object.entries(externalEntry.values || {}).map(([k,v]) => (
                <tr key={k}><td>{k}</td><td>{String(v)}</td></tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {externalEntry?.timestamp && <div style={{marginTop:6,fontSize:10,opacity:.6}}> {new Date(externalEntry.timestamp).toLocaleString()} </div>}
      </section>
      <section className="section">
        <h3 style={{fontSize:13,margin:'0 0 4px'}}>History Sparkline</h3>
        <div className="sparkline-wrapper">
          <Sparkline points={sparkPoints} />
        </div>
      </section>
      <footer>
        <button onClick={()=> { /* future: toggle pin via PATCH */ }}>Pin/Unpin</button>
        <button onClick={()=> { window.dispatchEvent(new CustomEvent('focus-device',{ detail:{ name } })); }}>Focus</button>
        <button onClick={()=> { onClose?.(); }}>Close</button>
      </footer>
    </aside>
  );
};
