"""Fresh-information routing backed by Tavily Search."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from config import Settings
from safety import ensure_captain_address, speech_friendly_text


LOGGER = logging.getLogger(__name__)
_CLIENT_NOT_PROVIDED = object()

_FRESH_TERMS = (
    "latest", "today", "tonight", "current", "currently", "recent",
    "right now", "this week", "this month", "tomorrow", "yesterday",
    "abhi", "aaj", "kal", "taaza", "taza", "आज", "अभी", "कल",
    "ताज़ा", "ताजा", "news", "headline", "breaking", "khabar",
    "samachar", "खबर", "समाचार", "politics", "political", "election",
    "president", "prime minister", "chief minister", "government",
    "minister", "chunav", "चुनाव", "राष्ट्रपति", "प्रधानमंत्री",
    "मुख्यमंत्री", "weather", "forecast", "temperature", "rainfall",
    "mausam", "baarish", "barish", "मौसम", "बारिश", "price", "cost",
    "exchange rate", "stock", "share market", "crypto", "bitcoin",
    "gold rate", "silver rate", "petrol", "diesel", "daam", "bhaav",
    "कीमत", "दाम", "भाव", "score", "fixture", "schedule", "standings",
    "points table", "match result", "ipl", "cricket match",
    "football match", "स्कोर", "मैच", "कार्यक्रम", "version",
    "release date", "software update",
)

_MAPS_TERMS = (
    "near me", "nearby", "paas", "hotel", "hotels", "restaurant", "restaurants",
    "cafe", "cafes", "hospital", "hospitals", "petrol pump", "ev charging",
    "gas station", "route", "direction", "directions", "rashta", "rasta",
    "distance", "kahan hai", "kidhar hai", "location", "map", "maps",
    "dhaba", "cinema", "theatre", "theater", "mall", "railway station",
    "bus stand", "airport", "navigate", "traffic",
)


def is_maps_or_location_query(query: str) -> bool:
    """Return whether a query is asking for maps, places, directions, or navigation."""
    normalized = " ".join(query.casefold().split())
    if not normalized:
        return False
    return any(_contains_term(normalized, term) for term in _MAPS_TERMS)


@dataclass(frozen=True, slots=True)
class SourceCitation:
    """One verified HTTP(S) source returned by Tavily Search."""

    title: str
    url: str


@dataclass(frozen=True, slots=True)
class RealtimeResponse:
    """A grounded answer plus citations suitable for display and speech."""

    display_text: str
    speech_text: str
    intent: str
    sources: tuple[SourceCitation, ...] = ()
    error: str | None = None
    confidence: float = 0.0
    fetched_at: str = ""
    topic: str = "general"


class TavilyRequestError(RuntimeError):
    """A sanitized Tavily HTTP failure carrying only status and safe detail."""

    def __init__(self, status_code: int | None, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class TavilyHTTPClient:
    """Minimal dependency-free client for Tavily's Search endpoint."""

    endpoint = "https://api.tavily.com/search"

    def __init__(self, api_key: str, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def search(
        self,
        query: str,
        *,
        search_depth: str,
        max_results: int,
        topic: str,
    ) -> Mapping[str, Any]:
        payload = json.dumps(
            {
                "query": query,
                "search_depth": search_depth,
                "max_results": max_results,
                "topic": topic,
                "include_answer": "basic",
                "include_raw_content": False,
                "include_images": False,
            }
        ).encode("utf-8")
        request = Request(
            self.endpoint,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = "Tavily HTTP request failed"
            try:
                error_data = json.loads(exc.read().decode("utf-8"))
                raw_detail = error_data.get("detail", {})
                if isinstance(raw_detail, Mapping):
                    detail = str(raw_detail.get("error") or detail)[:240]
            except Exception:
                pass
            raise TavilyRequestError(exc.code, detail) from exc
        except URLError as exc:
            raise ConnectionError("Tavily network request failed") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TavilyRequestError(None, "Tavily returned invalid JSON") from exc


def requires_fresh_information(query: str) -> bool:
    """Return whether a query must be answered using fresh web information."""

    normalized = " ".join(query.casefold().split())
    if not normalized:
        return False
    if re.search(
        r"\b(what|which|kaun|konsa|kaunsa)\b.*\b(model|api|assistant)\b|"
        r"\b(model|api)\b.*\b(use|using|chala|kar rahe|status)\b|"
        r"\b(tum|aap|you)\b.*\b(kaun|who)\b",
        normalized,
    ):
        return False
    if any(_contains_term(normalized, term) for term in _FRESH_TERMS):
        return True
    return is_maps_or_location_query(normalized)


def _contains_term(text: str, term: str) -> bool:
    if any(ord(character) > 127 for character in term):
        return term in text
    return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text))


