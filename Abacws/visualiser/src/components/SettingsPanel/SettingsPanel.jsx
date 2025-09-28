import React, { useEffect, useState } from 'react';
import './SettingsPanel.scss';

/* Simple floating settings drawer for coordinate alignment & debug */
export default function SettingsPanel() {
  const [open, setOpen] = useState(false);
  const [autoAlign, setAutoAlign] = useState(!!(window.__ABACWS_AUTO_ALIGN__));
  const [showBBoxes, setShowBBoxes] = useState(false);
  const [scaleSuggestion, setScaleSuggestion] = useState(null);

  useEffect(() => {
    const handler = (e) => {
      if (e.detail && typeof e.detail.scale === 'number') {
        setScaleSuggestion(e.detail.scale);
      }
    };
    window.addEventListener('abacws:scale-suggestion', handler);
    return () => window.removeEventListener('abacws:scale-suggestion', handler);
  }, []);

  const applyAutoAlign = () => {
    window.__ABACWS_AUTO_ALIGN__ = autoAlign;
    localStorage.setItem('__abacws_auto_align', autoAlign ? '1':'0');
    // eslint-disable-next-line no-restricted-globals
    window.location.reload();
  };

  const toggleBBoxes = () => {
    setShowBBoxes(v => {
      const nv = !v;
      window.dispatchEvent(new CustomEvent('abacws:toggle-bboxes', { detail: { enabled: nv } }));
      return nv;
    });
  };

  return (
    <div className={`settings-panel ${open ? 'open':''}`}>
      <button className="settings-toggle" onClick={() => setOpen(o=>!o)} title="Settings">⚙</button>
      <div className="settings-body">
        <h3>Settings</h3>
        <section>
          <h4>Coordinate Alignment</h4>
          <label className="row">
            <input type="checkbox" checked={autoAlign} onChange={e=>setAutoAlign(e.target.checked)} />
            <span>Auto Align Devices to Model</span>
          </label>
          <button onClick={applyAutoAlign}>Apply & Reload</button>
          {scaleSuggestion && (
            <div className="hint">Suggested uniform scale: <code>{scaleSuggestion.toFixed(4)}</code> (device extent vs model extent)</div>
          )}
        </section>
        <section>
          <h4>Debug</h4>
          <label className="row">
            <input type="checkbox" checked={showBBoxes} onChange={toggleBBoxes} />
            <span>Show Bounding Boxes</span>
          </label>
        </section>
      </div>
    </div>
  );
}
