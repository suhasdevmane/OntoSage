/**
 * FloorPlanViewer.js — Interactive floor plan component (T1 + T2)
 *
 * T1: Rendered PNG + invisible hotspot buttons over each space (centroid-based).
 *     Clicking a space emits selectSpace(space) → the chat container fires
 *     a user message: "Tell me about {space.label}".
 *
 * T2: Same PNG + SVG polygon/rect overlay per space, with hover tooltips
 *     showing label, type, and live sensor readings (fetched from API).
 *     Spaces are colour-coded by sensor status (green/amber/red/grey).
 *
 * Props:
 *   manifest    {Object}   FloorPlanManifest from /api/v1/floor-plans/{building}/{floor}/manifest
 *   onSelectSpace {Function(space)}  Called when a space is clicked/selected
 *   showSensors {Boolean}  If true, fetch live sensor readings (T2 mode). Default: true
 *   apiBase     {String}   Base URL for API calls. Default: ""
 *   className   {String}   Extra CSS class for the container
 *
 * Usage in ChatBot.js:
 *   When a message has type="floor_plan" with a manifest_url, render this component
 *   and wire onSelectSpace to send a user chat message.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";

const STATUS_COLOURS = {
  ok: "rgba(34,197,94,0.55)",
  warn: "rgba(251,191,36,0.55)",
  alert: "rgba(239,68,68,0.55)",
  unknown: "rgba(148,163,184,0.35)",
};

const TYPE_ICONS = {
  office: "🖥",
  lab: "🔬",
  meeting_room: "🤝",
  classroom: "📚",
  lecture: "🎓",
  toilet: "🚻",
  kitchen: "☕",
  server_room: "🖧",
  storage: "📦",
  staircase: "🪜",
  lift: "🛗",
  reception: "🏢",
  corridor: "🚶",
  utility: "⚙️",
  zone: "📡",
  unknown: "📍",
};

export default function FloorPlanViewer({
  manifest,
  onSelectSpace,
  showSensors = true,
  showSidePanel = true,   // T3: side panel visible by default
  apiBase = "",
  className = "",
}) {
  const [imgSize, setImgSize] = useState({ w: 0, h: 0 });
  const [hovered, setHovered] = useState(null);
  const [selected, setSelected] = useState(null);
  const [sensorReadings, setSensorReadings] = useState({});
  const [imgLoaded, setImgLoaded] = useState(false);
  const imgRef = useRef(null);
  const containerRef = useRef(null);

  // ── T3 side panel state ────────────────────────────────────────────────
  const [panelOpen, setPanelOpen] = useState(showSidePanel);
  const [searchQuery, setSearchQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState(null);   // null = all types
  const [searchResults, setSearchResults] = useState(null);  // null = use manifest
  const [searching, setSearching] = useState(false);

  const imageUrl = manifest?.rendered_image?.png_url || "";
  const spaces = manifest?.spaces || [];

  // Measure the rendered image so hotspots are positioned correctly
  const measureImg = useCallback(() => {
    if (imgRef.current) {
      setImgSize({
        w: imgRef.current.offsetWidth,
        h: imgRef.current.offsetHeight,
      });
    }
  }, []);

  useEffect(() => {
    measureImg();
    window.addEventListener("resize", measureImg);
    return () => window.removeEventListener("resize", measureImg);
  }, [measureImg, imgLoaded]);

  // Fetch latest sensor readings for all spaces that have sensor_uuids
  useEffect(() => {
    if (!showSensors || !spaces.length) return;
    const uuids = spaces.flatMap((s) => s.sensor_uuids || []).filter(Boolean);
    if (!uuids.length) return;

    const ctrl = new AbortController();
    fetch(
      `${apiBase}/api/v1/sensors/latest?uuids=${uuids.join(",")}`,
      { signal: ctrl.signal }
    )
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (data?.data) setSensorReadings(data.data);
      })
      .catch(() => {});

    return () => ctrl.abort();
  }, [showSensors, spaces, apiBase]);

  // ── T3: search across manifest (local) or API (cross-floor) ───────────
  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    const ctrl = new AbortController();
    setSearching(true);
    const building = manifest?.building_id || "abacws";
    fetch(
      `${apiBase}/api/v1/floor-plans/search?q=${encodeURIComponent(searchQuery)}&building=${building}`,
      { signal: ctrl.signal }
    )
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (data?.data) {
          setSearchResults(data.data.map((d) => d.space || d));
        } else {
          // Fallback: filter locally within the loaded manifest
          const q = searchQuery.toLowerCase();
          setSearchResults(
            spaces.filter(
              (s) =>
                s.label.toLowerCase().includes(q) ||
                s.zone_id.toLowerCase().includes(q) ||
                s.type.toLowerCase().includes(q)
            )
          );
        }
        setSearching(false);
      })
      .catch(() => {
        // Offline fallback
        const q = searchQuery.toLowerCase();
        setSearchResults(
          spaces.filter(
            (s) =>
              s.label.toLowerCase().includes(q) ||
              s.zone_id.toLowerCase().includes(q) ||
              s.type.toLowerCase().includes(q)
          )
        );
        setSearching(false);
      });

    return () => ctrl.abort();
  }, [searchQuery, spaces, manifest, apiBase]);

  // Derive the list shown in the side panel
  const panelSpaces = useCallback(() => {
    let list = searchResults !== null ? searchResults : spaces;
    if (typeFilter) list = list.filter((s) => s.type === typeFilter);
    return list;
  }, [searchResults, spaces, typeFilter]);

  // All distinct types for the filter chips
  const allTypes = [...new Set(spaces.map((s) => s.type))].sort();

  const handleSpaceClick = useCallback(
    (space) => {
      setSelected(space.id);
      if (onSelectSpace) onSelectSpace(space);
    },
    [onSelectSpace]
  );

  if (!manifest) return null;

  const hasSpatial = spaces.some((s) => s.centroid || s.bbox);

  // ── Status colour helper ───────────────────────────────────────────────
  function spaceStatus(space) {
    if (!space.sensor_uuids?.length) return "unknown";
    const readings = space.sensor_uuids.map((u) => sensorReadings[u]).filter(Boolean);
    if (!readings.length) return "unknown";
    const hasAlert = readings.some((r) => r.status === "alert");
    const hasWarn = readings.some((r) => r.status === "warn");
    if (hasAlert) return "alert";
    if (hasWarn) return "warn";
    return "ok";
  }

  function spaceTooltipText(space) {
    const icon = TYPE_ICONS[space.type] || "📍";
    const type = space.type.replace(/_/g, " ");
    const uuids = space.sensor_uuids || [];
    let sensorLine = "";
    if (uuids.length) {
      const readingStr = uuids
        .map((u) => {
          const r = sensorReadings[u];
          return r ? `${r.label || u}: ${r.value}${r.unit || ""}` : null;
        })
        .filter(Boolean)
        .join(", ");
      sensorLine = readingStr ? `\nSensors: ${readingStr}` : "";
    }
    return `${icon} ${space.label}\nType: ${type}${sensorLine}`;
  }

  return (
    <div
      ref={containerRef}
      className={`floor-plan-viewer ${className}`}
      style={{ position: "relative", display: "inline-block", width: "100%", maxWidth: 900 }}
    >
      {/* ── Floor label ─────────────────────────────────────────────── */}
      <div style={styles.header}>
        <span style={styles.headerTitle}>
          🏢 {manifest.building_name} — {manifest.floor_label}
        </span>
        <a
          href={manifest.pdf_url}
          target="_blank"
          rel="noreferrer"
          style={styles.pdfLink}
        >
          📄 Open PDF
        </a>
      </div>

      {/* ── Rendered floor plan image ────────────────────────────────── */}
      <div style={{ position: "relative", width: "100%" }}>
        <img
          ref={imgRef}
          src={imageUrl}
          alt={`${manifest.building_name} ${manifest.floor_label}`}
          onLoad={() => { setImgLoaded(true); measureImg(); }}
          style={{ width: "100%", display: "block", borderRadius: 6 }}
        />

        {/* ── T2: SVG overlay when we have spatial coordinates ─────── */}
        {imgLoaded && hasSpatial && imgSize.w > 0 && (
          <svg
            style={{
              position: "absolute", top: 0, left: 0,
              width: imgSize.w, height: imgSize.h,
              pointerEvents: "none",
            }}
            viewBox={`0 0 ${imgSize.w} ${imgSize.h}`}
          >
            {spaces.map((space) => {
              if (!space.bbox && !space.centroid) return null;
              const status = spaceStatus(space);
              const fill = STATUS_COLOURS[status];
              const isHovered = hovered === space.id;
              const isSelected = selected === space.id;
              const stroke = isSelected ? "#2563eb" : isHovered ? "#f59e0b" : "rgba(255,255,255,0.6)";
              const strokeW = isSelected || isHovered ? 2 : 1;

              if (space.bbox) {
                const { x, y, w, h } = space.bbox;
                return (
                  <rect
                    key={space.id}
                    x={x * imgSize.w}
                    y={y * imgSize.h}
                    width={w * imgSize.w}
                    height={h * imgSize.h}
                    fill={fill}
                    stroke={stroke}
                    strokeWidth={strokeW}
                    rx={3}
                    style={{ pointerEvents: "auto", cursor: "pointer", transition: "fill 0.2s" }}
                    onMouseEnter={() => setHovered(space.id)}
                    onMouseLeave={() => setHovered(null)}
                    onClick={() => handleSpaceClick(space)}
                  >
                    <title>{spaceTooltipText(space)}</title>
                  </rect>
                );
              }

              // Centroid-only: draw a small circle
              const cx = space.centroid.x * imgSize.w;
              const cy = space.centroid.y * imgSize.h;
              return (
                <circle
                  key={space.id}
                  cx={cx} cy={cy} r={isHovered || isSelected ? 10 : 7}
                  fill={fill}
                  stroke={stroke}
                  strokeWidth={strokeW}
                  style={{ pointerEvents: "auto", cursor: "pointer", transition: "all 0.2s" }}
                  onMouseEnter={() => setHovered(space.id)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => handleSpaceClick(space)}
                >
                  <title>{spaceTooltipText(space)}</title>
                </circle>
              );
            })}
          </svg>
        )}

        {/* ── T1 fallback: centroid hotspot buttons (no bbox) ──────── */}
        {imgLoaded && !hasSpatial && imgSize.w > 0 &&
          spaces.map((space) => {
            if (!space.centroid) return null;
            const left = space.centroid.x * imgSize.w;
            const top = space.centroid.y * imgSize.h;
            const status = spaceStatus(space);
            return (
              <button
                key={space.id}
                title={spaceTooltipText(space)}
                onClick={() => handleSpaceClick(space)}
                style={{
                  ...styles.hotspot,
                  left, top,
                  background: STATUS_COLOURS[status],
                  border: selected === space.id ? "2px solid #2563eb" : "1px solid rgba(255,255,255,0.7)",
                }}
                onMouseEnter={() => setHovered(space.id)}
                onMouseLeave={() => setHovered(null)}
              >
                {TYPE_ICONS[space.type] || "•"}
              </button>
            );
          })}

        {/* ── Hover tooltip ─────────────────────────────────────────── */}
        {hovered && (() => {
          const space = spaces.find((s) => s.id === hovered);
          if (!space) return null;
          const cx = (space.centroid?.x || (space.bbox?.x || 0) + (space.bbox?.w || 0) / 2) * imgSize.w;
          const cy = (space.centroid?.y || (space.bbox?.y || 0)) * imgSize.h;
          return (
            <div style={{ ...styles.tooltip, left: Math.min(cx + 12, imgSize.w - 180), top: Math.max(cy - 40, 4) }}>
              <strong>{space.label}</strong>
              <br />
              <span style={{ color: "#94a3b8", fontSize: 11 }}>
                {TYPE_ICONS[space.type]} {space.type.replace(/_/g, " ")}
                {space.zone_id ? ` · Zone ${space.zone_id}` : ""}
              </span>
              {(space.sensor_uuids || []).map((u) => {
                const r = sensorReadings[u];
                return r ? (
                  <div key={u} style={{ fontSize: 11, color: "#e2e8f0" }}>
                    {r.label || u}: <strong>{r.value}{r.unit || ""}</strong>
                  </div>
                ) : null;
              })}
            </div>
          );
        })()}
      </div>

      {/* ── T3 Side Panel toggle ────────────────────────────────────── */}
      <button
        onClick={() => setPanelOpen((o) => !o)}
        style={styles.panelToggle}
        title={panelOpen ? "Hide space list" : "Show space list"}
      >
        {panelOpen ? "◀ Hide" : "▶ Spaces"}
      </button>

      {/* ── Status legend ────────────────────────────────────────────── */}
      {showSensors && Object.keys(sensorReadings).length > 0 && (
        <div style={styles.statusLegend}>
          {Object.entries(STATUS_COLOURS).map(([s, c]) => (
            <span key={s} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11 }}>
              <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: c }} />
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </span>
          ))}
        </div>
      )}

    {/* ── T3 Side Panel ───────────────────────────────────────────────── */}
    {panelOpen && (
      <div style={styles.sidePanel}>
        {/* Search box */}
        <input
          id="floor-plan-search"
          type="search"
          placeholder="Search spaces…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          style={styles.searchInput}
          aria-label="Search spaces"
        />

        {/* Type filter chips */}
        <div style={styles.filterRow}>
          <button
            onClick={() => setTypeFilter(null)}
            style={{
              ...styles.filterChip,
              background: typeFilter === null ? "#3b82f6" : "#1e293b",
              border: typeFilter === null ? "1px solid #60a5fa" : "1px solid #334155",
            }}
          >
            All
          </button>
          {allTypes.map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t === typeFilter ? null : t)}
              style={{
                ...styles.filterChip,
                background: typeFilter === t ? "#3b82f6" : "#1e293b",
                border: typeFilter === t ? "1px solid #60a5fa" : "1px solid #334155",
              }}
            >
              {TYPE_ICONS[t] || ""} {t.replace(/_/g, " ")}
            </button>
          ))}
        </div>

        {/* Space list */}
        <div style={styles.spaceList}>
          {searching && (
            <div style={styles.searchingNote}>Searching…</div>
          )}
          {!searching && panelSpaces().length === 0 && (
            <div style={styles.searchingNote}>No spaces match your search.</div>
          )}
          {!searching && panelSpaces().map((space) => (
            <button
              key={space.id}
              onClick={() => handleSpaceClick(space)}
              style={{
                ...styles.spaceRow,
                background: selected === space.id ? "#1e3a8a" : "transparent",
                borderLeft: selected === space.id
                  ? "3px solid #3b82f6"
                  : "3px solid transparent",
              }}
            >
              <span style={styles.spaceRowIcon}>
                {TYPE_ICONS[space.type] || "📍"}
              </span>
              <span style={styles.spaceRowLabel}>
                {space.label}
                {space.zone_id && space.zone_id !== space.label && (
                  <span style={styles.spaceRowZone}> · {space.zone_id}</span>
                )}
              </span>
              <span style={styles.spaceRowType}>
                {space.type.replace(/_/g, " ")}
              </span>
            </button>
          ))}
        </div>

        <div style={styles.panelFooter}>
          {panelSpaces().length} space{panelSpaces().length !== 1 ? "s" : ""}
          {typeFilter ? ` · ${typeFilter.replace(/_/g, " ")}` : ""}
        </div>
      </div>
    )}
  </div>
  );
}

