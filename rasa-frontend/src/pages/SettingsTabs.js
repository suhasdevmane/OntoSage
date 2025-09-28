import React, { useState } from 'react';
import TopNav from '../components/TopNav';
import SettingsEditor from './SettingsEditor';
import Settings from './Settings';
import ActionServerTab from './ActionServerTab';

export default function SettingsTabs() {
  const [tab, setTab] = useState('edit');
  return (
    <div className="home-body">
      <TopNav />
      <div className="container mt-4" id="content">
        <h2>Settings</h2>
        <ul className="nav nav-tabs mt-3">
          <li className="nav-item">
            <button className={`nav-link ${tab==='edit'?'active':''}`} onClick={() => setTab('edit')}>Edit & Validate</button>
          </li>
          <li className="nav-item">
            <button className={`nav-link ${tab==='train'?'active':''}`} onClick={() => setTab('train')}>Train & Activate</button>
          </li>
          <li className="nav-item">
            <button className={`nav-link ${tab==='action'?'active':''}`} onClick={() => setTab('action')}>Action Server</button>
          </li>
        </ul>
        <div className="mt-3">
          {tab === 'edit' ? <SettingsEditor /> : tab === 'train' ? <Settings embedded={true} /> : <ActionServerTab />}
        </div>
      </div>
    </div>
  );
}
