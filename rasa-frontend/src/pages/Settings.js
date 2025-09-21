// src/pages/Settings.js
import React from 'react';
import TopNav from '../components/TopNav';

export default function Settings() {
  return (
    <div className="home-body">
      <TopNav />
      <div className="container mt-4" id="content">
        <h2>Settings</h2>
        <p className="text-muted">Configure frontend options and health-check preferences here (placeholder).</p>
        {/* Future: add forms for base URLs, timeouts, authentication, etc. */}
      </div>
    </div>
  );
}
