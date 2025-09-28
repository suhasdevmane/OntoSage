import { useEffect, useRef } from "react";
import Graphics from "../Graphics.js";

export function useGraphicsMount() {
  const graphics = Graphics.getInstance();
  const mountRef = useRef(null);
  useEffect(() => {
    graphics.init(mountRef).then();
    try { if (!window.__ABACWS_GRAPHICS_INSTANCE__) window.__ABACWS_GRAPHICS_INSTANCE__ = graphics; } catch(_){}
    return () => { graphics.dispose(); };
  }, [graphics, mountRef]);
  return mountRef;
}
