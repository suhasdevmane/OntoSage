// src/pages/About.js
import React from 'react';
import TopNav from '../components/TopNav';

export default function About() {
  return (
    <div className="home-body">
      <TopNav />
      <div className="container mt-4">
        <h2>About this Project</h2>
        <p>
          This Rasa-based assistant integrates a custom action server, Duckling for entity extraction,
          and a local file server for serving generated artifacts. It supports per-user authentication
          and per-user chat history and artifacts.
        </p>
        <p>
          Use the chat widget to ask questions, generate data artifacts (JSON/CSV/HTML/PDF/audio/video),
          and download them directly. The system is dockerized for quick setup and development.
        </p>
      </div>
    </div>
  );
}
