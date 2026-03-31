import React, { useState, useEffect, useRef } from 'react';
import Select from 'react-select';

const ModelTrainingTab = () => {
  // State for sensors
  const [sensors, setSensors] = useState([]);
  const [loadingSensors, setLoadingSensors] = useState(true);

  // State for training examples
  const [examples, setExamples] = useState([]);
  const [loadingExamples, setLoadingExamples] = useState(true);

  // State for form inputs
  const [question, setQuestion] = useState('');
  const [selectedSensors, setSelectedSensors] = useState([]);
  const [sparqlQuery, setSparqlQuery] = useState('');
  const [category, setCategory] = useState('user_defined');
  const [notes, setNotes] = useState('');

  // State for training job
  const [trainingJobId, setTrainingJobId] = useState(null);
  const [trainingStatus, setTrainingStatus] = useState('idle'); // idle, running, completed, error
  const [trainingProgress, setTrainingProgress] = useState(0);
  const [trainingLogs, setTrainingLogs] = useState('');
  const [epochs, setEpochs] = useState(10);

  // State for models
  const [availableModels, setAvailableModels] = useState([]);
  const [loadingModels, setLoadingModels] = useState(false);

  // State for editing
  const [editingIndex, setEditingIndex] = useState(null);

  const logsEndRef = useRef(null);

  // Auto-scroll logs
  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [trainingLogs]);

  // Load sensors on mount
  useEffect(() => {
    loadSensors();
    loadExamples();
    loadModels();
  }, []);

  // Poll training status
  const pollTrainingStatus = async (jobId) => {
    try {
      const response = await fetch(`http://localhost:6001/api/t5/train/${jobId}/status`);
      const data = await response.json();
      
      if (data.ok) {
        const job = data.job;
        setTrainingStatus(job.status);
        setTrainingProgress(job.progress || 0);
        setTrainingLogs(job.logs || '');
        
        if (job.status === 'completed' || job.status === 'error') {
          setTrainingStatus(job.status);
          loadModels();
        }
      }
    } catch (error) {
      console.error('Error polling training status:', error);
    }
  };

  useEffect(() => {
    if (trainingJobId && trainingStatus === 'running') {
      const interval = setInterval(() => {
        pollTrainingStatus(trainingJobId);
      }, 2000);
      return () => clearInterval(interval);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trainingJobId, trainingStatus]);

  const loadSensors = async () => {
    try {
      setLoadingSensors(true);
      console.log('Fetching sensors from http://localhost:6001/api/t5/sensors...');
      const response = await fetch('http://localhost:6001/api/t5/sensors');
      console.log('Response status:', response.status);
      const data = await response.json();
      console.log('Response data:', data);
      console.log('Number of sensors received:', data.sensors?.length);
      if (data.ok) {
        const sensorOptions = data.sensors.map(s => ({ value: s, label: s }));
        console.log('Setting sensors state with', sensorOptions.length, 'options');
        console.log('First 3 sensor options:', sensorOptions.slice(0, 3));
        setSensors(sensorOptions);
      } else {
        console.error('API returned ok:false');
      }
    } catch (error) {
      console.error('Error loading sensors:', error);
      console.error('Error details:', error.message, error.stack);
    } finally {
      setLoadingSensors(false);
      console.log('loadingSensors set to false');
    }
  };

  const loadExamples = async () => {
    try {
      setLoadingExamples(true);
      const response = await fetch('http://localhost:6001/api/t5/examples');
      const data = await response.json();
      if (data.ok) {
        setExamples(data.examples);
      }
    } catch (error) {
      console.error('Error loading examples:', error);
    } finally {
      setLoadingExamples(false);
    }
  };

  const loadModels = async () => {
    try {
      setLoadingModels(true);
      const response = await fetch('http://localhost:6001/api/t5/models');
      const data = await response.json();
      if (data.ok) {
        setAvailableModels(data.models);
      }
    } catch (error) {
      console.error('Error loading models:', error);
    } finally {
      setLoadingModels(false);
    }
  };

  const handleAddExample = async (e) => {
    e.preventDefault();
    
    if (!question.trim() || !sparqlQuery.trim()) {
      alert('Question and SPARQL query are required');
      return;
    }

    const newExample = {
      question: question.trim(),
      entities: selectedSensors.map(s => s.value),
      sparql: sparqlQuery.trim(),
      category: category,
      notes: notes.trim()
    };

    try {
      const url = editingIndex !== null
        ? `http://localhost:6001/api/t5/examples/${editingIndex}`
        : 'http://localhost:6001/api/t5/examples';
      
      const method = editingIndex !== null ? 'PUT' : 'POST';

      const response = await fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newExample)
      });

      const data = await response.json();
      if (data.ok) {
        await loadExamples();
        clearForm();
        alert(editingIndex !== null ? 'Example updated successfully!' : 'Example added successfully!');
      } else {
        alert('Error: ' + data.error);
      }
    } catch (error) {
      console.error('Error adding example:', error);
      alert('Failed to add example: ' + error.message);
    }
  };

  const handleEditExample = (index) => {
    const example = examples[index];
    setQuestion(example.question);
    setSelectedSensors(example.entities.map(e => ({ value: e, label: e })));
    setSparqlQuery(example.sparql);
    setCategory(example.category || 'user_defined');
    setNotes(example.notes || '');
    setEditingIndex(index);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleDeleteExample = async (index) => {
    if (!window.confirm('Are you sure you want to delete this example?')) {
      return;
    }

    try {
      const response = await fetch(`http://localhost:6001/api/t5/examples/${index}`, {
        method: 'DELETE'
      });

      const data = await response.json();
      if (data.ok) {
        await loadExamples();
        alert('Example deleted successfully!');
      } else {
        alert('Error: ' + data.error);
      }
    } catch (error) {
      console.error('Error deleting example:', error);
      alert('Failed to delete example: ' + error.message);
    }
  };

  const clearForm = () => {
    setQuestion('');
    setSelectedSensors([]);
    setSparqlQuery('');
    setCategory('user_defined');
    setNotes('');
    setEditingIndex(null);
  };

  const handleStartTraining = async () => {
    if (examples.length === 0) {
      alert('Please add at least one training example');
      return;
    }

    if (!window.confirm(`Start training with ${examples.length} examples for ${epochs} epochs? This may take 5-10 minutes.`)) {
      return;
    }

    try {
      const response = await fetch('http://localhost:6001/api/t5/train', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ epochs: epochs })
      });

      const data = await response.json();
      if (data.ok) {
        setTrainingJobId(data.job_id);
        setTrainingStatus('running');
        setTrainingProgress(0);
        setTrainingLogs('Training started...\n');
      } else {
        alert('Error starting training: ' + data.error);
      }
    } catch (error) {
      console.error('Error starting training:', error);
      alert('Failed to start training: ' + error.message);
    }
  };

  const handleDeployModel = async () => {
    if (!trainingJobId || trainingStatus !== 'completed') {
      alert('No completed training to deploy');
      return;
    }

    if (!window.confirm('Deploy this model to production? This will replace the current active model.')) {
      return;
    }

    try {
      const response = await fetch('http://localhost:6001/api/t5/deploy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: trainingJobId })
      });

      const data = await response.json();
      if (data.ok) {
        alert('Model deployed successfully! Please restart the action server to use the new model.');
        await loadModels();
      } else {
        alert('Error deploying model: ' + data.error);
      }
    } catch (error) {
      console.error('Error deploying model:', error);
      alert('Failed to deploy model: ' + error.message);
    }
  };

  return (
    <div className="model-training-tab">
      <h3>T5 Model Training</h3>
      <p className="text-muted">Train the NL2SPARQL model with custom examples</p>

      {/* Add/Edit Example Form */}
      <div className="card mb-4">
        <div className="card-header">
          <h5>{editingIndex !== null ? 'Edit' : 'Add'} Training Example</h5>
        </div>
        <div className="card-body">
          <form onSubmit={handleAddExample}>
            <div className="form-group mb-3">
              <label>Question *</label>
              <input
                type="text"
                className="form-control"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="e.g., What is the correlation between temperature and humidity in zone 5.04?"
                required
              />
            </div>

            <div className="form-group mb-3">
              <label>Sensors Involved</label>
              {/* Debug info */}
              <div style={{fontSize: '0.8em', color: '#666', marginBottom: '5px'}}>
                Debug: {loadingSensors ? 'Loading...' : `${sensors.length} sensors loaded`}
              </div>
              <Select
                isMulti
                value={selectedSensors}
                onChange={setSelectedSensors}
                options={sensors}
                isLoading={loadingSensors}
                placeholder="Select sensors mentioned in the question..."
                className="basic-multi-select"
                classNamePrefix="select"
              />
            </div>

            <div className="form-group mb-3">
              <label>SPARQL Query *</label>
              <textarea
                className="form-control"
                value={sparqlQuery}
                onChange={(e) => setSparqlQuery(e.target.value)}
                placeholder="SELECT ?sensor ?timeseriesId WHERE { ... }"
                rows="8"
                style={{ fontFamily: 'monospace', fontSize: '0.9em' }}
                required
              />
            </div>

            <div className="row">
              <div className="col-md-6">
                <div className="form-group mb-3">
                  <label>Category</label>
                  <select
                    className="form-control"
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                  >
                    <option value="user_defined">User Defined</option>
                    <option value="multi_sensor_correlation">Multi-Sensor Correlation</option>
                    <option value="single_sensor">Single Sensor</option>
                    <option value="complex_query">Complex Query</option>
                  </select>
                </div>
              </div>
              <div className="col-md-6">
                <div className="form-group mb-3">
                  <label>Notes (Optional)</label>
                  <input
                    type="text"
                    className="form-control"
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Any notes about this example..."
                  />
                </div>
              </div>
            </div>

            <div className="d-flex gap-2">
              <button type="submit" className="btn btn-primary">
                {editingIndex !== null ? 'Update' : 'Add'} Example
              </button>
              {editingIndex !== null && (
                <button type="button" className="btn btn-secondary" onClick={clearForm}>
                  Cancel Edit
                </button>
              )}
            </div>
          </form>
        </div>
      </div>

      {/* Training Examples List */}
      <div className="card mb-4">
        <div className="card-header d-flex justify-content-between align-items-center">
          <h5>Training Examples ({examples.length})</h5>
          <button className="btn btn-sm btn-outline-primary" onClick={loadExamples}>
            Refresh
          </button>
        </div>
        <div className="card-body">
          {loadingExamples ? (
            <div className="text-center">Loading examples...</div>
          ) : examples.length === 0 ? (
            <div className="text-center text-muted">No training examples yet. Add one above!</div>
          ) : (
            <div className="table-responsive">
              <table className="table table-sm table-hover">
                <thead>
                  <tr>
                    <th style={{ width: '5%' }}>#</th>
                    <th style={{ width: '35%' }}>Question</th>
                    <th style={{ width: '20%' }}>Entities</th>
                    <th style={{ width: '15%' }}>Category</th>
                    <th style={{ width: '15%' }}>Notes</th>
                    <th style={{ width: '10%' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {examples.map((example, index) => (
                    <tr key={index}>
                      <td>{index + 1}</td>
                      <td style={{ fontSize: '0.9em' }}>{example.question}</td>
                      <td>
                        <span className="badge bg-secondary">
                          {example.entities?.length || 0} sensors
                        </span>
                      </td>
                      <td>
                        <span className="badge bg-info text-dark">
                          {example.category || 'N/A'}
                        </span>
                      </td>
                      <td style={{ fontSize: '0.85em', color: '#666' }}>
                        {example.notes || '-'}
                      </td>
                      <td>
                        <button
                          className="btn btn-sm btn-outline-primary me-1"
                          onClick={() => handleEditExample(index)}
                          title="Edit"
                        >
                          ✏️
                        </button>
                        <button
                          className="btn btn-sm btn-outline-danger"
                          onClick={() => handleDeleteExample(index)}
                          title="Delete"
                        >
                          🗑️
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Training Section */}
      <div className="card mb-4">
        <div className="card-header">
          <h5>Train Model</h5>
        </div>
        <div className="card-body">
          <div className="row mb-3">
            <div className="col-md-6">
              <label>Training Epochs</label>
              <input
                type="number"
                className="form-control"
                value={epochs}
                onChange={(e) => setEpochs(parseInt(e.target.value) || 10)}
                min="1"
                max="50"
                disabled={trainingStatus === 'running'}
              />
              <small className="text-muted">More epochs = better learning but longer training time</small>
            </div>
            <div className="col-md-6 d-flex align-items-end">
              <button
                className="btn btn-success w-100"
                onClick={handleStartTraining}
                disabled={trainingStatus === 'running' || examples.length === 0}
              >
                {trainingStatus === 'running' ? 'Training...' : 'Start Training'}
              </button>
            </div>
          </div>

          {trainingStatus !== 'idle' && (
            <>
              <div className="mb-3">
                <div className="d-flex justify-content-between mb-2">
                  <span>Progress: {trainingProgress}%</span>
                  <span className={`badge ${trainingStatus === 'completed' ? 'bg-success' : trainingStatus === 'error' ? 'bg-danger' : 'bg-primary'}`}>
                    {trainingStatus.toUpperCase()}
                  </span>
                </div>
                <div className="progress">
                  <div
                    className={`progress-bar ${trainingStatus === 'error' ? 'bg-danger' : 'progress-bar-striped progress-bar-animated'}`}
                    role="progressbar"
                    style={{ width: `${trainingProgress}%` }}
                  />
                </div>
              </div>

              <div className="mb-3">
                <label>Training Logs</label>
                <div
                  style={{
                    background: '#1e1e1e',
                    color: '#d4d4d4',
                    padding: '15px',
                    borderRadius: '5px',
                    fontFamily: 'monospace',
                    fontSize: '0.85em',
                    maxHeight: '300px',
                    overflowY: 'auto'
                  }}
                >
                  <pre style={{ margin: 0, color: '#d4d4d4' }}>
                    {trainingLogs || 'Waiting for logs...'}
                    <div ref={logsEndRef} />
                  </pre>
                </div>
              </div>

              {trainingStatus === 'completed' && (
                <button
                  className="btn btn-primary"
                  onClick={handleDeployModel}
                >
                  Deploy Model to Production
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {/* Available Models */}
      <div className="card">
        <div className="card-header d-flex justify-content-between align-items-center">
          <h5>Available Models</h5>
          <button className="btn btn-sm btn-outline-primary" onClick={loadModels}>
            Refresh
          </button>
        </div>
        <div className="card-body">
          {loadingModels ? (
            <div className="text-center">Loading models...</div>
          ) : availableModels.length === 0 ? (
            <div className="text-center text-muted">No trained models found</div>
          ) : (
            <div className="table-responsive">
              <table className="table table-sm">
                <thead>
                  <tr>
                    <th>Model Name</th>
                    <th>Last Modified</th>
                    <th>Size (MB)</th>
                  </tr>
                </thead>
                <tbody>
                  {availableModels.map((model, index) => (
                    <tr key={index}>
                      <td>
                        <code>{model.name}</code>
                        {model.name === 'checkpoint-3' && (
                          <span className="badge bg-success ms-2">Production</span>
                        )}
                      </td>
                      <td>{new Date(model.modified).toLocaleString()}</td>
                      <td>{model.size_mb.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ModelTrainingTab;
