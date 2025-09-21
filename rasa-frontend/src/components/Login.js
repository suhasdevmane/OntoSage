// src/components/Login.js
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import db from '../db';

const API_BASE = 'http://localhost:8080/api';

function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const navigate = useNavigate();

  const handleLogin = async (e) => {
    e.preventDefault();

    const doRegister = async () => {
      try {
        const res = await fetch(`${API_BASE}/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ username, password })
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          alert(data.error || 'Registration failed');
          return false;
        }
        // Mirror in Dexie for offline cache
        const existing = await db.users.where('username').equals(username).first();
        if (!existing) {
          await db.users.add({ username, password });
        }
        await db.chatHistory.add({ username, messages: [] });
        sessionStorage.setItem('currentUser', username);
        navigate('/chat');
        return true;
      } catch (err) {
        console.error('Registration error:', err);
        alert('Registration error. Please try again.');
        return false;
      }
    };

    try {
      // Attempt login against backend
      const res = await fetch(`${API_BASE}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ username, password })
      });
      if (res.ok) {
        sessionStorage.setItem('currentUser', username);
        // Keep a copy locally (for offline viewing)
        const existing = await db.users.where('username').equals(username).first();
        if (!existing) {
          await db.users.add({ username, password });
        }
        navigate('/chat');
        return;
      }
      if (res.status === 401) {
        // Offer registration on invalid credentials
        if (window.confirm('Invalid username or password. Would you like to register this username?')) {
          await doRegister();
        }
        return;
      }
      if (res.status === 404 || res.status === 400) {
        // Fall through to registration prompt
      }
    } catch (err) {
      console.error('Login error, falling back to register flow:', err);
    }

    // Offer to register if login failed / user not found
    if (window.confirm('User not found. Would you like to register?')) {
      await doRegister();
    }
  };

  return (
    <div className="login-container" style={{ margin: '50px auto', width: '300px' }}>
      <h2>Login / Register</h2>
      <form onSubmit={handleLogin}>
        <div>
          <label>Username:</label>
          <input 
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required 
            style={{ width: '100%', marginBottom: '10px' }}
          />
        </div>
        <div>
          <label>Password:</label>
          <input 
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required 
            style={{ width: '100%', marginBottom: '10px' }}
          />
        </div>
        <button type="submit" style={{ width: '100%' }}>Login / Register</button>
      </form>
    </div>
  );
}

export default Login;
