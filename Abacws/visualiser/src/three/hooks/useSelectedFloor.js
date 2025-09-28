import { useCallback, useEffect, useState } from "react";
import { FloorSelectEvent } from "../events.js";

// Matches the TS API: returns [floor, setFloor]
export function useSelectedFloor() {
  const [floor, setFloor] = useState(0);

  // Listen for external floor changes from the 3D scene
  useEffect(() => {
    function onFloor(e) { setFloor(e.detail?.floor ?? 0); }
    window.addEventListener(FloorSelectEvent.TYPE, onFloor);
    return () => window.removeEventListener(FloorSelectEvent.TYPE, onFloor);
  }, []);

  // Setter that dispatches an event so Graphics updates the clipping plane
  const setSelectedFloor = useCallback((f) => {
    window.dispatchEvent(new FloorSelectEvent(f));
  }, []);

  return [floor, setSelectedFloor];
}
