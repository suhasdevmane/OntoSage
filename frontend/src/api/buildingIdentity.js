// Who this deployment serves — read from the API, never written into the UI.
//
// WHY THIS EXISTS
// ---------------
// The building's name was hardcoded in four places: the nav brand, the home page heading,
// a service tile, and a `manifest?.building_id || "abacws"` fallback in the floor-plan
// viewer. So every deployment greeted its users by the name of the first building this
// system ever served, and the floor-plan search silently queried that building whenever a
// manifest had not loaded yet (V10 W2-2).
//
// The fallback is the important half. `|| "abacws"` is not a default — it is a specific
// building, and a search that quietly runs against the wrong one returns plausible results
// for somewhere else. NEUTRAL_NAME below is a category, not a place, so an unreachable API
// produces a heading that is merely uninformative rather than wrong.

const BASE = process.env.REACT_APP_API_BASE || 'http://localhost:8000';

// Deliberately not a building. If the API cannot be reached we say nothing specific.
export const NEUTRAL_NAME = 'Building';

let cached = null;
let inflight = null;

export async function fetchBuildingIdentity() {
  if (cached) return cached;
  if (inflight) return inflight;

  inflight = fetch(`${BASE}/api/v1/building/identity`)
    .then((r) => (r.ok ? r.json() : null))
    .then((body) => {
      const d = (body && body.data) || {};
      cached = {
        buildingId: d.building_id || '',
        buildingName: d.building_name || NEUTRAL_NAME,
        namespace: d.ontology_namespace || '',
        prefix: d.ontology_prefix || '',
      };
      return cached;
    })
    .catch(() => ({
      buildingId: '',
      buildingName: NEUTRAL_NAME,
      namespace: '',
      prefix: '',
    }))
    .finally(() => {
      inflight = null;
    });

  return inflight;
}

// For a swap without a page reload, and for tests.
export function clearBuildingIdentityCache() {
  cached = null;
  inflight = null;
}
