// src/components/Login.js
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Form, Button, Alert, Container, Card, Spinner } from 'react-bootstrap';
import db from '../db';

const ORCHESTRATOR_API = process.env.REACT_APP_API_URL || 'http://localhost:8000';

function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [email, setEmail] = useState('');
  const [isRegistering, setIsRegistering] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);
  const [apiStatus, setApiStatus] = useState('checking');
  const navigate = useNavigate();

  // Check if already logged in
  useEffect(() => {
    const currentUser = sessionStorage.getItem('currentUser');
    const token = sessionStorage.getItem('session_token');
    if (currentUser && token) {
      navigate('/chat');
    }
  }, [navigate]);

  // Check API connectivity on mount
  useEffect(() => {
    const checkAPI = async () => {
      try {
        const res = await fetch(`${ORCHESTRATOR_API}/health`, {
          method: 'GET',
          signal: AbortSignal.timeout(5000)
        });
        if (res.ok) {
          setApiStatus('connected');
        } else {
          setApiStatus('error');
          setError('Orchestrator API is not responding. Please check if services are running.');
        }
      } catch (err) {
        setApiStatus('error');
        setError(`Cannot connect to API at ${ORCHESTRATOR_API}. Please ensure containers are running.`);
      }
    };
    checkAPI();
  }, []);

  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);

    try {
      console.log('Attempting login for:', username);
      
      const res = await fetch(`${ORCHESTRATOR_API}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ username, password })
      });

      const data = await res.json();
      console.log('Login response:', data);

      if (!res.ok) {
        // Provide specific error messages
        if (res.status === 401) {
          throw new Error('Invalid username or password. Please try again or register a new account.');
        } else if (res.status === 404) {
          throw new Error('User not found. Please register first.');
        }
        throw new Error(data.detail || data.message || 'Login failed');
      }

      // Check if we got a session token
      // API returns { success: true, data: { session_token: "..." } }
      const sessionToken = data.data?.session_token || data.session_token;
      
      if (!sessionToken) {
        throw new Error('Login succeeded but no session token received');
      }

      // Store session info
      sessionStorage.setItem('currentUser', username);
      sessionStorage.setItem('session_token', sessionToken);
      sessionStorage.setItem('chatbot_minimized', 'false'); // Show chat by default
      
      console.log('Session token stored:', data.session_token.substring(0, 10) + '...');

      // Cache user in local DB (don't store password)
      try {
        const existing = await db.users.where('username').equals(username).first();
        if (!existing) {
          await db.users.add({ username, password: '' });
        }
      } catch (dbErr) {
        console.warn('Local DB cache failed (non-critical):', dbErr);
      }

      // Trigger auth change event
      window.dispatchEvent(new Event('auth-changed'));

      setSuccess('Login successful! Loading chat...');
      setTimeout(() => navigate('/chat'), 800);

    } catch (err) {
      console.error('Login error:', err);
      setError(err.message || 'Login failed. Please check your credentials.');
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);

    try {
      // Validate input
      if (username.length < 3) {
        throw new Error('Username must be at least 3 characters');
      }
      if (password.length < 6) {
        throw new Error('Password must be at least 6 characters');
      }
      if (!/^[a-zA-Z0-9_]+$/.test(username)) {
        throw new Error('Username can only contain letters, numbers, and underscores');
      }

      console.log('Attempting registration for:', username);

      const res = await fetch(`${ORCHESTRATOR_API}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ username, password, email: email || undefined })
      });

      const data = await res.json();
      console.log('Registration response:', data);

      if (!res.ok) {
        if (res.status === 409 || data.detail?.includes('already exists')) {
          throw new Error('Username already exists. Please choose a different username or login.');
        }
        throw new Error(data.detail || data.message || 'Registration failed');
      }

      setSuccess('✓ Registration successful! You can now login with your credentials.');
      setIsRegistering(false);
      setPassword('');
      setEmail('');

    } catch (err) {
      console.error('Registration error:', err);
      setError(err.message || 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Container className="d-flex justify-content-center align-items-center" style={{ minHeight: '100vh', backgroundColor: '#f5f7fa' }}>
      <Card style={{ width: '450px', padding: '30px', boxShadow: '0 8px 16px rgba(0,0,0,0.1)', borderRadius: '12px' }}>
        <Card.Body>
          {/* Header */}
          <div className="text-center mb-4">
            <h2 className="mb-2" style={{ color: '#2c3e50', fontWeight: '600' }}>
              {isRegistering ? '🔐 Create Account' : '🏢 Welcome Back'}
            </h2>
            <p className="text-muted" style={{ fontSize: '0.9rem' }}>
              {isRegistering 
                ? 'Sign up to access OntoSage AI Assistant' 
                : 'Sign in to your OntoSage account'}
            </p>
          </div>

          {/* API Status Indicator */}
          {apiStatus === 'checking' && (
            <Alert variant="info" className="d-flex align-items-center">
              <Spinner animation="border" size="sm" className="me-2" />
              Connecting to OntoSage services...
            </Alert>
          )}
          
          {apiStatus === 'error' && error && (
            <Alert variant="danger">
              <strong>⚠️ Connection Error</strong>
              <p className="mb-0 mt-2" style={{ fontSize: '0.9rem' }}>{error}</p>
            </Alert>
          )}

          {apiStatus === 'connected' && error && !error.includes('connect') && (
            <Alert variant="danger">
              <strong>❌ {isRegistering ? 'Registration' : 'Login'} Failed</strong>
              <p className="mb-0 mt-2" style={{ fontSize: '0.9rem' }}>{error}</p>
            </Alert>
          )}
          
          {success && (
            <Alert variant="success">
              <strong>✅ Success!</strong>
              <p className="mb-0 mt-2" style={{ fontSize: '0.9rem' }}>{success}</p>
            </Alert>
          )}

          <Form onSubmit={isRegistering ? handleRegister : handleLogin}>
            {/* Username Field */}
            <Form.Group className="mb-3" controlId="formUsername">
              <Form.Label style={{ fontWeight: '500' }}>Username</Form.Label>
              <Form.Control
                type="text"
                placeholder="Enter your username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                minLength={3}
                maxLength={30}
                pattern="[a-zA-Z0-9_]+"
                disabled={loading || apiStatus === 'error'}
                style={{ padding: '10px', fontSize: '0.95rem' }}
              />
              <Form.Text className="text-muted" style={{ fontSize: '0.85rem' }}>
                {isRegistering ? '3-30 characters (letters, numbers, underscore only)' : 'Your registered username'}
              </Form.Text>
            </Form.Group>

            {/* Password Field */}
            <Form.Group className="mb-3" controlId="formPassword">
              <Form.Label style={{ fontWeight: '500' }}>Password</Form.Label>
              <Form.Control
                type="password"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={6}
                disabled={loading || apiStatus === 'error'}
                style={{ padding: '10px', fontSize: '0.95rem' }}
              />
              <Form.Text className="text-muted" style={{ fontSize: '0.85rem' }}>
                {isRegistering ? 'Minimum 6 characters' : 'Enter your password'}
              </Form.Text>
            </Form.Group>

            {/* Email Field (Registration Only) */}
            {isRegistering && (
              <Form.Group className="mb-3" controlId="formEmail">
                <Form.Label style={{ fontWeight: '500' }}>Email <span className="text-muted">(Optional)</span></Form.Label>
                <Form.Control
                  type="email"
                  placeholder="your.email@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={loading || apiStatus === 'error'}
                  style={{ padding: '10px', fontSize: '0.95rem' }}
                />
                <Form.Text className="text-muted" style={{ fontSize: '0.85rem' }}>
                  For password recovery and notifications
                </Form.Text>
              </Form.Group>
            )}

            {/* Submit Button */}
            <Button
              variant={isRegistering ? 'success' : 'primary'}
              type="submit"
              className="w-100 mb-3"
              disabled={loading || apiStatus === 'error'}
              style={{ padding: '12px', fontSize: '1rem', fontWeight: '500' }}
            >
              {loading ? (
                <>
                  <Spinner animation="border" size="sm" className="me-2" />
                  {isRegistering ? 'Creating Account...' : 'Signing In...'}
                </>
              ) : (
                isRegistering ? '✨ Create Account' : '🚀 Sign In'
              )}
            </Button>
          </Form>

          {/* Toggle Login/Register */}
          <div className="text-center mb-3">
            <hr style={{ margin: '20px 0' }} />
            <Button
              variant="link"
              onClick={() => {
                setIsRegistering(!isRegistering);
                setError('');
                setSuccess('');
                setPassword('');
                setEmail('');
              }}
              disabled={loading}
              style={{ textDecoration: 'none', fontSize: '0.95rem' }}
            >
              {isRegistering 
                ? '👤 Already have an account? Sign In' 
                : '📝 Don\'t have an account? Register'}
            </Button>
          </div>

          {/* Test Credentials (Development Only) */}
          {process.env.NODE_ENV === 'development' && !isRegistering && (
            <Alert variant="info" style={{ fontSize: '0.85rem', padding: '10px' }}>
              <strong>🧪 Test Credentials:</strong>
              <div className="mt-1">
                <code>testuser / test123</code>
              </div>
            </Alert>
          )}

          {/* Footer */}
          <div className="text-center mt-4">
            <small className="text-muted" style={{ fontSize: '0.8rem' }}>
              <strong>OntoSage 2.0</strong> - Intelligent Building Assistant
              <br />
              Powered by Brick Schema & SPARQL
            </small>
          </div>
        </Card.Body>
      </Card>
    </Container>
  );
}

export default Login;
