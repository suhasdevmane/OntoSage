import React, { useState, useEffect } from 'react';

export default function SystemTab({ api, headers }) {
  const [env, setEnv] = useState([]);
  const [aiConfig, setAiConfig] = useState(null);
  const [edits, setEdits] = useState({});
  const [envMsg, setEnvMsg] = useState('');
  const [restarting, setRestarting] = useState(false);

  useEffect(() => {
    fetch(`${api}/api/v1/admin/env`, { headers })
      .then(r=>r.json()).then(d => setEnv(d.data?.env||[])).catch(()=>{});
    fetch(`${api}/api/v1/admin/ai-config`, { headers })
      .then(r=>r.json()).then(d => setAiConfig(d.data)).catch(()=>{});
  }, [api, headers]);

  const saveEnv = async () => {
    const r = await fetch(`${api}/api/v1/admin/env`, {
      method:'PUT', headers, body: JSON.stringify({ changes: edits })
    });
    const d = await r.json();
    setEnvMsg(d.success ? `Saved ${d.data?.updated?.length||0} keys. Restart required.` : d.error);
    setEdits({});
  };

  const doRestart = async () => {
    if (!window.confirm('Restart the orchestrator now? All in-flight requests will fail.')) return;
    setRestarting(true);
    await fetch(`${api}/api/v1/admin/restart`, { method:'POST', headers });
    setTimeout(() => setRestarting(false), 8000);
  };

  return (
    <div>
      <div className="row g-4">
        <div className="col-12 col-lg-8">
          <h5>.env Editor <small className="text-muted fs-6">(secrets are masked)</small></h5>
          {envMsg && <div className="alert alert-info py-1 mb-2">{envMsg}</div>}
          <div style={{maxHeight:420,overflowY:'auto'}}>
            <table className="table table-sm table-bordered">
              <thead className="table-light"><tr><th style={{width:'35%'}}>Key</th><th>Value</th></tr></thead>
              <tbody>
                {env.map(row => (
                  <tr key={row.key}>
                    <td style={{fontFamily:'monospace',fontSize:12}}>{row.key}</td>
                    <td>
                      <input className="form-control form-control-sm font-monospace"
                        type={row.is_secret ? 'password' : 'text'}
                        defaultValue={row.value}
                        onChange={e => setEdits(prev => ({...prev, [row.key]: e.target.value}))} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button className="btn btn-sm btn-primary mt-2" onClick={saveEnv}
            disabled={Object.keys(edits).length===0}>
            Save {Object.keys(edits).length > 0 ? `(${Object.keys(edits).length} change${Object.keys(edits).length>1?'s':''})` : ''}
          </button>
        </div>
        <div className="col-12 col-lg-4">
          {aiConfig && (
            <div className="card mb-3">
              <div className="card-header"><strong>AI Configuration</strong></div>
              <div className="card-body" style={{fontSize:13}}>
                <p><strong>Model Provider:</strong> {aiConfig.model_provider}</p>
                <p><strong>Embedding Provider:</strong> {aiConfig.embedding_provider}</p>
                <p><strong>Ollama Model:</strong> {aiConfig.ollama_model||'-'}</p>
                <p><strong>OpenAI Model:</strong> {aiConfig.openai_model||'-'}</p>
                <p><strong>OpenAI Key Set:</strong> {aiConfig.openai_api_key_set ? 'Yes' : 'No'}</p>
              </div>
            </div>
          )}
          <div className="card border-danger">
            <div className="card-header bg-danger text-white"><strong>Orchestrator Restart</strong></div>
            <div className="card-body">
              <p className="small text-muted">Required after .env changes. Docker restart policy keeps it alive.</p>
              <button className="btn btn-danger btn-sm w-100" onClick={doRestart} disabled={restarting}>
                {restarting ? 'Restarting...' : 'Restart Orchestrator'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
