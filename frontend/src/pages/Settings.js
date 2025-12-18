// src/pages/Settings.js
import React, { useEffect, useRef, useState } from 'react';
import TopNav from '../components/TopNav';

export default function Settings({ embedded = false }) {
  // Removed old trainStatus; using progress + messages instead
  const [isTraining, setIsTraining] = useState(false);
  const [models, setModels] = useState([]);
  const [currentModel, setCurrentModel] = useState('');
  const [modelActionMsg, setModelActionMsg] = useState('');
  const [activatingModel, setActivatingModel] = useState(''); // name while activating
  const [activatingEta, setActivatingEta] = useState(300); // seconds countdown for 5 min
  const [progress, setProgress] = useState('idle');
  const [lastError, setLastError] = useState('');
  const [rasaMsg, setRasaMsg] = useState('');
  const [rasaStarted, setRasaStarted] = useState(false);
  const [rasaStatus, setRasaStatus] = useState('idle'); // 'idle' | 'starting' | 'healthy' | 'error'
  const [showRasaStatus, setShowRasaStatus] = useState(false);
  const hideTimerRef = useRef(null);
  // Small logs panel state
  const [rasaLogs, setRasaLogs] = useState('');
  const logsRef = useRef(null);
  // Start job tracking
  const [startJobId, setStartJobId] = useState('');
  // (state/running tracked via rasaStatus + job polling logs)
  const [trainJobId, setTrainJobId] = useState('');
  // Logs behavior and delta trackers
  const [appendLogs, setAppendLogs] = useState(true);
  const startLastCountRef = useRef(0);
  const trainLastCountRef = useRef(0);
  
  const step1Done = progress === 'done';
  const step2Active = rasaStatus === 'starting' || rasaStarted || rasaStatus === 'healthy';
  const step3Verified = rasaStatus === 'healthy';

  // Removed legacy HTTP training function; only job-based training is used.

  const triggerTrainingJob = async () => {
    setModelActionMsg('');
    setIsTraining(true);
    setProgress('starting');
    // Reset logs and note start
    setRasaLogs('');
    setRasaLogs((l) => l + `[${new Date().toLocaleTimeString()}] Triggering training job…\n`);
    try {
      const res = await fetch('http://localhost:8080/api/rasa/train_job2', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        setTrainJobId(data.jobId);
      } else {
        const details = data.logs ? `\nLogs: ${String(data.logs).slice(-500)}` : (data.body ? `\nDetails: ${String(data.body).slice(0,500)}` : '');
        const code = data.status ? ` (status ${data.status})` : '';
        setModelActionMsg(`Training job failed${code}: ${data.error || res.statusText}${details}`);
        // Append any logs tail to the panel
        if (data.logs) {
          setRasaLogs((l) => l + `\n[${new Date().toLocaleTimeString()}] Training failed. Logs tail:\n${data.logs}\n`);
        } else if (data.error) {
          setRasaLogs((l) => l + `\n[${new Date().toLocaleTimeString()}] Training failed: ${data.error}\n`);
        }
      }
    } catch (e) {
      setModelActionMsg(`Training job error: ${e.message}`);
      setRasaLogs((l) => l + `\n[${new Date().toLocaleTimeString()}] Training job error: ${e.message}\n`);
    } finally {
      // keep isTraining true until job completes via poller
    }
  };

  const loadModels = async () => {
    try {
      const res = await fetch('http://localhost:8080/api/rasa/models', { credentials: 'include' });
      const data = await res.json();
      if (res.ok) {
        setModels(Array.isArray(data.models) ? data.models : []);
        setCurrentModel(data.current || '');
      } else {
        setModelActionMsg(`Failed to load models: ${data.error || res.statusText}`);
      }
    } catch (e) {
      setModelActionMsg(`Failed to load models: ${e.message}`);
    }
  };

  const selectModel = async (name, opts = { restart: false }) => {
    setModelActionMsg('');
    setActivatingModel(name);
    setActivatingEta(300);
    try {
      const res = await fetch('http://localhost:8080/api/rasa/models/select', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: name, restart: !!opts.restart }),
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        setModelActionMsg(opts.restart ? `Restarted Rasa with model: ${name}` : `Activated model: ${name}`);
        // Mark as healthy if backend completed the cycle
        setRasaStatus('healthy');
        setRasaStarted(true);
        setShowRasaStatus(true);
        await loadModels();
      } else {
        setModelActionMsg(`Activate failed: ${data.error || res.statusText}`);
      }
    } catch (e) {
      setModelActionMsg(`Activate error: ${e.message}`);
    }
    setActivatingModel('');
  };

  // countdown timer for activation UI
  useEffect(() => {
    if (!activatingModel) return;
    setActivatingEta(300);
    const id = setInterval(() => setActivatingEta((s) => (s > 0 ? s - 1 : 0)), 1000);
    return () => clearInterval(id);
  }, [activatingModel]);

  const stopRasa = async () => {
    setRasaMsg('');
    setRasaLogs((l) => l + `[${new Date().toLocaleTimeString()}] Stopping Rasa…\n`);
    try {
      const res = await fetch('http://localhost:8080/api/rasa/stop', {
        method: 'POST',
        credentials: 'include',
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        setRasaMsg('Rasa stopped.');
        setRasaLogs((l) => l + `[${new Date().toLocaleTimeString()}] Rasa stopped.\n`);
      } else {
        setRasaMsg(`Stop failed: ${data.error || res.statusText}`);
        setRasaLogs((l) => l + `[${new Date().toLocaleTimeString()}] Stop failed: ${data.error || res.statusText}\n`);
      }
    } catch (e) {
      setRasaMsg(`Stop error: ${e.message}`);
      setRasaLogs((l) => l + `[${new Date().toLocaleTimeString()}] Stop error: ${e.message}\n`);
    }
  };

  const startRasa = async () => {
    setRasaMsg('');
    setRasaStatus('starting');
    setShowRasaStatus(true);
    // Job-based start sequence handled via polling below
    // Reset logs for a fresh start sequence (unless appending)
    if (!appendLogs) setRasaLogs('');
    setRasaLogs((l) => (l ? l + '\n' : '') + `--- Start Rasa @ ${new Date().toLocaleTimeString()} ---\n`);
    try {
      const res = await fetch('http://localhost:8080/api/rasa/start_job', {
        method: 'POST',
        credentials: 'include',
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        setStartJobId(data.jobId);
        startLastCountRef.current = 0;
      } else {
        setRasaMsg(`Start failed: ${data.error || res.statusText}`);
        setRasaStatus('error');
  // handled by status chip and logs
        setRasaLogs((l) => l + `[${new Date().toLocaleTimeString()}] Start failed: ${data.error || res.statusText}\n`);
      }
    } catch (e) {
      setRasaMsg(`Start error: ${e.message}`);
      setRasaStatus('error');
  // handled by status chip and logs
      setRasaLogs((l) => l + `[${new Date().toLocaleTimeString()}] Start error: ${e.message}\n`);
    }
  };

  useEffect(() => {
    loadModels();
  }, []);

  // Poll training job status for logs and completion
  useEffect(() => {
    if (!trainJobId) return;
    let cancelled = false;
    const id = setInterval(async () => {
      try {
        const res = await fetch(`http://localhost:8080/api/rasa/train_job2/${trainJobId}/status`, { credentials: 'include' });
        const data = await res.json();
        if (!cancelled && res.ok) {
          // Append only new lines based on last count
          const all = (data.logs || '').split(/\r?\n/);
          const prev = trainLastCountRef.current || 0;
          if (all.length > prev) {
            const delta = all.slice(prev).filter(Boolean).join('\n');
            if (delta) setRasaLogs((l) => (l ? l + '\n' : '') + delta + '\n');
            trainLastCountRef.current = all.length;
          }
          // Update progress chip based on state
          const state = data.state || 'starting';
          setProgress(state);
          if (state === 'done' && data.model) {
            setModelActionMsg(`Training job complete. Model: ${data.model}`);
            setIsTraining(false);
            setProgress('idle');
            await loadModels();
            clearInterval(id);
            trainLastCountRef.current = 0;
          } else if (state === 'error') {
            setLastError(data.error || 'unknown error');
            setIsTraining(false);
            setProgress('idle');
            clearInterval(id);
            trainLastCountRef.current = 0;
          }
        }
      } catch (_) {
        // ignore
      }
    }, 1000);
    return () => { cancelled = true; clearInterval(id); };
  }, [trainJobId]);
  
  useEffect(() => {
    // Cleanup hide timer on unmount
    return () => {
      if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    };
  }, []);

  const startBtnClass = rasaStatus === 'starting'
    ? 'btn btn-warning'
    : rasaStatus === 'healthy'
      ? 'btn btn-success'
      : 'btn btn-outline-success';
  const startBtnLabel = rasaStatus === 'starting' ? 'Starting…' : 'Start Rasa';
  
  // Poll start job status and stream logs into panel
  useEffect(() => {
    if (!startJobId) return;
    let cancelled = false;
    const id = setInterval(async () => {
      try {
        const res = await fetch(`http://localhost:8080/api/rasa/start_job/${startJobId}/status`, { credentials: 'include' });
        const data = await res.json();
        if (!cancelled && res.ok) {
          // state reflected in rasaStatus below
          // Update status chip
          if (data.state === 'healthy') {
            setRasaStatus('healthy');
            setRasaStarted(true);
            // Auto-hide status after 2 minutes
            if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
            hideTimerRef.current = setTimeout(() => setShowRasaStatus(false), 120000);
          } else if (data.state === 'error') {
            setRasaStatus('error');
          } else {
            setRasaStatus('starting');
          }
          // Append only new lines from backend tail
          const all = (data.logs || '').split(/\r?\n/);
          const prev = startLastCountRef.current || 0;
          if (all.length > prev) {
            const delta = all.slice(prev).filter(Boolean).join('\n');
            if (delta) setRasaLogs((l) => (l ? l + '\n' : '') + delta + '\n');
            startLastCountRef.current = all.length;
          }
          if (!data.running && (data.state === 'healthy' || data.state === 'error')) {
            clearInterval(id);
            startLastCountRef.current = 0;
          }
        }
      } catch (_) {
        // ignore transient errors
      }
    }, 1000);
    return () => { cancelled = true; clearInterval(id); };
  }, [startJobId]);
  // Auto-scroll logs
  useEffect(() => {
    if (logsRef.current) {
      logsRef.current.scrollTop = logsRef.current.scrollHeight;
    }
  }, [rasaLogs]);
  const renderCards = () => (
    <div>
      <div className="card mt-3">
        <div className="card-body">
          <h5 className="card-title">Rasa Model</h5>
          <p className="card-text">Train a new Rasa model using a one-off Docker job. Then start Rasa to use the new model.</p>
          <div className="d-flex align-items-center gap-4 flex-wrap">
            <button className="btn btn-primary" onClick={triggerTrainingJob} disabled={isTraining}>
              {isTraining ? 'Running…' : 'Train Rasa'}
            </button>
            <span className="text-muted">→</span>
            <button className={startBtnClass} onClick={startRasa} disabled={isTraining || rasaStatus === 'starting'} style={{ marginLeft: '0.5rem' }}>
              {startBtnLabel}
            </button>
            <button className="btn btn-outline-warning ms-2" onClick={stopRasa} disabled={isTraining}>Stop Rasa</button>
          </div>
          {/* Step circles under buttons with a Verify step */}
          <div className="mt-2">
            <div className="d-flex align-items-end" style={{ columnGap: '2.5rem', rowGap: '0.5rem', flexWrap: 'wrap' }}>
              <div className="d-flex flex-column align-items-start" style={{ minWidth: 120 }}>
                <div className={`rounded-circle d-flex align-items-center justify-content-center ${step1Done ? 'bg-success text-white' : 'bg-light'}`} style={{ width: 28, height: 28 }}>1</div>
                <div className="small text-muted mt-1">Train</div>
              </div>
              <div className="flex-grow-1 d-none d-md-block" style={{ height: 4, background: step2Active ? '#198754' : '#dee2e6', margin: '0 8px' }} />
              <div className="d-flex flex-column align-items-start" style={{ minWidth: 120 }}>
                <div className={`rounded-circle d-flex align-items-center justify-content-center ${step2Active ? 'bg-success text-white' : 'bg-light'}`} style={{ width: 28, height: 28 }}>2</div>
                <div className="small text-muted mt-1">Start</div>
              </div>
              <div className="flex-grow-1 d-none d-md-block" style={{ height: 4, background: step3Verified ? '#198754' : '#dee2e6', margin: '0 8px' }} />
              <div className="d-flex flex-column align-items-start" style={{ minWidth: 120 }}>
                <div className={`rounded-circle d-flex align-items-center justify-content-center ${step3Verified ? 'bg-success text-white' : 'bg-light'}`} style={{ width: 28, height: 28 }}>3</div>
                <div className="small text-muted mt-1">Verify</div>
              </div>
            </div>
          </div>
          {showRasaStatus && (
            <div className="mt-2">
              {rasaStatus === 'starting' && (
                <span className="badge bg-warning text-dark">Please wait… Rasa is turning on</span>
              )}
              {rasaStatus === 'healthy' && (
                <span className="badge bg-success">Rasa is healthy</span>
              )}
              {rasaStatus === 'error' && (
                <span className="badge bg-danger">Rasa failed to start</span>
              )}
            </div>
          )}
          {progress && progress !== 'idle' && progress !== 'done' && rasaStatus === 'idle' && (
            <div className="alert alert-warning mt-2 mb-0" role="alert">
              Please wait… {progress.replaceAll('_',' ')}
            </div>
          )}
          {progress === 'done' && rasaStatus === 'idle' && (
            <div className="alert alert-success mt-2 mb-0" role="alert">
              Model trained and saved. Next: click <strong>Start Rasa</strong> to run with the new model or choose a model from following list.
            </div>
          )}
          {progress === 'error' && lastError && rasaStatus === 'idle' && (
            <div className="alert alert-danger mt-2 mb-0 d-flex justify-content-between align-items-center" role="alert">
              <span>
                Training finished but auto-load failed: {lastError}. You can start Rasa now and use the latest model.
              </span>
              <button className="btn btn-sm btn-light" onClick={startRasa}>Start Rasa</button>
            </div>
          )}
          {rasaMsg && (
            <div className="alert alert-secondary mt-2 mb-0" role="alert">
              {rasaMsg}
            </div>
          )}
          {/* Compact logs window below the Rasa Model container */}
          <div className="mt-3">
            <div className="d-flex justify-content-between align-items-center">
              <div>
                <div className="form-text">Logs</div>
                <div className="mt-1 d-flex gap-2">
                  <span className={`badge ${progress === 'done' ? 'bg-success' : progress === 'error' ? 'bg-danger' : (progress === 'idle' ? 'bg-secondary' : 'bg-warning text-dark')}`} title="Training state">
                    Train: {progress}
                  </span>
                  <span className={`badge ${rasaStatus === 'healthy' ? 'bg-success' : rasaStatus === 'error' ? 'bg-danger' : (rasaStatus === 'idle' ? 'bg-secondary' : 'bg-warning text-dark')}`} title="Rasa state">
                    Rasa: {rasaStatus}
                  </span>
                </div>
              </div>
              <div className="d-flex align-items-center gap-3">
                <div className="form-check form-switch">
                  <input className="form-check-input" type="checkbox" role="switch" id="appendLogsSwitch" checked={appendLogs} onChange={(e) => setAppendLogs(e.target.checked)} />
                  <label className="form-check-label" htmlFor="appendLogsSwitch">Append across actions</label>
                </div>
                <button className="btn btn-sm btn-outline-secondary" onClick={() => setRasaLogs('')}>Clear</button>
              </div>
            </div>
            <div ref={logsRef} className="border rounded" style={{height: 220, overflow: 'auto', background: '#0b0b0b', color: '#cfd2d6', padding: '8px'}}>
              <pre style={{whiteSpace: 'pre-wrap', wordWrap: 'break-word', margin: 0}}>{rasaLogs || '—'}</pre>
            </div>
          </div>
        </div>
      </div>
      <div className="card mt-3">
        <div className="card-body">
          <h5 className="card-title">Models</h5>
          <div className="mb-2">
            <button className="btn btn-secondary me-2" onClick={loadModels} disabled={isTraining}>Refresh</button>
            <span className="text-muted">{progress && progress !== 'idle' ? `In progress: ${progress.replaceAll('_',' ')}` : ''}</span>
          </div>
          {currentModel && <p className="text-success">Current: {currentModel}</p>}
          {models.length === 0 ? (
            <p className="text-muted">No models found yet in server models directory.</p>
          ) : (
            <ul className="list-group">
              {models.map(m => (
                <li key={m.name} className="list-group-item d-flex justify-content-between align-items-center">
                  <div className="d-flex align-items-center">
                    {currentModel && currentModel.includes(m.name) ? (
                      <span className="badge bg-success rounded-circle me-2" style={{ width: 10, height: 10 }} title="Currently loaded"></span>
                    ) : (
                      <span className="me-2" style={{ width: 10, height: 10 }}></span>
                    )}
                    <div className="d-flex flex-column">
                      <strong>{m.name}</strong>
                      <small className="text-muted">{new Date(m.mtime*1000).toLocaleString()} • {(m.size/1024/1024).toFixed(1)} MB</small>
                    </div>
                  </div>
                  <div className="d-flex align-items-center gap-2">
                    <button className="btn btn-sm btn-outline-success" onClick={() => selectModel(m.name, { restart: true })} disabled={isTraining}>
                      {activatingModel === m.name ? 'Activating…' : 'Activate'}
                    </button>
                    <button className="btn btn-sm btn-outline-danger" onClick={async () => {
                      if (!window.confirm(`Delete model ${m.name}? This cannot be undone.`)) return;
                      setModelActionMsg('');
                      try {
                        const res = await fetch('http://localhost:8080/api/rasa/models/delete', {
                          method: 'POST',
                          credentials: 'include',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ model: m.name }),
                        });
                        const data = await res.json();
                        if (res.ok && data.ok) {
                          setModelActionMsg(`Deleted: ${m.name}`);
                          await loadModels();
                        } else {
                          setModelActionMsg(`Delete failed: ${data.error || res.statusText}`);
                        }
                      } catch (e) {
                        setModelActionMsg(`Delete error: ${e.message}`);
                      }
                    }} disabled={isTraining || (currentModel && currentModel.includes(m.name))}>
                      Delete
                    </button>
                    {activatingModel === m.name && (
                      <span className="badge bg-warning text-dark ms-2" title="Waiting for model to be ready">
                        Loading… {Math.floor(activatingEta/60)}:{String(activatingEta%60).padStart(2,'0')}
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
          {modelActionMsg && (
            <div className="alert alert-info mt-3" role="alert">
              {modelActionMsg}
            </div>
          )}
        </div>
      </div>
      {/* Future: add forms for base URLs, timeouts, authentication, etc. */}
    </div>
  );

  if (embedded) {
    return (
      <div className="container mt-3" id="content">
        <h4>Train & Activate</h4>
        {renderCards()}
      </div>
    );
  }

  return (
    <div className="home-body">
      <TopNav />
      <div className="container mt-4" id="content">
        <h2>Settings</h2>
        <p className="text-muted">Configure frontend options and health-check preferences here (placeholder).</p>
        {renderCards()}
      </div>
    </div>
  );
}
