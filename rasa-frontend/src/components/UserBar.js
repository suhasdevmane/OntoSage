import React from 'react';
import { useNavigate } from 'react-router-dom';

export default function UserBar() {
  const navigate = useNavigate();
  const currentUser = sessionStorage.getItem('currentUser');

  if (!currentUser) return null;

  const logout = async () => {
    try {
      await fetch('http://localhost:8080/api/logout', { method: 'POST', credentials: 'include' });
    } catch (e) {
      // ignore network errors for logout
    }
    try {
      // Optional: keep Dexie as an offline cache; if desired, uncomment to clear history for this user.
      // const rec = await db.chatHistory.where('username').equals(currentUser).first();
      // if (rec) await db.chatHistory.delete(rec.id);
    } catch {}
    sessionStorage.removeItem('currentUser');
    navigate('/login');
  };

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0,
      background: '#f8f9fa', borderBottom: '1px solid #e5e7eb',
      padding: '6px 12px', zIndex: 11000, display: 'flex', alignItems: 'center', justifyContent: 'space-between'
    }}>
      <div style={{ fontSize: 14 }}>Logged in as <strong>{currentUser}</strong></div>
      <button onClick={logout} style={{
        fontSize: 13, background: '#dc3545', color: 'white', border: 'none',
        borderRadius: 4, padding: '6px 10px', cursor: 'pointer'
      }}>Logout</button>
    </div>
  );
}
