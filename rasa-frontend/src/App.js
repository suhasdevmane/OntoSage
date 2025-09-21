// src/App.js
import React from 'react';
import { BrowserRouter as Router, Route, Routes, Navigate } from 'react-router-dom';
import ChatBot from './components/ChatBot';
import Login from './components/Login';
import Home from './components/Home';
import Links from './pages/Links';
import About from './pages/About';
import Health from './pages/Health';
import Settings from './pages/Settings';

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Home />} />
        <Route path="/links" element={<Links />} />
        <Route path="/about" element={<About />} />
  <Route path="/health" element={<Health />} />
  <Route path="/settings" element={<Settings />} />
        <Route path="/chat" element={<Home />} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
      {/* Floating chat widget, visible on all pages */}
      <ChatBot />
    </Router>
  );
}

export default App;
