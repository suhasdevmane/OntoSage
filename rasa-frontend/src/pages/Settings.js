// src/pages/Settings.js
import React, { useEffect, useRef, useState } from 'react';
import TopNav from '../components/TopNav';

export default function Settings() {
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
  
  const step1Done = progress === 'done';
  const step2Active = rasaStatus === 'starting' || rasaStarted || rasaStatus === 'healthy';
  const step3Verified = rasaStatus === 'healthy';

  // Removed legacy HTTP training function; only job-based training is used.

  const triggerTrainingJob = async () => {
    setModelActionMsg('');
    setIsTraining(true);
    setProgress('starting');
    try {
      const res = await fetch('http://localhost:8080/api/rasa/train_job', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        setModelActionMsg(`Training job complete. Model: ${data.model}`);
        setRasaStarted(false);
        await loadModels();
      } else {
        const details = data.logs ? `\nLogs: ${String(data.logs).slice(-500)}` : (data.body ? `\nDetails: ${String(data.body).slice(0,500)}` : '');
        const code = data.status ? ` (status ${data.status})` : '';
        setModelActionMsg(`Training job failed${code}: ${data.error || res.statusText}${details}`);
      }
    } catch (e) {
      setModelActionMsg(`Training job error: ${e.message}`);
    } finally {
      setIsTraining(false);
      setProgress('idle');
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
    try {
      const res = await fetch('http://localhost:8080/api/rasa/stop', {
        method: 'POST',
        credentials: 'include',
      });
      const data = await res.json();
      if (res.ok && data.ok) setRasaMsg('Rasa stopped.');
      else setRasaMsg(`Stop failed: ${data.error || res.statusText}`);
    } catch (e) {
      setRasaMsg(`Stop error: ${e.message}`);
    }
  };

  const startRasa = async () => {
    setRasaMsg('');
    setRasaStatus('starting');
    setShowRasaStatus(true);
    try {
      const res = await fetch('http://localhost:8080/api/rasa/start', {
        method: 'POST',
        credentials: 'include',
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        setRasaMsg('Rasa started.');
        setRasaStarted(true);
        setRasaStatus('healthy');
        // Auto-hide the Rasa status chip after ~2 minutes once healthy
        if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
        hideTimerRef.current = setTimeout(() => setShowRasaStatus(false), 120000);
        await loadModels();
      } else {
        setRasaMsg(`Start failed: ${data.error || res.statusText}`);
        setRasaStatus('error');
      }
    } catch (e) {
      setRasaMsg(`Start error: ${e.message}`);
      setRasaStatus('error');
    }
  };

  useEffect(() => {
    loadModels();
    const id = setInterval(async () => {
      try {
        const res = await fetch('http://localhost:8080/api/rasa/train_job/status', { credentials: 'include' });
        const data = await res.json();
        if (res.ok) {
          setProgress(data.step || 'idle');
          setLastError(data.error || '');
          if (data.step === 'done' && data.model) {
            await loadModels();
          }
        }
      } catch {
        // ignore
      }
    }, 1500);
    return () => clearInterval(id);
  }, []);
  
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
  
  // Optional frontend health polling of Rasa /version to update UI promptly
  useEffect(() => {
    if (!showRasaStatus || rasaStatus !== 'starting') return;
    let cancelled = false;
    const interval = setInterval(async () => {
      try {
        const res = await fetch('http://localhost:5005/version', { method: 'GET' });
        if (!cancelled && res.ok) {
          setRasaStatus('healthy');
          if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
          hideTimerRef.current = setTimeout(() => setShowRasaStatus(false), 120000);
          clearInterval(interval);
        }
      } catch (_) {
        // keep waiting
      }
    }, 1000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [showRasaStatus, rasaStatus]);
  return (
    <div className="home-body">
      <TopNav />
      <div className="container mt-4" id="content">
        <h2>Settings</h2>
        <p className="text-muted">Configure frontend options and health-check preferences here (placeholder).</p>
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
                {/* Under Train button */}
                <div className="d-flex flex-column align-items-start" style={{ minWidth: 120 }}>
                  <div className={`rounded-circle d-flex align-items-center justify-content-center ${step1Done ? 'bg-success text-white' : 'bg-light'}`} style={{ width: 28, height: 28 }}>1</div>
                  <div className="small text-muted mt-1">Train</div>
                </div>
                {/* Connector between 1 and 2 */}
                <div className="flex-grow-1 d-none d-md-block" style={{ height: 4, background: step2Active ? '#198754' : '#dee2e6', margin: '0 8px' }} />
                {/* Under Start button */}
                <div className="d-flex flex-column align-items-start" style={{ minWidth: 120 }}>
                  <div className={`rounded-circle d-flex align-items-center justify-content-center ${step2Active ? 'bg-success text-white' : 'bg-light'}`} style={{ width: 28, height: 28 }}>2</div>
                  <div className="small text-muted mt-1">Start</div>
                </div>
                {/* Connector between 2 and 3 */}
                <div className="flex-grow-1 d-none d-md-block" style={{ height: 4, background: step3Verified ? '#198754' : '#dee2e6', margin: '0 8px' }} />
                {/* Verify step */}
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
            {/* Only show training-in-progress alert while not started, and avoid showing 'done' in yellow */}
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

            {/* Old linear stepper removed in favor of per-button circles with verify */}
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
    </div>
  );
}