def _topic_for_query(query: str) -> str:
    normalized = query.casefold()
    if any(
        term in normalized
        for term in ("stock", "share market", "crypto", "bitcoin", "gold rate", "finance")
    ):
        return "finance"
    if any(
        term in normalized
        for term in ("news", "headline", "breaking", "khabar", "samachar", "election")
    ):
        return "news"
    return "general"


class RealtimeInfoService:
    """Query Tavily once, cache the cited answer, and avoid Gemini grounding."""

    def __init__(self, settings: Settings, client: Any = _CLIENT_NOT_PROVIDED) -> None:
        self.settings = settings
        self._cache: dict[str, tuple[float, RealtimeResponse]] = {}
        if client is _CLIENT_NOT_PROVIDED:
            self._client = None
            self._build_client_on_demand = True
        else:
            self._client = client
            self._build_client_on_demand = False

    def _build_client(self) -> Any:
        return TavilyHTTPClient(
            api_key=self.settings.tavily_api_key or "",
            timeout_seconds=self.settings.request_timeout_seconds,
        )

    def close(self) -> None:
        close_method = getattr(self._client, "close", None)
        if callable(close_method):
            close_method()

    def _answer_with_google_search(self, query: str) -> RealtimeResponse | None:
        """Ground live web queries using Gemini Native Google Search tool."""
        if not self.settings.api_configured:
            return None
        try:
            from automation import _get_cached_genai_client
            from google.genai import types

            client = _get_cached_genai_client(self.settings.api_key)
            prompt = (
                f"You are DarkShadow AI live intelligence officer. Answer the user's fresh real-time query for Captain Kuldeep.\n"
                f"Query: {query}\n"
                f"Current UTC time: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
                f"Provide a direct, up-to-date, grounded answer in natural Hindi/Hinglish (2-4 clear sentences). "
                f"Always lead with the latest facts and figures."
            )
            afc_cfg = (
                types.AutomaticFunctionCallingConfig(disable=True)
                if hasattr(types, "AutomaticFunctionCallingConfig")
                else None
            )
            config = types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                automatic_function_calling=afc_cfg,
                temperature=0.1,
                max_output_tokens=500,
            )
            model_to_use = getattr(self.settings, "model", None) or "gemini-3.8-flash"
            resp = client.models.generate_content(
                model=model_to_use,
                contents=prompt,
                config=config,
            )
            text = (getattr(resp, "text", "") or "").strip()
            if not text:
                return None

            sources: list[SourceCitation] = []
            candidates = getattr(resp, "candidates", None) or ()
            if candidates:
                g_meta = getattr(candidates[0], "grounding_metadata", None)
                if g_meta:
                    chunks = getattr(g_meta, "grounding_chunks", None) or ()
                    for chunk in chunks:
                        web = getattr(chunk, "web", None)
                        if web:
                            url = getattr(web, "uri", None) or ""
                            title = getattr(web, "title", None) or url
                            if url and _is_safe_source_url(url):
                                sources.append(SourceCitation(title=_clean_title(title, url), url=url))

            answer_text = ensure_captain_address(text)
            if sources:
                source_lines = "\n".join(f"- {s.title}: {s.url}" for s in sources[:5])
                display_text = f"{answer_text}\n\nSources (Google Search):\n{source_lines}"
            else:
                display_text = answer_text

            return RealtimeResponse(
                display_text=display_text,
                speech_text=speech_friendly_text(answer_text),
                intent="realtime",
                sources=tuple(sources[:5]),
                error=None,
                confidence=0.95,
                fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                topic=_topic_for_query(query),
            )
        except Exception as exc:
            LOGGER.debug("Google Search Grounding fallback: %s", exc)
            return None

    def _answer_with_google_maps(self, query: str) -> RealtimeResponse | None:
        """Ground location, places, or route queries using Gemini Google Maps Grounding tool."""
        if not self.settings.api_configured:
            return None
        try:
            from automation import _get_cached_genai_client
            from google.genai import types

            client = _get_cached_genai_client(self.settings.api_key)
            prompt = (
                f"You are DarkShadow AI live navigation and location intelligence officer for Captain Kuldeep.\n"
                f"Location/Place Query: {query}\n"
                f"Current UTC time: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
                f"Provide a clear, grounded, helpful answer in natural Hindi/Hinglish (2-4 clear sentences). "
                f"Highlight exact place names, distances, ratings, or route directions when available."
            )
            tools: list[Any] = []
            if hasattr(types, "GoogleMaps"):
                try:
                    tools.append(types.Tool(google_maps=types.GoogleMaps()))
                except Exception:
                    pass
            if hasattr(types, "GoogleSearch"):
                try:
                    tools.append(types.Tool(google_search=types.GoogleSearch()))
                except Exception:
                    pass

            afc_cfg = (
                types.AutomaticFunctionCallingConfig(disable=True)
                if hasattr(types, "AutomaticFunctionCallingConfig")
                else None
            )
            config = types.GenerateContentConfig(
                tools=tools,
                automatic_function_calling=afc_cfg,
                temperature=0.1,
                max_output_tokens=500,
            )
            model_to_use = getattr(self.settings, "model", None) or "gemini-3.8-flash"
            resp = client.models.generate_content(
                model=model_to_use,
                contents=prompt,
                config=config,
            )
            text = (getattr(resp, "text", "") or "").strip()
            if not text:
                return None

            sources: list[SourceCitation] = []
            candidates = getattr(resp, "candidates", None) or ()
            if candidates:
                g_meta = getattr(candidates[0], "grounding_metadata", None)
                if g_meta:
                    chunks = getattr(g_meta, "grounding_chunks", None) or ()
                    for chunk in chunks:
                        maps_chunk = getattr(chunk, "maps", None)
                        if maps_chunk:
                            m_title = getattr(maps_chunk, "title", None) or "Google Maps Place"
                            m_uri = getattr(maps_chunk, "uri", None) or "https://maps.google.com"
                            sources.append(SourceCitation(title=f"[Map] {m_title}", url=m_uri))
                        web_chunk = getattr(chunk, "web", None)
                        if web_chunk:
                            url = getattr(web_chunk, "uri", None) or ""
                            title = getattr(web_chunk, "title", None) or url
                            if url and _is_safe_source_url(url):
                                sources.append(SourceCitation(title=_clean_title(title, url), url=url))

            answer_text = ensure_captain_address(text)
            if sources:
                source_lines = "\n".join(f"- {s.title}: {s.url}" for s in sources[:5])
                display_text = f"{answer_text}\n\nSources (Google Maps / Grounding):\n{source_lines}"
            else:
                display_text = answer_text

            return RealtimeResponse(
                display_text=display_text,
                speech_text=speech_friendly_text(answer_text),
                intent="maps_grounding",
                sources=tuple(sources[:5]),
                error=None,
                confidence=0.96,
                fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                topic="maps",
            )
        except Exception as exc:
            LOGGER.debug("Google Maps Grounding fallback: %s", exc)
            return None

    def answer(self, query: str) -> RealtimeResponse:
        """Return a grounded answer, or an honest verification failure."""

        cleaned = query.strip()
        if not cleaned:
            return self._response(
                "Captain, fresh-information query khaali hai.", "empty_input"
            )
        cache_key = " ".join(cleaned.casefold().split())
        cached = self._cache.get(cache_key)
        if cached is not None and cached[0] >= time.monotonic():
            return cached[1]

        # 1. Google Maps Grounding if query is location/maps-related and enabled
        if getattr(self.settings, "map_grounding_enabled", True) and is_maps_or_location_query(cleaned) and self.settings.api_configured:
            maps_response = self._answer_with_google_maps(cleaned)
            if maps_response is not None:
                if self.settings.realtime_cache_seconds > 0:
                    self._cache[cache_key] = (
                        time.monotonic() + self.settings.realtime_cache_seconds,
                        maps_response,
                    )
                return maps_response

        # 2. Native Google Search Grounding if provider is auto or google
        provider = getattr(self.settings, "search_grounding_provider", "auto")
        if provider in {"auto", "google"} and self.settings.api_configured:
            google_response = self._answer_with_google_search(cleaned)
            if google_response is not None:
                if self.settings.realtime_cache_seconds > 0:
                    self._cache[cache_key] = (
                        time.monotonic() + self.settings.realtime_cache_seconds,
                        google_response,
                    )
                return google_response
            if provider == "google":
                return self._response(
                    "Captain, Google Search Grounding se verified answer fetch nahi ho saka. Thodi der baad retry kijiye.",
                    "grounding_failed",
                )

        # 2. Fallback to Tavily
        if not self.settings.tavily_configured and self._build_client_on_demand:
            return self._response(
                "Captain, fresh web information ke liye Gemini API key ya TAVILY_API_KEY configure kijiye.",
                "missing_search_keys",
            )
        if self._client is None and self._build_client_on_demand:
            self._client = self._build_client()
        if self._client is None:
            return self._response(
                "Captain, fresh-information client initialize nahi ho saka.",
                "client_unavailable",
            )

        topic = _topic_for_query(cleaned)
        try:
            result = self._client.search(
                cleaned,
                search_depth=self.settings.tavily_search_depth,
                max_results=self.settings.tavily_max_results,
                topic=topic,
            )
        except Exception as exc:
            return self._error_response(exc)

        answer_text = str(_field(result, "answer", "") or "").strip()
        sources = self._extract_tavily_sources(result)
        if not answer_text or not sources:
            LOGGER.warning(
                "Fresh query was not verifiably grounded (text=%s, sources=%s)",
                bool(answer_text), len(sources),
            )
            return self._response(
                "Captain, latest information ko reliable sources se verify nahi "
                "kar saka. Main bina verification ke current answer invent nahi "
                "karunga; thodi der baad retry kijiye.",
                "grounding_failed",
            )

        answer_text = ensure_captain_address(answer_text)
        source_lines = "\n".join(
            f"- {source.title}: {source.url}" for source in sources
        )
        response = RealtimeResponse(
            display_text=f"{answer_text}\n\nSources:\n{source_lines}",
            speech_text=speech_friendly_text(answer_text),
            intent="realtime",
            sources=sources,
            error=None,
            confidence=min(0.96, 0.64 + len(sources) * 0.07),
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            topic=topic,
        )
        if self.settings.realtime_cache_seconds > 0:
            self._cache[cache_key] = (
                time.monotonic() + self.settings.realtime_cache_seconds,
                response,
            )
        return response

    @staticmethod
    def _extract_tavily_sources(result: Any) -> tuple[SourceCitation, ...]:
        sources: list[SourceCitation] = []
        seen_urls: set[str] = set()
        for item in _field(result, "results", ()) or ():
            url = str(_field(item, "url", "") or "").strip()
            if not _is_safe_source_url(url) or url in seen_urls:
                continue
            sources.append(
                SourceCitation(
                    title=_clean_title(_field(item, "title", ""), url),
                    url=url,
                )
            )
            seen_urls.add(url)
        return tuple(sources)

    def _error_response(self, exc: Exception) -> RealtimeResponse:
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        error_name = type(exc).__name__
        lowered = f"{error_name} {getattr(exc, 'message', '')}".casefold()
        LOGGER.error(
            "Tavily search request failed (type=%s, status=%s)",
            error_name, status,
        )
        if status == 401 or "unauthorized" in lowered:
            return self._response(
                "Captain, Tavily API key invalid ya unauthorized hai. `.env` "
                "mein TAVILY_API_KEY verify kijiye.",
                "invalid_tavily_key",
            )
        if status == 403:
            return self._response(
                "Captain, Tavily account ne is search option ko allow nahi kiya. "
                "Basic-compatible request use ho rahi hai; retry kijiye.",
                "tavily_forbidden",
            )
        if status in {432, 433}:
            return self._response(
                "Captain, Tavily monthly credits ya spending limit complete ho gayi.",
                "tavily_credits_exhausted",
            )
        if status == 429 or "rate" in lowered:
            return self._response(
                "Captain, Tavily rate limit hit hui. Thoda wait karke retry kijiye.",
                "rate_limited",
            )
        if status in {408, 504} or isinstance(exc, TimeoutError) or "timeout" in lowered:
            return self._response(
                "Captain, Tavily search request time out ho gayi. App "
                "running hai; retry kar sakte hain.",
                "timeout",
            )
        if isinstance(exc, (ConnectionError, OSError)) or any(
            token in lowered
            for token in ("connecterror", "network", "dns", "name resolution")
        ):
            return self._response(
                "Captain, Tavily se fresh information lane ke liye internet "
                "connection nahi mil rahi.",
                "no_internet",
            )
        return self._response(
            "Captain, fresh information verify nahi ho saki. Technical error "
            "safe form mein log hui; retry kar sakte hain.",
            "api_error",
        )

    @staticmethod
    def _response(text: str, error: str) -> RealtimeResponse:
        display_text = ensure_captain_address(text)
        return RealtimeResponse(
            display_text=display_text,
            speech_text=speech_friendly_text(display_text),
            intent="realtime",
            sources=(),
            error=error,
        )


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _is_safe_source_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _clean_title(raw_title: Any, url: str) -> str:
    title = " ".join(str(raw_title or "").split())[:120]
    return title or urlparse(url).netloc
