import { useEffect, useState } from "react";
import { DeviceSelectEvent } from "../events.js";

export function useSelectedDevice() {
  const [selected, setSelected] = useState(null);
  useEffect(() => {
    function onSelect(e) { setSelected(e.detail?.deviceName ?? null); }
    window.addEventListener(DeviceSelectEvent.TYPE, onSelect);
    return () => window.removeEventListener(DeviceSelectEvent.TYPE, onSelect);
  }, []);
  return selected;
}
