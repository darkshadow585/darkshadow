"""Spotify Web API integration for DarkShadow."""

import os
import ssl
import json
import base64
import time
import logging
import urllib.request
import urllib.parse
from typing import Any
from config import Settings, load_settings
from networking import install_ipv4_first_dns

install_ipv4_first_dns()
LOGGER = logging.getLogger(__name__)

def _get_ssl_context() -> ssl.SSLContext | None:
    """Create SSL context with certifi or safe fallback."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    except Exception:
        return None

class SpotifyClient:
    """Zero-dependency Spotify Web API client using Client Credentials OAuth."""

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str = "http://127.0.0.1:8888/callback") -> None:
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.redirect_uri = redirect_uri.strip()
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._ssl_ctx = _get_ssl_context()

    def _get_access_token(self) -> str | None:
        """Fetch or refresh Spotify Bearer access token."""
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token

        if not self.client_id or not self.client_secret:
            return None

        try:
            auth_header = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode("utf-8")).decode("utf-8")
            token_url = "https://accounts.spotify.com/api/token"
            data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")
            req = urllib.request.Request(
                token_url,
                data=data,
                headers={
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "DarkShadow-AI/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=6.0, context=self._ssl_ctx) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                self._access_token = body.get("access_token")
                expires_in = body.get("expires_in", 3600)
                self._token_expires_at = time.monotonic() + expires_in - 60
                return self._access_token
        except Exception as exc:
            LOGGER.warning("Spotify token acquisition failed: %s", exc)
            return None

    def search_track(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search Spotify for tracks and return exact metadata and URLs."""
        token = self._get_access_token()
        if not token:
            return []

        try:
            params = urllib.parse.urlencode({
                "q": query,
                "type": "track",
                "limit": limit,
                "market": "IN",
            })
            url = f"https://api.spotify.com/v1/search?{params}"
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "DarkShadow-AI/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=6.0, context=self._ssl_ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                tracks = data.get("tracks", {}).get("items", [])
                results = []
                for t in tracks:
                    artists = ", ".join(a["name"] for a in t.get("artists", []))
                    track_name = t.get("name", "")
                    track_id = t.get("id", "")
                    track_url = t.get("external_urls", {}).get("spotify", f"https://open.spotify.com/track/{track_id}")
                    uri = t.get("uri", f"spotify:track:{track_id}")
                    album = t.get("album", {}).get("name", "")
                    results.append({
                        "id": track_id,
                        "title": track_name,
                        "artists": artists,
                        "album": album,
                        "url": track_url,
                        "uri": uri,
                    })
                return results
        except urllib.error.HTTPError as http_err:
            if http_err.code == 403:
                LOGGER.debug("Spotify track search unavailable: HTTP 403 (Active Spotify Premium required for Developer App)")
            else:
                LOGGER.warning("Spotify track search HTTP error: %s", http_err)
            return []
        except Exception as exc:
            LOGGER.warning("Spotify track search failed: %s", exc)
            return []

def get_spotify_client(settings: Settings | None = None) -> SpotifyClient | None:
    """Return active Spotify client if configured in settings or environment."""
    s = settings or load_settings()
    cid = s.spotify_client_id or os.environ.get("SPOTIFY_CLIENT_ID")
    csec = s.spotify_client_secret or os.environ.get("SPOTIFY_CLIENT_SECRET")
    ruri = s.spotify_redirect_uri or os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    if cid and csec:
        return SpotifyClient(cid, csec, ruri)
    return None