import { Spinner } from "../../components/index.js";
import { useGraphicsLoaded, useGraphicsMount } from "../../three/index.js";

export function ModelView() {
  const loaded = useGraphicsLoaded();
  const mountRef = useGraphicsMount();
  const loadingSpinner = loaded ? null : <Spinner />;
  return (
    <div ref={mountRef} className="model-container">
      {loadingSpinner}
    </div>
  );
}
