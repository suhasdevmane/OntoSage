import { useEffect, useMemo, useState } from 'react';
import Graphics from '../../three/Graphics.js';
import './DeviceActions.scss';

export function DeviceActions({ deviceName, pinned }) {
  const [busy, setBusy] = useState(false);
  const graphics = useMemo(() => Graphics.getInstance(), []);

  useEffect(() => { setBusy(false); }, [deviceName]);

  if (!deviceName) return null;
  const onToggle = async () => {
    try { setBusy(true); await graphics.togglePinByName(deviceName); } finally { setBusy(false); }
  };
  const onMoveY = async () => { await graphics.startMoveModeByName(deviceName, 'Y'); };
  const onMoveXZ = async () => { await graphics.startMoveModeByName(deviceName, 'XZ'); };

  return (
    <div className="device-actions">
      <button disabled={busy} onClick={onToggle}>{pinned ? '🔓 Unlock' : '🔒 Lock'}</button>
      <button disabled={busy} onClick={onMoveY}>↕ Move up/down</button>
      <button disabled={busy} onClick={onMoveXZ}>↔ Move left/right</button>
    </div>
  );
}
