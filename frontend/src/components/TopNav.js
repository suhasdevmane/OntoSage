// src/components/TopNav.js
import React from 'react';
import { Link } from 'react-router-dom';

export default function TopNav() {
  const currentUser = sessionStorage.getItem('currentUser');
  const handleLogout = async () => {
    try {
      await fetch('http://localhost:8080/api/logout', { method: 'POST', credentials: 'include' });
    } catch {}
    sessionStorage.removeItem('currentUser');
    sessionStorage.removeItem('chatbot_minimized');
    window.dispatchEvent(new Event('auth-changed'));
    // Slight delay to allow state to propagate
    setTimeout(() => { window.location.href = '/login'; }, 0);
  };

  return (
    <nav className="navbar navbar-expand-lg navbar-light bg-light">
      <div className="container">
        <Link className="navbar-brand" to="/">Abacws SmartBot</Link>

        <button
          className="navbar-toggler"
          type="button"
          data-toggle="collapse"
          data-target="#navbarScroll"
          aria-controls="navbarScroll"
          aria-expanded="false"
          aria-label="Toggle navigation"
        >
          <span className="navbar-toggler-icon" />
        </button>

        <div className="collapse navbar-collapse" id="navbarScroll">
          <ul className="navbar-nav mr-auto my-2 my-lg-0 navbar-nav-scroll">
            <li className="nav-item">
              <Link className="nav-link" to="/">Home</Link>
            </li>
            <li className="nav-item">
              <a className="nav-link" href="https://suhasdevmane.github.io/" target="_blank" rel="noreferrer">Docs</a>
            </li>
            <li className="nav-item">
              <Link className="nav-link" to="/links">Links</Link>
            </li>
            <li className="nav-item">
              <Link className="nav-link" to="/about">About us</Link>
            </li>
            <li className="nav-item">
              <Link className="nav-link" to="/health">Health Check</Link>
            </li>
            <li className="nav-item">
              <Link className="nav-link" to="/settings">Settings</Link>
            </li>
          </ul>

          <form className="form-inline my-2 my-lg-0 d-flex align-items-center ms-auto" onSubmit={(e) => e.preventDefault()}>
            <input
              className="form-control mr-sm-2"
              type="search"
              placeholder="Search"
              aria-label="Search"
            />
            <button className="btn btn-outline-success my-2 my-sm-0" type="button">Search</button>
            <div className="d-flex align-items-center ms-3">
              {currentUser ? (
                <>
                  <span style={{ fontSize: 14, marginRight: 10 }}>Logged in as <strong>{currentUser}</strong></span>
                  <button type="button" className="btn btn-danger btn-sm" onClick={handleLogout}>Logout</button>
                </>
              ) : (
                <Link className="btn btn-primary btn-sm" to="/login">Login</Link>
              )}
            </div>
          </form>
        </div>
      </div>
    </nav>
  );
}
