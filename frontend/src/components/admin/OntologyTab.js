import React, { useState, useEffect, useCallback } from 'react';

const EXAMPLE_TTL = `# ── REQUIRED: use the same bldg: namespace as the active building TTL ──────
# For bldg1 (Abacws): <http://abacwsbuilding.cardiff.ac.uk/abacws#>
@prefix bldg:   <http://abacwsbuilding.cardiff.ac.uk/abacws#> .
@prefix brick:  <https://brickschema.org/schema/Brick#> .
@prefix ref:    <https://brickschema.org/schema/Brick/ref#> .
@prefix bacnet: <http://data.ashrae.org/bacnet/> .
@prefix unit:   <http://qudt.org/vocab/unit/> .
@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .

# ── Pattern 1: SQL/Postgres/MySQL time-series sensor (TimeseriesReference) ──
# Database node — credentials stay in database_registry.yaml, NOT here.
bldg:database1
    a ref:Database ;
    rdfs:label "Primary MySQL Sensor Store" .

bldg:MyNewTemperatureSensor
    a brick:Temperature_Sensor ;
    rdfs:label "My New Temperature Sensor"@en ;
    brick:isPartOf bldg:Floor3 ;
    brick:hasUnit unit:DEG_C ;
    ref:hasExternalReference [
        a ref:TimeseriesReference ;
        ref:hasTimeseriesId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" ;
        ref:storedAt bldg:database1 ;
    ] .

# ── Pattern 2: BACnet sensor point (BACnetReference) ────────────────────────
bldg:sample-device
    a bacnet:BACnetDevice ;
    bacnet:device-instance 123 ;
    bacnet:hasPort [
        a bacnet:Port ;
        bacnet:network-type bacnet:NetworkType.ipv4 ;
        bacnet:ip-address "C0A80164"^^xsd:hexBinary ;
        bacnet:ip-default-gateway "C0A80101"^^xsd:hexBinary ;
    ] .

bldg:MyBACnetAirSensor
    a brick:Zone_Air_Temperature_Sensor ;
    rdfs:label "BACnet Zone Air Temp Sensor"@en ;
    brick:isPartOf bldg:Floor1 ;
    brick:hasUnit unit:DEG_C ;
    ref:hasExternalReference [
        a ref:BACnetReference ;
        bacnet:object-identifier "analog-value,5"^^bacnet:objectIdentifier ;
        bacnet:object-name "BLDG-Z410-ZATS" ;
        bacnet:objectOf bldg:sample-device ;
    ] .
`;

const EXAMPLE_QUERY = `PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?sensor ?label WHERE {
  ?sensor a brick:Temperature_Sensor .
  OPTIONAL { ?sensor rdfs:label ?label }
} LIMIT 20`;

