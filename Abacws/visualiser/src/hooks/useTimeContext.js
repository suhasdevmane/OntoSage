import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';

/*
 Time context centralises selection of temporal window & mode across components.
 Modes:
  - 'range': fixed from/to (ms epoch)
  - 'relative': last N ms (rolling window) updated every tick
  - 'live': like relative + more frequent refresh hint (future SSE integration)
*/

const TimeContext = createContext(null);

export function TimeProvider({ children }) {
  const [mode, setMode] = useState('relative'); // relative | range | live
  const [relativeMs, setRelativeMs] = useState(60 * 60 * 1000); // last 1h
  const [range, setRange] = useState({ from: Date.now() - 60*60*1000, to: Date.now() });
  const [tick, setTick] = useState(0); // increments to trigger recalculation
  const timerRef = useRef();

  // Update timer cadence based on mode
  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    const interval = mode === 'live' ? 5000 : (mode === 'relative' ? 15000 : 60000);
    timerRef.current = setInterval(() => setTick(t => t + 1), interval);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [mode]);

  const value = useMemo(() => {
    const now = Date.now();
    if (mode === 'relative' || mode === 'live') {
      return {
        mode,
        from: now - relativeMs,
        to: now,
        relativeMs,
        setRelativeMs,
        setMode,
        setRange,
        live: mode === 'live'
      };
    }
    return {
      mode,
      from: range.from,
      to: range.to,
      relativeMs,
      setRelativeMs,
      setMode,
      setRange,
      live: false
    };
  }, [mode, relativeMs, range, tick]);

  return <TimeContext.Provider value={value}>{children}</TimeContext.Provider>;
}

export function useTimeContext() {
  return useContext(TimeContext);
}

// Utility preset list
export const TIME_PRESETS = [
  { label: '15m', ms: 15*60*1000 },
  { label: '1h', ms: 60*60*1000 },
  { label: '6h', ms: 6*60*60*1000 },
  { label: '12h', ms: 12*60*60*1000 },
  { label: '24h', ms: 24*60*60*1000 },
];
