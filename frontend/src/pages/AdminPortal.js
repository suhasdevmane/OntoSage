import React, { useState, useEffect } from 'react';
import TopNav from '../components/TopNav';
import OntologyTab from '../components/admin/OntologyTab';
import CapabilitiesTab from '../components/admin/CapabilitiesTab';
import DatabasesTab from '../components/admin/DatabasesTab';
import UsersTab from '../components/admin/UsersTab';
import DataSourcesTab from '../components/admin/DataSourcesTab';
import SystemTab from '../components/admin/SystemTab';
import IndexStatusTab from '../components/admin/IndexStatusTab';
import AuditTab from '../components/admin/AuditTab';
import CoverageTab from '../components/admin/CoverageTab';

const API = 'http://localhost:8000';

function useAdminToken() {
  const [token, setToken] = useState(() => sessionStorage.getItem('session_token'));
  useEffect(() => {
    const sync = () => setToken(sessionStorage.getItem('session_token'));
    window.addEventListener('auth-changed', sync);
    return () => window.removeEventListener('auth-changed', sync);
  }, []);
  return token;
}

const TABS = [
  { id: 'ontology', label: 'Ontology' },
  { id: 'capabilities', label: 'Capabilities' },
  { id: 'databases', label: 'Databases' },
  { id: 'datasources', label: 'Data Sources' },
  { id: 'index', label: 'Index Status' },
  { id: 'users', label: 'Users' },
  { id: 'system', label: 'System' },
  { id: 'audit', label: 'Audit Log' },
  { id: 'coverage', label: 'Coverage' },
];

export default function AdminPortal() {
  const [tab, setTab] = useState('ontology');
  const token = useAdminToken();

  if (!token) {
    return (
      <div className="home-body">
        <TopNav />
        <div className="container mt-5">
          <div className="alert alert-warning">
            Please <a href="/login">log in</a> with an admin account to access the admin portal.
          </div>
        </div>
      </div>
    );
  }

  const authHeaders = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  const props = { api: API, headers: authHeaders };

  return (
    <div className="home-body">
      <TopNav />
      <div className="container-fluid mt-3 px-4" id="content">
        <div className="d-flex align-items-center mb-3">
          <h2 className="me-3">Admin Portal</h2>
          <span className="badge bg-danger">system:admin</span>
        </div>
        <ul className="nav nav-tabs flex-wrap">
          {TABS.map(t => (
            <li className="nav-item" key={t.id}>
              <button
                className={`nav-link ${tab === t.id ? 'active' : ''}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            </li>
          ))}
        </ul>
        <div className="tab-content border border-top-0 p-3 bg-white rounded-bottom">
          {tab === 'ontology' && <OntologyTab {...props} />}
          {tab === 'capabilities' && <CapabilitiesTab {...props} />}
          {tab === 'databases' && <DatabasesTab {...props} />}
          {tab === 'datasources' && <DataSourcesTab {...props} />}
          {tab === 'index' && <IndexStatusTab {...props} />}
          {tab === 'users' && <UsersTab {...props} />}
          {tab === 'system' && <SystemTab {...props} />}
          {tab === 'audit' && <AuditTab {...props} />}
          {tab === 'coverage' && <CoverageTab {...props} />}
        </div>
      </div>
    </div>
  );
}
