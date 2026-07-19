import React, { useState, useEffect } from 'react';

const MASK = '••••••••';

export default function SystemTab({ api, headers }) {
  const [env, setEnv] = useState([]);
  const [aiConfig, setAiConfig] = useState(null);
  const [edits, setEdits] = useState({});
  const [envMsg, setEnvMsg] = useState('');
  const [restarting, setRestarting] = useState(false);

  const [provider, setProvider] = useState('local');
  const [embeddingProvider, setEmbeddingProvider] = useState('local');
  const [ollamaModel, setOllamaModel] = useState('');
  const [ollamaCloudModel, setOllamaCloudModel] = useState('');
  const [ollamaCloudBaseUrl, setOllamaCloudBaseUrl] = useState('');
  const [openaiModel, setOpenaiModel] = useState('');
  const [openaiKey, setOpenaiKey] = useState('');
  const [ollamaCloudKey, setOllamaCloudKey] = useState('');
  const [modelOptions, setModelOptions] = useState([]);
  const [probing, setProbing] = useState(false);
  const [probeMsg, setProbeMsg] = useState('');
  const [aiMsg, setAiMsg] = useState('');
  const [savingAi, setSavingAi] = useState(false);

  const loadAiConfig = () => {
    fetch(`${api}/api/v1/admin/ai-config`, { headers })
      .then(r => r.json())
      .then(d => {
        setAiConfig(d.data);
        if (d.data) {
          setProvider(d.data.model_provider || 'local');
          setEmbeddingProvider(d.data.embedding_provider || 'local');
          setOllamaModel(d.data.ollama_model || '');
          setOllamaCloudModel(d.data.ollama_cloud_model || '');
          setOllamaCloudBaseUrl(d.data.ollama_cloud_base_url || '');
          setOpenaiModel(d.data.openai_model || '');
        }
      })
      .catch(() => {});
  };

  useEffect(() => {
    fetch(`${api}/api/v1/admin/env`, { headers })
      .then(r=>r.json()).then(d => setEnv(d.data?.env||[])).catch(()=>{});
    loadAiConfig();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const probeModels = async (p) => {
    setProbing(true);
    setProbeMsg('');
    try {
      const r = await fetch(`${api}/api/v1/admin/ai-config/test`, {
        method: 'POST', headers, body: JSON.stringify({ provider: p })
      });
      const d = await r.json();
      if (d.success) {
        setModelOptions(d.data?.models || []);
        setProbeMsg(`Reachable — ${(d.data?.models || []).length} model(s) available (${d.data?.latency_ms} ms)`);
      } else {
        setModelOptions([]);
        setProbeMsg(d.error || 'Probe failed');
      }
    } catch (e) {
      setProbeMsg(String(e));
    } finally {
      setProbing(false);
    }
  };

  const saveAiConfig = async () => {
    setSavingAi(true);
    setAiMsg('');
    try {
      const changes = { MODEL_PROVIDER: provider, EMBEDDING_PROVIDER: embeddingProvider };
      if (provider === 'local' && ollamaModel) changes.OLLAMA_MODEL = ollamaModel;
      if (provider === 'cloud') {
        if (ollamaCloudModel) changes.OLLAMA_CLOUD_MODEL = ollamaCloudModel;
        if (ollamaCloudBaseUrl) changes.OLLAMA_CLOUD_BASE_URL = ollamaCloudBaseUrl;
      }
      if (provider === 'openai' && openaiModel) changes.OPENAI_MODEL = openaiModel;
      // API keys are only sent if the admin actually typed one — an empty
      // field must never overwrite an existing key (mirrors the .env
      // editor's MASK convention: untouched secret fields aren't submitted).
      if (openaiKey) changes.OPENAI_API_KEY = openaiKey;
      if (ollamaCloudKey) changes.OLLAMA_CLOUD_API_KEY = ollamaCloudKey;

      const r = await fetch(`${api}/api/v1/admin/env`, {
        method: 'PUT', headers, body: JSON.stringify({ changes })
      });
      const d = await r.json();
      setAiMsg(d.success ? 'Saved. Restart the orchestrator to apply.' : d.error);
      if (d.success) {
        setOpenaiKey('');
        setOllamaCloudKey('');
        loadAiConfig();
      }
    } catch (e) {
      setAiMsg(String(e));
    } finally {
      setSavingAi(false);
    }
  };

  const noOpenAiKey = aiConfig && !aiConfig.openai_api_key_set;

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
                {noOpenAiKey && (
                  <div className="alert alert-warning py-1 mb-2" style={{fontSize:12}}>
                    No OpenAI API key set — <code>MODEL_PROVIDER=openai</code> would
                    auto-fall-back to <code>local</code> at startup.
                  </div>
                )}
                {aiMsg && <div className="alert alert-info py-1 mb-2" style={{fontSize:12}}>{aiMsg}</div>}

                <label className="form-label mb-1"><strong>Model Provider</strong></label>
                <select className="form-select form-select-sm mb-2" value={provider}
                  onChange={e => { setProvider(e.target.value); setModelOptions([]); setProbeMsg(''); }}>
                  {(aiConfig.providers || ['local', 'cloud', 'openai']).map(p => (
                    <option key={p} value={p}>
                      {p === 'local' ? 'local (Ollama, no API costs)' : p === 'cloud' ? 'cloud (Ollama Cloud API)' : 'openai (OpenAI API)'}
                    </option>
                  ))}
                </select>

                {provider === 'local' && (
                  <>
                    <label className="form-label mb-1">Ollama Model</label>
                    <input className="form-control form-control-sm mb-1" list="model-options"
                      value={ollamaModel} onChange={e => setOllamaModel(e.target.value)}
                      placeholder="e.g. gemma4:26b" />
                  </>
                )}

                {provider === 'cloud' && (
                  <>
                    <label className="form-label mb-1">Ollama Cloud Base URL</label>
                    <input className="form-control form-control-sm mb-1"
                      value={ollamaCloudBaseUrl} onChange={e => setOllamaCloudBaseUrl(e.target.value)}
                      placeholder="https://api.ollama.ai/v1" />
                    <label className="form-label mb-1">Ollama Cloud Model</label>
                    <input className="form-control form-control-sm mb-1" list="model-options"
                      value={ollamaCloudModel} onChange={e => setOllamaCloudModel(e.target.value)}
                      placeholder="e.g. gpt-oss:120b-cloud" />
                    <label className="form-label mb-1">Ollama Cloud API Key</label>
                    <input className="form-control form-control-sm mb-1" type="password"
                      value={ollamaCloudKey} onChange={e => setOllamaCloudKey(e.target.value)}
                      placeholder={aiConfig.ollama_cloud_api_key_set ? MASK : 'sk-...'} />
                  </>
                )}

                {provider === 'openai' && (
                  <>
                    <label className="form-label mb-1">OpenAI Model</label>
                    <input className="form-control form-control-sm mb-1" list="model-options"
                      value={openaiModel} onChange={e => setOpenaiModel(e.target.value)}
                      placeholder="e.g. gpt-4o-mini" />
                    <label className="form-label mb-1">OpenAI API Key</label>
                    <input className="form-control form-control-sm mb-1" type="password"
                      value={openaiKey} onChange={e => setOpenaiKey(e.target.value)}
                      placeholder={aiConfig.openai_api_key_set ? MASK : 'sk-...'} />
                  </>
                )}

                <datalist id="model-options">
                  {modelOptions.map(m => <option key={m} value={m} />)}
                </datalist>
                <button className="btn btn-sm btn-outline-secondary mb-2" type="button"
                  onClick={() => probeModels(provider)} disabled={probing}>
                  {probing ? 'Checking...' : 'Test connection / list models'}
                </button>
                {probeMsg && <div className="small text-muted mb-2">{probeMsg}</div>}

                <label className="form-label mb-1 mt-1"><strong>Embedding Provider</strong></label>
                <select className="form-select form-select-sm mb-2" value={embeddingProvider}
                  onChange={e => setEmbeddingProvider(e.target.value)}>
                  {(aiConfig.embedding_providers || ['local', 'openai']).map(p => (
                    <option key={p} value={p}>{p === 'local' ? 'local (sentence-transformers)' : 'openai'}</option>
                  ))}
                </select>

                <button className="btn btn-sm btn-primary w-100" onClick={saveAiConfig} disabled={savingAi}>
                  {savingAi ? 'Saving...' : 'Save AI Config'}
                </button>
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
