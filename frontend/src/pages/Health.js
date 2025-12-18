// src/pages/Health.js
import React, { useState } from 'react';
import TopNav from '../components/TopNav';

// OntoSage 2.0 Service Endpoints
const endpointList = [
  // OntoSage 2.0 Core Services
  { name: 'Orchestrator API', url: 'http://localhost:8000/health', category: 'OntoSage 2.0' },
  { name: 'RAG Service', url: 'http://localhost:8001/health', category: 'OntoSage 2.0' },
  { name: 'Code Executor', url: 'http://localhost:8002/health', category: 'OntoSage 2.0' },
  { name: 'Whisper STT', url: 'http://localhost:8003/health', category: 'OntoSage 2.0' },
  
  // Infrastructure
  { name: 'Qdrant Vector DB', url: 'http://localhost:6333/health', category: 'Infrastructure' },
  { name: 'Redis Memory Store', url: 'http://localhost:6379/', category: 'Infrastructure' },
  { name: 'Jena Fuseki (SPARQL)', url: 'http://localhost:3030/$/ping', category: 'Infrastructure' },
  { name: 'MySQL Database', url: 'http://localhost:3306/', category: 'Infrastructure' },
  
  // AI Models
  { name: 'Ollama (Mistral)', url: 'http://localhost:11434/api/tags', category: 'AI Models' },
  
  // Frontend
  { name: 'React Frontend', url: 'http://localhost:3000/', category: 'User Interface' },
];

const cardStyle = {
  borderRadius: 16,
  boxShadow: '0 10px 25px rgba(0,0,0,0.08)',
  backdropFilter: 'blur(6px)',
  border: '1px solid rgba(255,255,255,0.3)'
};

export default function Health() {
  const [results, setResults] = useState({});
  const [loading, setLoading] = useState({});
  const [selectedCategory, setSelectedCategory] = useState('All');

  const categories = ['All', ...new Set(endpointList.map(ep => ep.category))];
  const filteredEndpoints = selectedCategory === 'All' 
    ? endpointList 
    : endpointList.filter(ep => ep.category === selectedCategory);

  const checkOne = async (name, url) => {
    setLoading(prev => ({ ...prev, [name]: true }));
    try {
      // Use no-cors to avoid blocking for endpoints without CORS; status will be opaque.
      const mode = url.startsWith('http://localhost') ? 'no-cors' : 'cors';
      const res = await fetch(url, { method: 'GET', mode });
      // When mode is 'no-cors', res.status is 0. Treat 0 as reachable.
      const ok = res.ok || res.status === 200 || res.status === 204 || res.type === 'opaque' || res.status === 0;
      let text = '';
      try { text = await res.text(); } catch {}
      setResults(prev => ({ ...prev, [name]: { ok, status: res.status || 0, text: text?.slice(0, 200) } }));
    } catch (e) {
      setResults(prev => ({ ...prev, [name]: { ok: false, status: -1, text: String(e) } }));
    } finally {
      setLoading(prev => ({ ...prev, [name]: false }));
    }
  };

  const checkAll = async () => {
    const endpoints = selectedCategory === 'All' ? endpointList : filteredEndpoints;
    for (const ep of endpoints) {
      // Fire sequentially to avoid spamming
      // eslint-disable-next-line no-await-in-loop
      await checkOne(ep.name, ep.url);
    }
  };

  return (
    <div className="home-body">
      <TopNav />
      <div className="container mt-4" id="content">
        <div className="d-flex align-items-center justify-content-between mb-3">
          <h2>Health Check - Integrated Services</h2>
          <button className="btn btn-outline-primary" onClick={checkAll}>
            Check All {selectedCategory !== 'All' && `(${selectedCategory})`}
          </button>
        </div>
        
        <div className="mb-4">
          <label className="me-2"><strong>Filter by Category:</strong></label>
          <div className="btn-group" role="group">
            {categories.map(cat => (
              <button
                key={cat}
                className={`btn btn-sm ${selectedCategory === cat ? 'btn-primary' : 'btn-outline-primary'}`}
                onClick={() => setSelectedCategory(cat)}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>

        <p className="text-muted">
          Showing {filteredEndpoints.length} services. 
          Click "Check All" to test all services in the selected category, or check individual services below.
        </p>

        <div className="row row-cols-1 row-cols-md-2 row-cols-lg-3 g-4">
          {filteredEndpoints.map(ep => {
            const r = results[ep.name];
            const busy = loading[ep.name];
            const badge = r ? (r.ok ? 'bg-success' : 'bg-danger') : 'bg-secondary';
            const label = r ? (r.ok ? 'Healthy' : 'Unreachable') : 'Unknown';
            return (
              <div className="col" key={ep.name}>
                <div className="card p-3" style={cardStyle}>
                  <div className="d-flex justify-content-between align-items-start">
                    <div>
                      <h5 className="mb-1">{ep.name}</h5>
                      <small className="badge bg-info text-dark mb-1">{ep.category}</small>
                      <br />
                      <a href={ep.url} target="_blank" rel="noreferrer" style={{ fontSize: 11 }}>{ep.url}</a>
                    </div>
                    <span className={`badge ${badge}`}>{label}</span>
                  </div>
                  <div className="mt-3">
                    <button
                      className="btn btn-primary btn-sm w-100"
                      onClick={() => checkOne(ep.name, ep.url)}
                      disabled={busy}
                    >
                      {busy ? 'Checking…' : 'Check Health'}
                    </button>
                  </div>
                  {r && (
                    <pre className="mt-3" style={{ maxHeight: 120, overflow: 'auto', background: '#f8f9fa', padding: 8, borderRadius: 6, fontSize: 11 }}>
{`status: ${r.status}\n${r.text}`}
                    </pre>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
