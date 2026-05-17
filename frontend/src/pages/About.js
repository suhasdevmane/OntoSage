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
          OntoSage is an agentic AI framework for smart buildings. It integrates a knowledge graph
          (GraphDB/SPARQL), time-series databases, and language models to answer natural language
          questions about building systems, sensor data, and operations.
        </p>
        <p>
          Use the chat widget to ask questions about building analytics, discover sensors and zones,
          generate reports, detect anomalies, and download artifacts (CSV/JSON/HTML). The system
          supports per-user authentication, RBAC, and chat history. It is fully dockerized for
          quick setup and scalable deployment.
        </p>
      </div>
    </div>
  );
}
