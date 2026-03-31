import React, { useEffect, useRef, useState } from 'react';

export default function ActionServerTab() {
  const [jobId, setJobId] = useState('');
  const [state, setState] = useState('idle');
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState('');
  const [error, setError] = useState('');
  const [isRestarting, setIsRestarting] = useState(false);
  const logRef = useRef(null);

  const startRestart = async () => {
    setIsRestarting(true);
    setError('');
    setLogs('');
    try {
      const res = await fetch('http://localhost:8080/api/action_server/restart', {
        method: 'POST',
        credentials: 'include',
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        setJobId(data.jobId);
        setRunning(true);
        setState('starting');
      } else {
        setError(data.error || res.statusText);
        setIsRestarting(false);
      }
    } catch (e) {
      setError(e.message);
      setIsRestarting(false);
    }
  };

  // Poll status
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    const id = setInterval(async () => {
      try {
        const res = await fetch(`http://localhost:8080/api/action_server/restart/${jobId}/status`, { credentials: 'include' });
        const data = await res.json();
        if (!cancelled && res.ok) {
          setState(data.state || 'running');
          setRunning(!!data.running);
          setError(data.error || '');
          setLogs(data.logs || '');
          if (!data.running && (data.state === 'healthy' || data.state === 'error')) {
            clearInterval(id);
            setIsRestarting(false);
          }
        }
      } catch (_) {
        // ignore
      }
    }, 1000);
    return () => { cancelled = true; clearInterval(id); };
  }, [jobId]);

  // Auto-scroll logs
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logs]);

  const badge = state === 'healthy' ? 'bg-success' : state === 'error' ? 'bg-danger' : 'bg-warning text-dark';

  return (
    <div className="card mt-3">
      <div className="card-body">
        <h5 className="card-title">Action Server</h5>
        <p className="card-text">Rebuild and restart the Rasa Action Server container. Useful after editing <code>rasa-ui/actions/actions.py</code>.</p>
        <div className="d-flex align-items-center gap-3 flex-wrap">
          <button className="btn btn-outline-primary" onClick={startRestart} disabled={isRestarting}>
            {isRestarting ? 'Restarting…' : 'Restart Action Server'}
          </button>
          {state !== 'idle' && (
            <span className={`badge ${badge}`}>{running ? 'In Progress' : (state === 'healthy' ? 'Healthy' : state)}</span>
          )}
          {error && <span className="text-danger small">{error}</span>}
        </div>
        <div className="mt-3">
          <div className="form-text">Logs</div>
          <div ref={logRef} className="border rounded" style={{height: 280, overflow: 'auto', background: '#0b0b0b', color: '#cfd2d6', padding: '8px'}}>
            <pre style={{whiteSpace: 'pre-wrap', wordWrap: 'break-word', margin: 0}}>{logs || '—'}</pre>
          </div>
        </div>
      </div>
    </div>
  );
}
