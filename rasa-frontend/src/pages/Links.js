// src/pages/Links.js
import React from 'react';
import TopNav from '../components/TopNav';

export default function Links() {
  return (
    <div className="home-body">
      <TopNav />
      <div className="container mt-4">
        <h2>Useful Links</h2>
        <p>Add your own links here (GitHub, research, docs, etc.).</p>
        <ul>
          <li><a href="https://github.com/" target="_blank" rel="noreferrer">GitHub</a></li>
          <li><a href="https://arxiv.org/" target="_blank" rel="noreferrer">arXiv</a></li>
          <li><a href="https://scholar.google.com/" target="_blank" rel="noreferrer">Google Scholar</a></li>
          <li><a href="https://rasa.com/docs/rasa/" target="_blank" rel="noreferrer">Rasa Docs</a></li>
        </ul>
      </div>
    </div>
  );
}