// ── Inline styles ────────────────────────────────────────────────────────────

const styles = {
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "6px 8px",
    background: "#0f172a",
    borderRadius: "6px 6px 0 0",
    marginBottom: 2,
  },
  headerTitle: {
    color: "#e2e8f0",
    fontWeight: 600,
    fontSize: 14,
  },
  pdfLink: {
    color: "#60a5fa",
    fontSize: 12,
    textDecoration: "none",
  },
  hotspot: {
    position: "absolute",
    transform: "translate(-50%, -50%)",
    width: 22,
    height: 22,
    borderRadius: "50%",
    cursor: "pointer",
    fontSize: 12,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 0,
    boxShadow: "0 1px 4px rgba(0,0,0,0.4)",
    transition: "all 0.15s",
  },
  tooltip: {
    position: "absolute",
    background: "#1e293b",
    color: "#f1f5f9",
    padding: "6px 10px",
    borderRadius: 6,
    fontSize: 12,
    boxShadow: "0 4px 12px rgba(0,0,0,0.5)",
    pointerEvents: "none",
    zIndex: 50,
    minWidth: 140,
    maxWidth: 220,
    lineHeight: 1.5,
  },
  legend: {
    marginTop: 8,
    padding: "6px 8px",
    background: "#0f172a",
    borderRadius: 6,
  },
  legendTitle: {
    color: "#94a3b8",
    fontSize: 11,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  },
  legendGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: 4,
    marginTop: 6,
  },
  legendItem: {
    color: "#e2e8f0",
    fontSize: 11,
    padding: "3px 8px",
    borderRadius: 4,
    cursor: "pointer",
    transition: "background 0.15s",
  },
  statusLegend: {
    display: "flex",
    gap: 12,
    marginTop: 6,
    padding: "4px 8px",
    background: "#0f172a",
    borderRadius: 6,
  },
  // ── T3 side panel ─────────────────────────────────────────────────────────
  panelToggle: {
    marginTop: 6,
    padding: "4px 10px",
    background: "#1e293b",
    color: "#94a3b8",
    border: "1px solid #334155",
    borderRadius: 4,
    cursor: "pointer",
    fontSize: 11,
    transition: "background 0.15s",
  },
  sidePanel: {
    marginTop: 8,
    background: "#0f172a",
    border: "1px solid #1e293b",
    borderRadius: 6,
    overflow: "hidden",
    display: "flex",
    flexDirection: "column",
    maxHeight: 480,
  },
  searchInput: {
    width: "100%",
    boxSizing: "border-box",
    padding: "7px 10px",
    background: "#1e293b",
    border: "none",
    borderBottom: "1px solid #334155",
    color: "#e2e8f0",
    fontSize: 12,
    outline: "none",
  },
  filterRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 4,
    padding: "6px 8px",
    borderBottom: "1px solid #1e293b",
  },
  filterChip: {
    padding: "2px 8px",
    borderRadius: 12,
    cursor: "pointer",
    fontSize: 10,
    color: "#e2e8f0",
    transition: "background 0.15s",
    whiteSpace: "nowrap",
  },
  spaceList: {
    overflowY: "auto",
    flex: 1,
    padding: "4px 0",
  },
  spaceRow: {
    display: "flex",
    alignItems: "center",
    width: "100%",
    padding: "5px 10px",
    border: "none",
    cursor: "pointer",
    color: "#e2e8f0",
    textAlign: "left",
    gap: 6,
    transition: "background 0.1s",
  },
  spaceRowIcon: {
    fontSize: 14,
    flexShrink: 0,
    width: 20,
    textAlign: "center",
  },
  spaceRowLabel: {
    flex: 1,
    fontSize: 12,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  spaceRowZone: {
    color: "#64748b",
    fontSize: 10,
  },
  spaceRowType: {
    fontSize: 10,
    color: "#64748b",
    flexShrink: 0,
    textTransform: "capitalize",
  },
  panelFooter: {
    padding: "5px 10px",
    fontSize: 10,
    color: "#475569",
    borderTop: "1px solid #1e293b",
    background: "#0f172a",
  },
  searchingNote: {
    padding: "8px 10px",
    color: "#64748b",
    fontSize: 12,
    fontStyle: "italic",
  },
};
