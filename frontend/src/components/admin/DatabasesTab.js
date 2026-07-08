import React, { useState, useEffect, useCallback } from 'react';

// CSV format: local_id,brick_class,location,uuid[,unit,label]  (BACnet → manual TTL in OntologyTab)
const CSV_HELP = `# Required: local_id,brick_class,location,uuid  Optional: unit,label
# BACnet sensors: use OntologyTab → manual TTL upload (BACnetReference pattern)
# uuid must match the actual row identifier in the target database.
local_id,brick_class,location,uuid,unit,label
Zone5_Temp,brick:Temperature_Sensor,bldg:Floor5,8f541ba4-c437-43ba-ba1d-5c946583fe54,unit:DEG_C,Zone 5 Temperature
Zone5_CO2,brick:CO2_Sensor,bldg:Floor5,38b5fa0e-407e-4a23-8800-6ec4f6d60785,unit:PPM,Zone 5 CO2`;

export default function DatabasesTab({ api, headers }) {
  const [dbs, setDbs] = useState([]);
  const [counts, setCounts] = useState({});
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');
  const [form, setForm] = useState({ key:'', type:'mysql_narrow', host:'', port:'3306', user:'', password:'', database:'', table:'' });
  const [testResult, setTestResult] = useState(null);
  const [introspectResult, setIntrospectResult] = useState(null);
  const [selectedDb, setSelectedDb] = useState('');
  const [csvText, setCsvText] = useState(CSV_HELP);
  const [csvResult, setCsvResult] = useState(null);

  const loadDbs = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${api}/api/v1/admin/databases`, { headers });
      const d = await r.json();
      setDbs(d.data?.databases || []);
      const cr = await fetch(`${api}/api/v1/admin/databases/sensor-counts`, { headers });
      const cd = await cr.json();
      setCounts(cd.data?.counts || {});
    } finally {
      setLoading(false);
    }
  }, [api, headers]);

  useEffect(() => { loadDbs(); }, [loadDbs]);

  const handleTest = async () => {
    setTestResult(null);
    const r = await fetch(`${api}/api/v1/admin/databases/test`, {
      method: 'POST', headers, body: JSON.stringify({ ...form, port: String(form.port) })
    });
    setTestResult(await r.json());
  };

  const handleIntrospect = async () => {
    setIntrospectResult(null);
    const r = await fetch(`${api}/api/v1/admin/databases/introspect`, {
      method: 'POST', headers, body: JSON.stringify({ ...form, port: String(form.port) })
    });
    setIntrospectResult(await r.json());
  };

  const handleAdd = async () => {
    setMsg('');
    const r = await fetch(`${api}/api/v1/admin/databases`, {
      method: 'POST', headers, body: JSON.stringify(form)
    });
    const d = await r.json();
    setMsg(d.success ? `Added '${form.key}'. Restart the orchestrator for it to take effect.` : `Error: ${d.error}`);
    if (d.success) loadDbs();
  };

  const handleDelete = async (key) => {
    if (!window.confirm(`Delete connection '${key}'?`)) return;
    const r = await fetch(`${api}/api/v1/admin/databases/${key}`, { method: 'DELETE', headers });
    const d = await r.json();
    setMsg(d.success ? `Deleted '${key}'` : `Error: ${d.error}`);
    loadDbs();
  };

  const handleRegisterCsv = async () => {
    setCsvResult(null);
    const r = await fetch(`${api}/api/v1/admin/databases/${selectedDb}/sensors/csv`, {
      method: 'POST', headers, body: JSON.stringify({ csv: csvText })
    });
    const d = await r.json();
    setCsvResult(d);
    if (d.success) loadDbs();
  };

  const f = (k) => (e) => setForm(prev => ({ ...prev, [k]: e.target.value }));

  return (
    <div>
      {msg && <div className={`alert py-2 alert-${msg.startsWith('Error') ? 'danger' : 'success'} mb-3`}>{msg}</div>}
      <h5>Connections</h5>
      <div className="table-responsive mb-4">
        <table className="table table-sm table-bordered">
          <thead className="table-light">
            <tr><th>Key</th><th>Type</th><th>Host</th><th>Source</th><th>Active</th><th>Sensors in GraphDB</th><th></th></tr>
          </thead>
          <tbody>
            {dbs.length === 0 && <tr><td colSpan={7} className="text-center text-muted">No connections</td></tr>}
            {dbs.map(db => (
              <tr key={db.key}>
                <td><code>{db.key}</code></td>
                <td>{db.type}</td>
                <td>{db.fields?.host || '-'}</td>
                <td><span className={`badge bg-${db.source==='curated'?'secondary':'info'}`}>{db.source}</span></td>
                <td><span className={`badge bg-${db.active?'success':'warning'}`}>{db.active?'Yes':'No'}</span></td>
                <td className="text-end">{counts[db.key] ?? '-'}</td>
                <td>
                  {db.source === 'custom' && (
                    <button className="btn btn-xs btn-outline-danger py-0 px-1" style={{fontSize:11}}
                      onClick={() => handleDelete(db.key)}>Del</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className="btn btn-sm btn-outline-secondary" onClick={loadDbs} disabled={loading}>Refresh</button>
      </div>

      <div className="row g-4">
        <div className="col-12 col-lg-6">
          <div className="card">
            <div className="card-header"><strong>Add External Database Connection</strong></div>
            <div className="card-body">
              {[
                ['key', 'Registry Key (e.g. bldg2_mysql)', 'text'],
                ['host', 'Host', 'text'],
                ['port', 'Port', 'text'],
                ['user', 'User', 'text'],
                ['password', 'Password', 'password'],
                ['database', 'Database Name', 'text'],
                ['table', 'Table (narrow adapter only)', 'text'],
              ].map(([k, label, type]) => (
                <div className="mb-2" key={k}>
                  <label className="form-label small mb-0">{label}</label>
                  <input className="form-control form-control-sm" type={type} value={form[k]}
                    onChange={f(k)} />
                </div>
              ))}
              <div className="mb-2">
                <label className="form-label small mb-0">Type</label>
                <select className="form-select form-select-sm" value={form.type} onChange={f('type')}>
                  {['mysql', 'mysql_narrow', 'postgresql', 'timescaledb'].map(t =>
                    <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div className="d-flex gap-2 flex-wrap">
                <button className="btn btn-sm btn-outline-secondary" onClick={handleTest}>Test Connection</button>
                <button className="btn btn-sm btn-outline-info" onClick={handleIntrospect}>Introspect Tables</button>
                <button className="btn btn-sm btn-primary" onClick={handleAdd}>Add Connection</button>
              </div>
              {testResult && (
                <div className={`alert py-1 mt-2 alert-${testResult.success ? 'success' : 'danger'}`} style={{fontSize:12}}>
                  {testResult.success ? `Connected (${testResult.data?.latency_ms}ms)` : `Error: ${testResult.error}`}
                </div>
              )}
              {introspectResult?.success && (
                <div className="mt-2" style={{maxHeight:120,overflowY:'auto',fontSize:11}}>
                  {(introspectResult.data?.tables||[]).map(t => (
                    <div key={t.name}><strong>{t.name}</strong>: {t.columns.map(c=>c.name).join(', ')}</div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="col-12 col-lg-6">
          <div className="card">
            <div className="card-header"><strong>Register Sensors (CSV to GraphDB Triples)</strong></div>
            <div className="card-body">
              <p className="small text-muted mb-2">
                After adding a DB, register its sensors so SPARQL can find them.
                Each row becomes Brick triples in GraphDB. UUIDs must match real rows in the DB.
              </p>
              <div className="mb-2">
                <label className="form-label small mb-0">Target connection</label>
                <select className="form-select form-select-sm" value={selectedDb}
                  onChange={e => setSelectedDb(e.target.value)}>
                  <option value="">- select a connection -</option>
                  {dbs.map(db => <option key={db.key} value={db.key}>{db.key}</option>)}
                </select>
              </div>
              <label className="form-label small mb-0">CSV — required: local_id,brick_class,location,uuid — optional: unit,label</label>
              <textarea className="form-control font-monospace mb-2" rows={8} value={csvText}
                onChange={e => setCsvText(e.target.value)} style={{fontSize:11}} />
              <button className="btn btn-sm btn-primary" disabled={!selectedDb || !csvText}
                onClick={handleRegisterCsv}>
                Register Sensors in GraphDB
              </button>
              {csvResult && (
                <div className={`alert py-1 mt-2 alert-${csvResult.success ? 'success' : 'danger'}`} style={{fontSize:12}}>
                  {csvResult.success
                    ? `Registered ${csvResult.data?.points} sensors for '${selectedDb}'`
                    : `Error: ${csvResult.error}`}
                  {csvResult.data?.parse_warnings?.length > 0 && (
                    <div className="mt-1 text-warning">Warnings: {csvResult.data.parse_warnings.join('; ')}</div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
