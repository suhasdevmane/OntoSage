import './App.scss';
import { ModelView, DataView } from './views/index.js';
import { useEffect, useState } from 'react';
import { HamburgerToggle, HealthStatus, DeviceDrawer, AdjustDevicesPanel, SettingsPanel } from './components/index.js';
import { DeviceSelectEvent, useSelectedDevice } from './three/index.js';
import { useDeviceInfo, TimeProvider } from './hooks/index.js';

export default function App() {
  const [hideDataView, setHideDataView] = useState(window.innerWidth < 500);
  const selectedDeviceName = useSelectedDevice();
  const selectedDeviceInfo = useDeviceInfo(selectedDeviceName);

  useEffect(() => {
    function deviceSelectedListener() {
      setHideDataView(false);
    }
    window.addEventListener(DeviceSelectEvent.TYPE, deviceSelectedListener);
    return () => { window.removeEventListener(DeviceSelectEvent.TYPE, deviceSelectedListener); };
  }, []);

  return (
    <TimeProvider>
      <div className="app">
        <AdjustDevicesPanel />
        <HealthStatus />
        <ModelView />
        <HamburgerToggle onClick={() => { setHideDataView(!hideDataView); }} close={!hideDataView} />
        <DataView hidden={hideDataView} />
        <SettingsPanel />
        {selectedDeviceName && <DeviceDrawer onClose={() => { window.dispatchEvent(new CustomEvent(DeviceSelectEvent.TYPE,{ detail:{ deviceName: null } })); }} />}
      </div>
    </TimeProvider>
  );
}