export default function OntologyTab({ api, headers }) {
  const [graphs, setGraphs] = useState({});
  const [graphsLoading, setGraphsLoading] = useState(false);
  const [ttlText, setTtlText] = useState(EXAMPLE_TTL);
  const [graphUri, setGraphUri] = useState('urn:ontosage:custom:extension');
  const [validateResult, setValidateResult] = useState(null);
  const [uploadResult, setUploadResult] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [sparqlQuery, setSparqlQuery] = useState(EXAMPLE_QUERY);
  const [sparqlResult, setSparqlResult] = useState(null);
  const [sparqlRunning, setSparqlRunning] = useState(false);
  const [dropMsg, setDropMsg] = useState('');

  const loadGraphs = useCallback(async () => {
    setGraphsLoading(true);
    try {
      const r = await fetch(`${api}/api/v1/admin/ontology/graphs`, { headers });
      const d = await r.json();
      setGraphs(d.data?.graphs || {});
    } catch (e) {
      setGraphs({});
    } finally {
      setGraphsLoading(false);
    }
  }, [api, headers]);

  useEffect(() => { loadGraphs(); }, [loadGraphs]);

  const handleValidate = async () => {
    setValidateResult(null);
    const r = await fetch(`${api}/api/v1/admin/ontology/validate`, {
      method: 'POST', headers, body: JSON.stringify({ ttl: ttlText })
    });
    setValidateResult(await r.json());
  };

  const handleUpload = async () => {
    setUploading(true);
    setUploadResult(null);
    try {
      const r = await fetch(`${api}/api/v1/admin/ontology/upload`, {
        method: 'POST', headers,
        body: JSON.stringify({ ttl: ttlText, graph_uri: graphUri })
      });
      const d = await r.json();
      setUploadResult(d);
      if (d.success) loadGraphs();
    } finally {
      setUploading(false);
    }
  };

  const handleDrop = async (graphId) => {
    if (!window.confirm(`Delete named graph:\n${graphId}\n\nThis permanently removes all its triples. Continue?`)) return;
    setDropMsg('');
    const encoded = encodeURIComponent(graphId);
    const r = await fetch(`${api}/api/v1/admin/ontology/graphs/${encoded}`, {
      method: 'DELETE', headers
    });
    const d = await r.json();
    setDropMsg(d.success ? `Dropped: ${graphId}` : `Error: ${d.error}`);
    loadGraphs();
  };

  const handleSparql = async () => {
    setSparqlRunning(true);
    setSparqlResult(null);
    try {
      const r = await fetch(`${api}/api/v1/admin/ontology/sparql`, {
        method: 'POST', headers,
        body: JSON.stringify({ query: sparqlQuery, limit: 100 })
      });
      setSparqlResult(await r.json());
    } finally {
      setSparqlRunning(false);
    }
  };

  const handleFileUpload = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => setTtlText(ev.target.result);
    reader.readAsText(file);
    setGraphUri(`urn:ontosage:ttl:${file.name}`);
  };

  return (
    <div>
      <div className="mb-4">
        <div className="d-flex justify-content-between align-items-center mb-2">
          <h5>Named Graphs in GraphDB</h5>
          <button className="btn btn-sm btn-outline-secondary" onClick={loadGraphs} disabled={graphsLoading}>
            {graphsLoading ? 'Loading...' : 'Refresh'}
          </button>
        </div>
        {dropMsg && <div className={`alert alert-${dropMsg.startsWith('Error') ? 'danger' : 'success'} py-1`}>{dropMsg}</div>}
        <div style={{ maxHeight: 220, overflowY: 'auto' }}>
          <table className="table table-sm table-bordered mb-0">
            <thead className="table-light"><tr><th>Named Graph URI</th><th style={{width:90}}>Triples</th><th style={{width:70}}></th></tr></thead>
            <tbody>
              {Object.entries(graphs).length === 0 && (
                <tr><td colSpan={3} className="text-muted text-center">No named graphs found (GraphDB empty or unreachable)</td></tr>
              )}
              {Object.entries(graphs).sort((a,b) => b[1]-a[1]).map(([g, n]) => (
                <tr key={g}>
                  <td style={{fontFamily:'monospace',fontSize:12,wordBreak:'break-all'}}>{g}</td>
                  <td className="text-end">{n.toLocaleString()}</td>
                  <td className="text-center">
                    <button className="btn btn-xs btn-outline-danger py-0 px-1" style={{fontSize:11}}
                      onClick={() => handleDrop(g)}>Drop</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="row g-4">
        <div className="col-12 col-xl-6">
          <div className="card h-100">
            <div className="card-header"><strong>Upload TTL / Add Triples</strong></div>
            <div className="card-body">
              <div className="mb-2">
                <label className="form-label small">Named Graph URI</label>
                <input className="form-control form-control-sm font-monospace" value={graphUri}
                  onChange={e => setGraphUri(e.target.value)}
                  placeholder="urn:ontosage:ttl:my_extension.ttl" />
                <small className="text-muted">Convention: urn:ontosage:ttl:&lt;filename&gt; or urn:ontosage:custom:&lt;label&gt;</small>
              </div>
              <div className="mb-2">
                <label className="form-label small">Upload .ttl file (optional)</label>
                <input type="file" className="form-control form-control-sm" accept=".ttl,.n3,.owl"
                  onChange={handleFileUpload} />
              </div>
              <div className="mb-2">
                <label className="form-label small">Turtle content</label>
                <textarea className="form-control font-monospace" rows={10} value={ttlText}
                  onChange={e => setTtlText(e.target.value)} style={{fontSize:12}} />
              </div>
              {validateResult && (
                <div className={`alert py-1 alert-${validateResult.success ? 'success' : 'danger'} mb-2`} style={{fontSize:12}}>
                  {validateResult.success
                    ? `Valid - ${validateResult.data?.triple_count} triples, ${Object.keys(validateResult.data?.prefixes||{}).length} prefixes`
                    : `${validateResult.error || validateResult.data?.error}`}
                </div>
              )}
              {uploadResult && (
                <div className={`alert py-1 alert-${uploadResult.success ? 'success' : 'danger'} mb-2`} style={{fontSize:12}}>
                  {uploadResult.success
                    ? `Uploaded ${uploadResult.data?.triple_count} triples to ${uploadResult.data?.graph}`
                    : `${uploadResult.error}`}
                </div>
              )}
              <div className="d-flex gap-2">
                <button className="btn btn-outline-secondary btn-sm" onClick={handleValidate}>Validate</button>
                <button className="btn btn-primary btn-sm" onClick={handleUpload} disabled={uploading || !ttlText || !graphUri}>
                  {uploading ? 'Uploading...' : 'Upload to GraphDB'}
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="col-12 col-xl-6">
          <div className="card h-100">
            <div className="card-header"><strong>SPARQL Browser (read-only)</strong></div>
            <div className="card-body">
              <textarea className="form-control font-monospace mb-2" rows={8} value={sparqlQuery}
                onChange={e => setSparqlQuery(e.target.value)} style={{fontSize:12}} />
              <button className="btn btn-primary btn-sm mb-3" onClick={handleSparql} disabled={sparqlRunning}>
                {sparqlRunning ? 'Running...' : 'Run Query'}
              </button>
              {sparqlResult && (
                sparqlResult.success
                  ? (
                    <div style={{maxHeight:200,overflowY:'auto'}}>
                      <table className="table table-sm table-bordered" style={{fontSize:11}}>
                        <thead className="table-light">
                          <tr>{(sparqlResult.data?.columns||[]).map(c => <th key={c}>{c}</th>)}</tr>
                        </thead>
                        <tbody>
                          {(sparqlResult.data?.rows||[]).map((row,i) => (
                            <tr key={i}>{(sparqlResult.data?.columns||[]).map(c => (
                              <td key={c} style={{wordBreak:'break-all',maxWidth:200}}>{row[c]||''}</td>
                            ))}</tr>
                          ))}
                        </tbody>
                      </table>
                      <small className="text-muted">{sparqlResult.data?.count} rows</small>
                    </div>
                  )
                  : <div className="alert alert-danger py-1" style={{fontSize:12}}>{sparqlResult.error}</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
