import { useEffect, useState } from "react";
import { LoadEvent } from "../events.js";

export function useGraphicsLoaded() {
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    function onLoad(e) { setLoaded(e.detail?.success ?? true); }
    window.addEventListener(LoadEvent.TYPE, onLoad);
    return () => window.removeEventListener(LoadEvent.TYPE, onLoad);
  }, []);
  return loaded;
}
