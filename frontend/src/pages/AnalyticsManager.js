import React, { useEffect, useState } from 'react';
import SensorSelector from '../components/SensorSelector';
import analyticsApi, { buildSamplePayload } from '../api/analyticsApi';

const API_BASE = 'http://localhost:8080'; // adjust if gateway differs

export default function AnalyticsManager() {
  const [functions, setFunctions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [validating, setValidating] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [testError, setTestError] = useState('');
  const [deciderReloadMsg, setDeciderReloadMsg] = useState('');

  // New function form state
  const [newFn, setNewFn] = useState({
    name: '',
    description: '',
    patterns: '', // comma separated
  });
  const [params, setParams] = useState([]); // {name,type,default,description}
  const [previewCode, setPreviewCode] = useState('');
  const [selectedSensors, setSelectedSensors] = useState([]);

  const [testPayload, setTestPayload] = useState('{\n  "seriesA": [{"timestamp":"2025-01-01T00:00:00","reading_value":10},{"timestamp":"2025-01-01T01:00:00","reading_value":12}]\n}');
  const [testParams, setTestParams] = useState('');

  const loadFunctions = async () => {
    setLoading(true); setError('');
    try {
      try {
        const data = await analyticsApi.listFunctions();
        setFunctions(data.functions || []);
      } catch (err) {
        setError(err.message || 'Failed to load functions');
      }
    } catch (e) {
      setError(e.message);
    } finally { setLoading(false); }
  };

  useEffect(() => { loadFunctions(); }, []);

  const addParam = () => {
    setParams(p => [...p, { name: '', type: 'float', default: '', description: '' }]);
  };
  const updateParam = (idx, key, value) => {
    setParams(p => p.map((row,i) => i===idx ? { ...row, [key]: value } : row));
  };
  const removeParam = (idx) => setParams(p => p.filter((_,i)=>i!==idx));

  const buildPreview = () => {
    const patternsList = newFn.patterns.split(',').map(s=>s.trim()).filter(Boolean);
    const extras = params.filter(p=>p.name).map(p=>({name:p.name, default:p.default||undefined, type:p.type, description:p.description}));
    // Minimal synthetic representation; backend will generate final file
    const paramSig = extras.map(p => p.default ? `${p.name}=${JSON.stringify(p.default)}` : p.name).join(', ');
    const docParams = extras.map(p => `    - ${p.name} (${p.type}): ${p.description}`).join('\n');
    const code = `@analytics_function(patterns=${JSON.stringify(patternsList)}, description=${JSON.stringify(newFn.description)})\n` +
`def ${newFn.name}(sensor_data${paramSig? ', ' + paramSig: ''}):\n` +
`    """Auto-created analytics function.\n\nParameters:\n${docParams}\n"""\n` +
`    flat = _aggregate_flat(sensor_data)\n    if not flat: return {'error':'No data'}\n    first_key = next(iter(flat.keys()))\n    df = _df_from_readings(flat[first_key])\n    if df.empty: return {'error':'Empty series'}\n    return {'series': first_key, 'mean': float(df['reading_value'].mean())}`;
    setPreviewCode(code);
  };

  useEffect(buildPreview, [newFn, params]);

  const validate = async () => {
    setValidating(true); setError('');
    try {
  const data = await analyticsApi.validateFunction(previewCode);
  if (!data.ok) setError(data.message || 'Validation failed'); else setError('');
    } catch (e) { setError(e.message); } finally { setValidating(false); }
  };

  const submit = async () => {
    setCreating(true); setError(''); setDeciderReloadMsg('');
    try {
      const payload = {
        name: newFn.name.trim(),
        description: newFn.description.trim(),
        patterns: newFn.patterns.split(',').map(s=>s.trim()).filter(Boolean),
        parameters: params.filter(p=>p.name).map(p=>({ name: p.name.trim(), type: p.type || 'Any', default: p.default!==''? p.default: undefined, description: p.description }))
      };
      const data = await analyticsApi.addFunction(payload);
      if (data.ok) {
        setShowCreate(false);
        setNewFn({ name:'', description:'', patterns:''});
        setParams([]);
        setPreviewCode('');
        await loadFunctions();
        if (data.decider_reloaded) setDeciderReloadMsg('Decider rules reloaded');
      } else {
        setError(data.error || 'Create failed');
      }
    } catch (e) { setError(e.message); } finally { setCreating(false); }
  };

  const runTest = async () => {
    setTestError(''); setTestResult(null);
    let payloadObj = {};
    let paramsObj = {};
    try { payloadObj = JSON.parse(testPayload); } catch (e) { setTestError('Invalid JSON payload'); return; }
    if (testParams.trim()) {
      try { paramsObj = JSON.parse(testParams); } catch (e) { setTestError('Invalid JSON params'); return; }
    }
    try {
      const data = await analyticsApi.testRun({ functionName: testResult?.functionUnderTest || selectedFunctionName(), payload: payloadObj, params: paramsObj });
      if (data.ok) {
        setTestResult({ raw: data.result, functionUnderTest: selectedFunctionName() });
      } else {
        setTestError(data.error || 'Test failed');
      }
    } catch (e) { setTestError(e.message); }
  };

  const [selectedName, setSelectedName] = useState('');
  const selectedFunctionName = () => selectedName || (functions[0]?.name || '');
  const selectedFn = functions.find(f => f.name === selectedFunctionName());

  const renderList = () => (
    <div className="card mt-3">
      <div className="card-body">
        <div className="d-flex justify-content-between align-items-center">
          <h5 className="card-title mb-0">Registered Analytics Functions</h5>
          <div>
            <button className="btn btn-sm btn-outline-primary me-2" onClick={loadFunctions} disabled={loading}>Refresh</button>
            <button className="btn btn-sm btn-success" onClick={() => setShowCreate(s=>!s)}>{showCreate? 'Close' : 'New Function'}</button>
          </div>
        </div>
        {loading && <div className="mt-2 text-muted">Loading…</div>}
        {error && <div className="alert alert-danger mt-2 mb-0">{error}</div>}
        {!loading && !error && (
          <div className="table-responsive mt-3" style={{maxHeight: 320, overflow: 'auto'}}>
            <table className="table table-sm table-hover align-middle">
              <thead className="table-light"><tr><th>Name</th><th>Patterns</th><th>Description</th><th>Params</th></tr></thead>
              <tbody>
                {functions.map(fn => (
                  <tr key={fn.name} className={fn.name===selectedFunctionName()? 'table-primary':''} style={{cursor:'pointer'}} onClick={()=>setSelectedName(fn.name)}>
                    <td><code>{fn.name}</code></td>
                    <td className="small" style={{maxWidth:160}}>{fn.patterns.join(', ')}</td>
                    <td className="small" style={{maxWidth:240}}>{fn.description}</td>
                    <td className="small">{(fn.parameters||[]).map(p=>p.name).join(', ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {selectedFn && (
          <div className="mt-3">
            <h6 className="fw-bold mb-2">Function Detail</h6>
            <div className="small"><strong>Patterns:</strong> {selectedFn.patterns.join(', ') || '—'}</div>
            <div className="small"><strong>Description:</strong> {selectedFn.description || '—'}</div>
            <div className="small mt-1"><strong>Parameters:</strong></div>
            <ul className="small mb-0">
              {(selectedFn.parameters||[]).map(p => (
                <li key={p.name}><code>{p.name}</code>{p.type? `: ${p.type}`:''}{p.default !== undefined && p.default !== null ? ` = ${String(p.default)}`:''} {p.description? ` – ${p.description}`:''}</li>
              ))}
              {(!selectedFn.parameters || selectedFn.parameters.length===0) && <li>None</li>}
            </ul>
          </div>
        )}
      </div>
    </div>
  );

  const renderCreate = () => !showCreate ? null : (
    <div className="card mt-3">
      <div className="card-body">
        <h5 className="card-title">Create Analytics Function</h5>
        <div className="row g-3">
          <div className="col-md-4">
            <label className="form-label">Name</label>
            <input className="form-control" value={newFn.name} onChange={e=>setNewFn({...newFn, name:e.target.value})} placeholder="e.g. room_temperature_delta" />
          </div>
          <div className="col-md-8">
            <label className="form-label">Patterns (comma separated)</label>
            <input className="form-control" value={newFn.patterns} onChange={e=>setNewFn({...newFn, patterns:e.target.value})} placeholder="latest temperature, temperature trend" />
          </div>
          <div className="col-12">
            <label className="form-label">Description</label>
            <textarea className="form-control" rows={2} value={newFn.description} onChange={e=>setNewFn({...newFn, description:e.target.value})} />
          </div>
        </div>
        {/* Sensor selector + sample payload generator */}
        <div className="mt-3">
          <SensorSelector selected={selectedSensors} onChange={setSelectedSensors} />
          <div className="d-flex gap-2 mt-2 align-items-center">
            <button type="button" className="btn btn-sm btn-outline-primary" onClick={()=>{
              const sample = buildSamplePayload(selectedSensors);
              setTestPayload(JSON.stringify(sample, null, 2));
            }} disabled={selectedSensors.length===0}>Generate Sample Payload</button>
            {selectedSensors.length===0 && <span className="text-muted small">Select sensors to build a nested sample payload</span>}
          </div>
        </div>
        <div className="mt-3">
          <div className="d-flex justify-content-between align-items-center mb-2">
            <h6 className="mb-0">Parameters</h6>
            <button className="btn btn-sm btn-outline-secondary" onClick={addParam}>Add Parameter</button>
          </div>
          {params.length === 0 && <div className="text-muted small">No parameters defined.</div>}
          {params.length > 0 && (
            <div className="table-responsive">
              <table className="table table-sm align-middle">
                <thead><tr><th>Name</th><th>Type</th><th>Default</th><th>Description</th><th></th></tr></thead>
                <tbody>
                  {params.map((p,i) => (
                    <tr key={i}>
                      <td><input className="form-control form-control-sm" value={p.name} onChange={e=>updateParam(i,'name',e.target.value)} placeholder="e.g. window_hours" /></td>
                      <td><input className="form-control form-control-sm" value={p.type} onChange={e=>updateParam(i,'type',e.target.value)} placeholder="float" /></td>
                      <td><input className="form-control form-control-sm" value={p.default} onChange={e=>updateParam(i,'default',e.target.value)} placeholder="" /></td>
                      <td><input className="form-control form-control-sm" value={p.description} onChange={e=>updateParam(i,'description',e.target.value)} placeholder="Short description" /></td>
                      <td><button className="btn btn-sm btn-outline-danger" onClick={()=>removeParam(i)}>&times;</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div className="mt-3">
          <div className="d-flex justify-content-between align-items-center mb-2">
            <h6 className="mb-0">Preview & Validate</h6>
            <div className="d-flex gap-2">
              <button className="btn btn-sm btn-outline-primary" onClick={validate} disabled={validating}>Validate</button>
              <button className="btn btn-sm btn-success" onClick={submit} disabled={creating}>Create</button>
            </div>
          </div>
          <pre className="border rounded p-2 bg-light small" style={{maxHeight:240, overflow:'auto'}}>{previewCode || '—'}</pre>
          {(validating || creating) && <div className="small text-muted mt-2">{validating? 'Validating...' : 'Creating...'}</div>}
        </div>
      </div>
    </div>
  );

  const renderTester = () => (
    <div className="card mt-3">
      <div className="card-body">
        <h5 className="card-title">Test Run</h5>
        <div className="row g-3">
          <div className="col-md-4">
            <label className="form-label">Function</label>
            <select className="form-select" value={selectedFunctionName()} onChange={e=>setSelectedName(e.target.value)}>
              {functions.map(fn => <option key={fn.name} value={fn.name}>{fn.name}</option>)}
            </select>
          </div>
          <div className="col-md-4">
            <label className="form-label">Params (JSON)</label>
            <textarea className="form-control" rows={3} value={testParams} onChange={e=>setTestParams(e.target.value)} placeholder='{"window_hours":6}' />
          </div>
          <div className="col-md-4">
            <label className="form-label">Payload (JSON)</label>
            <textarea className="form-control" rows={3} value={testPayload} onChange={e=>setTestPayload(e.target.value)} />
          </div>
        </div>
        <div className="mt-2 d-flex gap-2">
            <button className="btn btn-outline-primary" onClick={runTest}>Run Test</button>
            <button className="btn btn-outline-secondary" onClick={()=>{setTestResult(null); setTestError('');}}>Clear</button>
            <button className="btn btn-outline-warning" onClick={async ()=>{
              try { const res = await fetch(`${API_BASE}/decider/reload`, { method:'POST'}); const d = await res.json(); setDeciderReloadMsg(d.ok? 'Decider reloaded' : 'Reload failed'); } catch(e){ setDeciderReloadMsg('Reload error'); }
            }}>Reload Decider Rules</button>
        </div>
        {deciderReloadMsg && <div className="small text-info mt-2">{deciderReloadMsg}</div>}
        {testError && <div className="alert alert-danger mt-3 mb-0">{testError}</div>}
        {testResult && !testError && (
          <div className="mt-3">
            <h6 className="fw-bold">Result</h6>
            <pre className="border rounded p-2 bg-light small" style={{maxHeight:240, overflow:'auto'}}>{JSON.stringify(testResult.raw, null, 2)}</pre>
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className="container mt-3">
      <h4>Analytics Functions</h4>
      <p className="text-muted small mb-1">Create and test analytics functions dynamically. These map natural language questions via the Decider.</p>
      {renderList()}
      {renderCreate()}
      {renderTester()}
    </div>
  );
}
