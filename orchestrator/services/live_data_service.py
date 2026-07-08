"""Live-data service — fetch CURRENT information the LLM cannot know from its
training cutoff, for the general_knowledge node.

Two capabilities, both free:
  * Weather  — Open-Meteo (https://open-meteo.com): keyless JSON geocoding +
               forecast API. Non-commercial use needs no API key.
  * Web search — provider-pluggable. Default DuckDuckGo (keyless, via the `ddgs`
               package); optional Tavily when TAVILY_API_KEY is set.

Everything degrades gracefully: a network failure, missing dependency, or empty
result returns None/[] so the caller can fall back to a plain LLM answer rather
than erroring.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

import httpx

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes → human-readable conditions.
# https://open-meteo.com/en/docs (Weather variable documentation)
_WMO_CODES: Dict[int, str] = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snowfall",
    73: "moderate snowfall",
    75: "heavy snowfall",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


class LiveDataService:
    """Fetch current weather and web-search results for live-data questions."""

    def __init__(self) -> None:
        self._timeout = float(getattr(settings, "WEB_SEARCH_TIMEOUT_S", 8.0))

    # ── Weather (Open-Meteo) ─────────────────────────────────────────────────
    async def get_weather(self, location: str) -> Optional[Dict]:
        """Return current weather for a place name, or None if it can't be found.

        Two hops: geocode the name → fetch current conditions for the coords.
        """
        if not location or not location.strip():
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                geo = await client.get(
                    _GEOCODE_URL,
                    params={
                        "name": location.strip(),
                        "count": 1,
                        "language": "en",
                        "format": "json",
                    },
                )
                geo.raise_for_status()
                results = (geo.json() or {}).get("results") or []
                if not results:
                    logger.info(f"[live_data] geocode found no match for '{location}'")
                    return None
                place = results[0]
                lat, lon = place["latitude"], place["longitude"]

                wx = await client.get(
                    _FORECAST_URL,
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": (
                            "temperature_2m,relative_humidity_2m,apparent_temperature,"
                            "weather_code,wind_speed_10m,precipitation"
                        ),
                        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                        "timezone": "auto",
                        "forecast_days": 1,
                    },
                )
                wx.raise_for_status()
                data = wx.json() or {}
        except Exception as e:  # noqa: BLE001 — any failure → graceful None
            logger.warning(f"[live_data] weather fetch failed for '{location}': {e}")
            return None

        cur = data.get("current") or {}
        units = data.get("current_units") or {}
        daily = data.get("daily") or {}
        code = cur.get("weather_code")
        place_label = ", ".join(
            p for p in (place.get("name"), place.get("admin1"), place.get("country")) if p
        )
        return {
            "location": place_label or location,
            "condition": _WMO_CODES.get(int(code), "unknown") if code is not None else "unknown",
            "temperature": cur.get("temperature_2m"),
            "temperature_unit": units.get("temperature_2m", "°C"),
            "feels_like": cur.get("apparent_temperature"),
            "humidity": cur.get("relative_humidity_2m"),
            "humidity_unit": units.get("relative_humidity_2m", "%"),
            "wind_speed": cur.get("wind_speed_10m"),
            "wind_unit": units.get("wind_speed_10m", "km/h"),
            "precipitation": cur.get("precipitation"),
            "high": (daily.get("temperature_2m_max") or [None])[0],
            "low": (daily.get("temperature_2m_min") or [None])[0],
            "precip_chance": (daily.get("precipitation_probability_max") or [None])[0],
            "observed_at": cur.get("time"),
            "source": "Open-Meteo",
        }

    @staticmethod
    def format_weather(w: Dict) -> str:
        """Compact, LLM-friendly rendering of a weather dict."""
        parts = [
            f"Location: {w['location']}",
            f"Condition: {w['condition']}",
            f"Temperature: {w['temperature']}{w['temperature_unit']} "
            f"(feels like {w['feels_like']}{w['temperature_unit']})",
            f"Humidity: {w['humidity']}{w['humidity_unit']}",
            f"Wind: {w['wind_speed']} {w['wind_unit']}",
        ]
        if w.get("high") is not None and w.get("low") is not None:
            parts.append(f"Today's range: {w['low']}–{w['high']}{w['temperature_unit']}")
        if w.get("precip_chance") is not None:
            parts.append(f"Precipitation chance today: {w['precip_chance']}%")
        if w.get("observed_at"):
            parts.append(f"Observed at: {w['observed_at']} (local time)")
        return "\n".join(parts)

    # ── Web search (pluggable) ───────────────────────────────────────────────
    async def web_search(self, query: str, max_results: Optional[int] = None) -> List[Dict]:
        """Return a list of {title, snippet, url}. Empty list on any failure.

        The backend is selected explicitly by settings.WEB_SEARCH_PROVIDER:
          * "duckduckgo" (default) — free, keyless.
          * "tavily"               — uses TAVILY_API_KEY; falls back to DuckDuckGo
                                      if the key is missing or the call yields nothing.
          * "none"                 — web search disabled.
        """
        if not query or not query.strip():
            return []
        n = max_results or int(getattr(settings, "WEB_SEARCH_MAX_RESULTS", 5))
        provider = getattr(settings, "WEB_SEARCH_PROVIDER", "duckduckgo")

        if provider == "none":
            return []

        if provider == "tavily":
            tavily_key = getattr(settings, "TAVILY_API_KEY", None)
            if tavily_key:
                results = await self._search_tavily(query, n, tavily_key)
                if results:
                    return results
                logger.warning(
                    "[live_data] Tavily returned no results — falling back to DuckDuckGo"
                )
            else:
                logger.warning(
                    "[live_data] WEB_SEARCH_PROVIDER=tavily but TAVILY_API_KEY is unset "
                    "— falling back to DuckDuckGo"
                )
            return await self._search_duckduckgo(query, n)

        # Default: DuckDuckGo (keyless).
        return await self._search_duckduckgo(query, n)

    async def _search_tavily(self, query: str, n: int, api_key: str) -> List[Dict]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": api_key,
                        "query": query,
                        "max_results": n,
                        "search_depth": "basic",
                    },
                )
                resp.raise_for_status()
                data = resp.json() or {}
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[live_data] Tavily search failed: {e}")
            return []
        return [
            {
                "title": r.get("title", ""),
                "snippet": r.get("content", ""),
                "url": r.get("url", ""),
            }
            for r in (data.get("results") or [])
        ][:n]

    async def _search_duckduckgo(self, query: str, n: int) -> List[Dict]:
        """Keyless DuckDuckGo search via the `ddgs` package (sync → executor)."""
        try:
            try:
                from ddgs import DDGS  # maintained package name
            except ImportError:  # pragma: no cover — older package name
                from duckduckgo_search import DDGS  # type: ignore
        except ImportError:
            logger.warning(
                "[live_data] DuckDuckGo search unavailable — install `ddgs` "
                "(pip install ddgs) or set WEB_SEARCH_PROVIDER=tavily with a key."
            )
            return []

        def _run() -> List[Dict]:
            out: List[Dict] = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=n):
                    out.append(
                        {
                            "title": r.get("title", ""),
                            "snippet": r.get("body", ""),
                            "url": r.get("href", ""),
                        }
                    )
            return out

        try:
            return await asyncio.get_event_loop().run_in_executor(None, _run)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[live_data] DuckDuckGo search failed: {e}")
            return []

    @staticmethod
    def format_search_results(results: List[Dict]) -> str:
        """Numbered, LLM-friendly rendering of search results with sources."""
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "").strip()
            snippet = r.get("snippet", "").strip()
            url = r.get("url", "").strip()
            lines.append(f"[{i}] {title}\n{snippet}\nSource: {url}")
        return "\n\n".join(lines)


# Module-level singleton (cheap; httpx clients are created per-call).
_live_data_service: Optional[LiveDataService] = None


def get_live_data_service() -> LiveDataService:
    """Return the process-wide LiveDataService singleton."""
    global _live_data_service
    if _live_data_service is None:
        _live_data_service = LiveDataService()
    return _live_data_service
