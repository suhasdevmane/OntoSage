import React, { useEffect, useState } from 'react';

const API = 'http://localhost:6080';

export default function SettingsEditor() {
  const [cwd, setCwd] = useState('');
  const [entries, setEntries] = useState([]);
  const [openPath, setOpenPath] = useState('');
  const [content, setContent] = useState('');
  const [msg, setMsg] = useState('');
  const [validating, setValidating] = useState(false);
  const [linting, setLinting] = useState(false);

  const list = async (dir = '') => {
    setMsg('');
    try {
      const res = await fetch(`${API}/files?dir=${encodeURIComponent(dir)}`);
      const data = await res.json();
      if (res.ok) {
        setEntries(data);
        setCwd(dir);
      } else {
        setMsg(data.detail || 'Failed to list files');
      }
    } catch (e) {
      setMsg(e.message);
    }
  };

  const open = async (path) => {
    setMsg('');
    try {
      const res = await fetch(`${API}/file?path=${encodeURIComponent(path)}`);
      const data = await res.json();
      if (res.ok) {
        setOpenPath(data.path);
        setContent(data.content);
      } else {
        setMsg(data.detail || 'Failed to read file');
      }
    } catch (e) {
      setMsg(e.message);
    }
  };

  const save = async () => {
    setMsg('');
    try {
      const res = await fetch(`${API}/file`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: openPath, content })
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        setMsg('Saved');
        // Reload directory for mtime updates
        list(cwd);
      } else {
        setMsg(data.detail || 'Failed to save file');
      }
    } catch (e) {
      setMsg(e.message);
    }
  };

  const validate = async () => {
    setValidating(true);
    setMsg('');
    try {
      const res = await fetch(`${API}/validate`, { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        setMsg(data.ok ? 'Validation passed' : `Validation failed (code ${data.returncode})`);
        // Append a collapsible output
        if (data.output) {
          console.log('Validation output:', data.output);
        }
      } else {
        setMsg(data.detail || 'Validation error');
      }
    } catch (e) {
      setMsg(e.message);
    } finally {
      setValidating(false);
    }
  };

  const lint = async () => {
    setLinting(true);
    setMsg('');
    try {
      const res = await fetch(`${API}/lint-actions`, { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        if (data.ok) setMsg('Actions lint clean');
        else setMsg(`${(data.results||[]).length} lint issues found`);
        console.log('Lint results:', data.results);
      } else {
        setMsg(data.detail || 'Lint error');
      }
    } catch (e) {
      setMsg(e.message);
    } finally {
      setLinting(false);
    }
  };

  useEffect(() => { list(''); }, []);

  const goUp = () => {
    if (!cwd) return;
    const parts = cwd.split('/').filter(Boolean);
    parts.pop();
    list(parts.join('/'));
  };

  return (
    <>
      <h4>Rasa — Edit & Validate</h4>
      <p className="text-muted">Edit your Rasa project files, validate data, and lint custom actions before training.</p>
      <div className="row g-3">
        <div className="col-12 col-md-4">
          <div className="card">
            <div className="card-body">
              <div className="d-flex justify-content-between align-items-center">
                <h6 className="mb-2">Project files</h6>
                <div>
                  <button className="btn btn-sm btn-outline-secondary me-2" onClick={() => list(cwd)}>Refresh</button>
                  <button className="btn btn-sm btn-outline-secondary" onClick={goUp} disabled={!cwd}>Up</button>
                </div>
              </div>
              <ul className="list-group small">
                {entries.map(e => (
                  <li key={e.path} className="list-group-item d-flex justify-content-between align-items-center">
                    <button className="btn btn-link p-0 text-decoration-none" onClick={() => e.is_dir ? list((cwd?cwd+'/':'') + e.name) : open(e.path)}>
                      {e.is_dir ? '📁' : '📄'} {e.name}
                    </button>
                    <span className="text-muted">{e.is_dir ? '' : (e.size/1024).toFixed(1)+' KB'}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <div className="card mt-3">
            <div className="card-body d-flex gap-2">
              <button className="btn btn-outline-primary" onClick={validate} disabled={validating}>{validating ? 'Validating…' : 'Validate Data'}</button>
              <button className="btn btn-outline-secondary" onClick={lint} disabled={linting}>{linting ? 'Linting…' : 'Lint Actions'}</button>
            </div>
          </div>
          {msg && <div className="alert alert-info mt-3">{msg}</div>}
        </div>
        <div className="col-12 col-md-8">
          <div className="card h-100">
            <div className="card-body d-flex flex-column">
              <div className="d-flex justify-content-between align-items-center mb-2">
                <h6 className="mb-0">Editor</h6>
                <button className="btn btn-sm btn-primary" onClick={save} disabled={!openPath}>Save</button>
              </div>
              <div className="small text-muted mb-2">{openPath || 'Select a file to view/edit'}</div>
              <textarea className="form-control" style={{ flex: 1, minHeight: 400, fontFamily: 'monospace' }} value={content} onChange={(e) => setContent(e.target.value)} disabled={!openPath} />
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
