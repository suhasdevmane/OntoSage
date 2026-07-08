import React, { useState, useEffect, useCallback } from 'react';

const ROLES = ['admin','facility_manager','analyst','operator','occupant','readonly'];

export default function UsersTab({ api, headers }) {
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState({ username:'', password:'', role:'readonly', email:'' });
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    const r = await fetch(`${api}/api/v1/admin/users`, { headers });
    const d = await r.json();
    setUsers(d.data?.users || []);
  }, [api, headers]);

  useEffect(() => { load(); }, [load]);

  const create = async () => {
    const r = await fetch(`${api}/api/v1/admin/users`, {
      method:'POST', headers, body: JSON.stringify(form)
    });
    const d = await r.json();
    setMsg(d.success ? `Created ${form.username}` : d.error);
    if (d.success) { setForm({username:'',password:'',role:'readonly',email:''}); load(); }
  };

  const changeRole = async (username, role) => {
    await fetch(`${api}/api/v1/admin/users/${username}/role`, {
      method:'PUT', headers, body: JSON.stringify({ role })
    });
    load();
  };

  const del = async (username) => {
    if (!window.confirm(`Delete user '${username}'?`)) return;
    await fetch(`${api}/api/v1/admin/users/${username}`, { method:'DELETE', headers });
    load();
  };

  return (
    <div>
      {msg && <div className="alert alert-info py-1 mb-3">{msg}</div>}
      <div className="row g-4">
        <div className="col-12 col-lg-7">
          <h5>Users</h5>
          <table className="table table-sm table-bordered">
            <thead className="table-light"><tr><th>Username</th><th>Role</th><th>Email</th><th></th></tr></thead>
            <tbody>
              {users.map(u => (
                <tr key={u.username}>
                  <td><code>{u.username}</code></td>
                  <td>
                    <select className="form-select form-select-sm" value={u.role}
                      onChange={e => changeRole(u.username, e.target.value)} style={{minWidth:130}}>
                      {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                  <td style={{fontSize:12}}>{u.email||'-'}</td>
                  <td>
                    <button className="btn btn-xs btn-outline-danger py-0 px-1" style={{fontSize:11}}
                      onClick={() => del(u.username)}>Del</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="col-12 col-lg-5">
          <div className="card">
            <div className="card-header"><strong>Create User</strong></div>
            <div className="card-body">
              {[['username','Username','text'],['password','Password','password'],['email','Email (optional)','email']].map(([k,label,type]) => (
                <div className="mb-2" key={k}>
                  <label className="form-label small mb-0">{label}</label>
                  <input className="form-control form-control-sm" type={type} value={form[k]}
                    onChange={e => setForm(prev=>({...prev,[k]:e.target.value}))} />
                </div>
              ))}
              <div className="mb-2">
                <label className="form-label small mb-0">Role</label>
                <select className="form-select form-select-sm" value={form.role}
                  onChange={e => setForm(prev=>({...prev,role:e.target.value}))}>
                  {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
              <button className="btn btn-sm btn-primary" onClick={create}>Create</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
