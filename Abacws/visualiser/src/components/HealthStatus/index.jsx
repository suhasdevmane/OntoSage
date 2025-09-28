import { useState } from 'react';
import { useHealth } from '../../hooks';
import { toggleDatastore } from '../../hooks/useHealth';
import './style.scss';

export function HealthStatus() {
  const health = useHealth(8000);
  const db = health?.db;
  const [apiKey, setApiKey] = useState('');
  const [busy, setBusy] = useState(false);
  const forcedDisabled = db?.status === 'disabled';

  async function handleToggle() {
    if (!db) return;
    setBusy(true);
    try {
      await toggleDatastore(db.status !== 'disabled', apiKey || undefined);
    } catch (e) { /* swallow */ }
    setBusy(false);
  }

  return (
    <div className="healthstatus">
      <div className="row">
        <span className="label">API:</span>
        <span className={`value ${health?.status || 'unknown'}`}>{health?.status || '...'}</span>
      </div>
      <div className="row">
        <span className="label">DB Engine:</span>
        <span className="value">{db?.engine || 'n/a'}</span>
      </div>
      <div className="row">
        <span className="label">DB Status:</span>
        <span className={`value ${db?.status || 'unknown'}`}>{db?.status || '...'}</span>
      </div>
      <div className="row">
        <input placeholder="API Key" type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} />
        <button disabled={busy || !db} onClick={handleToggle}>{db?.status === 'disabled' ? 'Enable DB' : 'Disable DB'}</button>
      </div>
    </div>
  );
}