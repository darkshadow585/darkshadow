"""YouTube Full Potential Engine for DarkShadow.

Features:
- Video ID and URL resolution (watch, shorts, youtu.be, embed, search)
- ISO 8601 duration parsing (PT15M33S -> 15 min 33 sec)
- Deep video metadata (views, likes, channel, tags, exact length)
- Subtitle / Transcript fetching via YouTube TimedText API
- AI Video Summarizer with Gemini Flash (Concise bullet points & insights)
- Public Comments Sentiment & Review Analyzer (commentThreads API + AI)
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


def extract_youtube_video_id(url_or_text: str) -> str | None:
    """Extract standard 11-character YouTube video ID from various URL formats or raw ID."""
    cleaned = str(url_or_text).strip()
    if not cleaned:
        return None

    # Direct 11-char ID
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", cleaned):
        return cleaned

    # Standard watch URL: youtube.com/watch?v=XXXXXXXXXXX
    match = re.search(r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/)([a-zA-Z0-9_-]{11})", cleaned)
    if match:
        return match.group(1)

    return None


def parse_iso8601_duration(duration_str: str) -> tuple[str, int]:
    """Parse ISO 8601 duration string (e.g. 'PT1H15M33S', 'PT4M20S') to human readable text and total seconds."""
    raw = str(duration_str).strip()
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", raw)
    if not match:
        return raw, 0

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    total_seconds = hours * 3600 + minutes * 60 + seconds

    parts = []
    if hours > 0:
        parts.append(f"{hours} hr")
    if minutes > 0:
        parts.append(f"{minutes} min")
    if seconds > 0 or not parts:
        parts.append(f"{seconds} sec")

    return " ".join(parts), total_seconds


def fetch_video_details(
    video_id: str,
    api_key: str | None = None,
    timeout_seconds: float = 6.0,
) -> dict[str, Any] | None:
    """Fetch structured metadata for a YouTube video using Data API v3 or HTML fallback."""
    clean_id = extract_youtube_video_id(video_id) or video_id
    if not clean_id or len(clean_id) != 11:
        return None

    # 1. Official YouTube Data API v3
    if api_key:
        try:
            url = (
                f"https://www.googleapis.com/youtube/v3/videos?"
                f"part=snippet,contentDetails,statistics&id={clean_id}&key={api_key.strip()}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "DarkShadow-AI/2.0"})
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items", [])
                if items:
                    item = items[0]
                    snippet = item.get("snippet", {})
                    content_details = item.get("contentDetails", {})
                    statistics = item.get("statistics", {})
                    raw_dur = content_details.get("duration", "PT0S")
                    human_dur, total_secs = parse_iso8601_duration(raw_dur)

                    return {
                        "video_id": clean_id,
                        "title": snippet.get("title", ""),
                        "channel": snippet.get("channelTitle", ""),
                        "channel_id": snippet.get("channelId", ""),
                        "description": snippet.get("description", ""),
                        "published_at": snippet.get("publishedAt", ""),
                        "tags": snippet.get("tags", []),
                        "duration": human_dur,
                        "duration_seconds": total_secs,
                        "view_count": int(statistics.get("viewCount", 0)),
                        "like_count": int(statistics.get("likeCount", 0)),
                        "comment_count": int(statistics.get("commentCount", 0)),
                        "url": f"https://www.youtube.com/watch?v={clean_id}",
                    }
        except Exception as api_err:
            LOGGER.debug("YouTube API video details failed: %s", api_err)

    # 2. HTML Scraper Fallback
    try:
        url = f"https://www.youtube.com/watch?v={clean_id}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            },
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            title_m = re.search(r'<meta name="title" content="([^"]+)">', html)
            desc_m = re.search(r'<meta name="description" content="([^"]+)">', html)
            title = title_m.group(1) if title_m else "YouTube Video"
            description = desc_m.group(1) if desc_m else ""
            return {
                "video_id": clean_id,
                "title": title,
                "channel": "",
                "description": description,
                "duration": "Unknown",
                "duration_seconds": 0,
                "view_count": 0,
                "like_count": 0,
                "comment_count": 0,
                "url": url,
            }
    except Exception as scrape_err:
        LOGGER.debug("YouTube HTML video scrape failed: %s", scrape_err)

    return None


def fetch_video_transcript(video_id: str, timeout_seconds: float = 6.0) -> str | None:
    """Fetch plain text subtitles/transcripts for a video using TimedText endpoints."""
    clean_id = extract_youtube_video_id(video_id) or video_id
    if not clean_id or len(clean_id) != 11:
        return None

    # 1. Direct TimedText API (English / Hindi / Auto-generated)
    for lang in ("en", "hi", "en-US", "en-GB", "a.en", "a.hi"):
        try:
            tt_url = f"https://www.youtube.com/api/timedtext?v={clean_id}&lang={lang}"
            req = urllib.request.Request(
                tt_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                xml_data = resp.read().decode("utf-8", errors="ignore")
                if xml_data and "<text" in xml_data:
                    root = ET.fromstring(xml_data)
                    lines = [elem.text.strip() for elem in root.findall(".//text") if elem.text and elem.text.strip()]
                    if lines:
                        return " ".join(lines)
        except Exception:
            continue

    # 2. Extract caption tracks from player JSON in webpage
    try:
        url = f"https://www.youtube.com/watch?v={clean_id}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            m = re.search(r'"captionTracks":(\[.*?\])', html)
            if m:
                tracks = json.loads(m.group(1))
                if tracks:
                    base_url = tracks[0].get("baseUrl")
                    if base_url:
                        with urllib.request.urlopen(base_url, timeout=timeout_seconds) as track_resp:
                            track_xml = track_resp.read().decode("utf-8", errors="ignore")
                            root = ET.fromstring(track_xml)
                            lines = [elem.text.strip() for elem in root.findall(".//text") if elem.text and elem.text.strip()]
                            if lines:
                                return " ".join(lines)
    except Exception as exc:
        LOGGER.debug("Caption track extract error: %s", exc)

    return None


def fetch_video_comments(
    video_id: str,
    max_results: int = 30,
    api_key: str | None = None,
    timeout_seconds: float = 6.0,
) -> list[dict[str, Any]]:
    """Fetch top comments for a video using YouTube commentThreads API."""
    clean_id = extract_youtube_video_id(video_id) or video_id
    if not clean_id or len(clean_id) != 11 or not api_key:
        return []

    try:
        url = (
            f"https://www.googleapis.com/youtube/v3/commentThreads?"
            f"part=snippet&videoId={clean_id}&maxResults={max_results}&order=relevance&key={api_key.strip()}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "DarkShadow-AI/2.0"})
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            comments = []
            for item in data.get("items", []):
                top_comment = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
                text = top_comment.get("textDisplay", "")
                author = top_comment.get("authorDisplayName", "User")
                likes = top_comment.get("likeCount", 0)
                if text:
                    comments.append({
                        "author": author,
                        "text": text,
                        "likes": likes,
                    })
            return comments
    except Exception as exc:
        LOGGER.debug("YouTube comment fetch error: %s", exc)
        return []


def analyze_youtube_video_agentic(
    url_or_query: str,
    prompt: str = "Analyze this video, highlight key moments with timestamps, and summarize main takeaways.",
    model: str | None = None,
    gemini_api_key: str | None = None,
    youtube_api_key: str | None = None,
) -> dict[str, Any]:
    """Analyze a YouTube video using Gemini's Agentic Video Understanding (released Sept 1, 2026).

    Uses an active Think-Act-Observe loop to dynamically inspect key segments,
    consuming up to 88% fewer tokens with 66% lower cost.
    Falls back gracefully to transcript/metadata AI summarization on errors.
    """
    vid = extract_youtube_video_id(url_or_query)
    if not vid:
        from automation import extract_youtube_search_results
        res = extract_youtube_search_results(url_or_query, max_results=1)
        if res:
            vid = res[0]["id"]

    if not vid:
        return {
            "success": False,
            "error": "video_not_found",
            "message": f"YouTube par '{url_or_query}' se koi video match nahi hui.",
        }

    yt_url = f"https://www.youtube.com/watch?v={vid}"
    details = fetch_video_details(vid, api_key=youtube_api_key)
    title = details.get("title", "YouTube Video") if details else "YouTube Video"
    channel = details.get("channel", "") if details else ""
    duration = details.get("duration", "") if details else ""

    if not gemini_api_key:
        try:
            from config import load_settings
            s = load_settings()
            gemini_api_key = s.api_key
            if not model:
                model = s.agentic_video_model
        except Exception:
            pass

    if not model:
        model = "gemini-3.7-flash"

    if not gemini_api_key:
        return {
            "success": False,
            "error": "gemini_api_key_missing",
            "message": "Gemini API key configured nahi hai video analyze karne ke liye.",
        }

    try:
        from automation import _get_cached_genai_client
        client = _get_cached_genai_client(gemini_api_key)

        analysis_prompt = (
            f"You are DarkShadow AI Agentic Video Analyst. "
            f"Analyze the following video for Captain Kuldeep in clear, natural Hinglish.\n"
            f"Video Title: {title}\n"
            f"Channel: {channel}\n"
            f"User Goal / Question: {prompt}\n\n"
            f"Structure your response:\n"
            f"1. 🎯 **Video Gist & Objective** (1-2 sentences)\n"
            f"2. ⏱️ **Key Moments / Timeline** (Important timestamps & what happens)\n"
            f"3. 📌 **Deep Insights & Key Learnings** (Key points, code, or visual demos shown)\n"
            f"4. 💡 **Captain's Actionable Summary**"
        )

        agentic_text = ""
        # 1. Try Gemini Interactions API with processing: agentic
        interactions_api = getattr(client, "interactions", None)
        if interactions_api is not None and callable(getattr(interactions_api, "create", None)):
            try:
                interaction = interactions_api.create(
                    model=model,
                    input=[
                        {
                            "type": "video",
                            "uri": yt_url,
                            "processing": "agentic",
                        },
                        {
                            "type": "text",
                            "text": analysis_prompt,
                        },
                    ],
                )
                agentic_text = str(
                    getattr(interaction, "output_text", "")
                    or getattr(interaction, "text", "")
                    or ""
                ).strip()
            except Exception as ia_exc:
                LOGGER.debug("Agentic interaction API call failed: %s; trying models generate_content", ia_exc)

        # 2. Try models.generate_content with URI Part if interactions did not return text
        if not agentic_text:
            try:
                from google.genai import types
                part = types.Part.from_uri(file_uri=yt_url, mime_type="video/*")
                resp = client.models.generate_content(
                    model=model,
                    contents=[part, analysis_prompt],
                )
                agentic_text = (getattr(resp, "text", "") or "").strip()
            except Exception as gen_exc:
                LOGGER.debug("Direct URI generate_content failed: %s", gen_exc)

        if agentic_text:
            return {
                "success": True,
                "video_id": vid,
                "title": title,
                "channel": channel,
                "duration": duration,
                "url": yt_url,
                "agentic_mode": True,
                "summary": agentic_text,
            }

        LOGGER.info("Agentic video understanding returned empty; falling back to transcript summarizer")
        return summarize_youtube_video_ai(
            vid,
            detail_level="detailed",
            youtube_api_key=youtube_api_key,
            gemini_api_key=gemini_api_key,
            skip_agentic_retry=True,
        )
    except Exception as exc:
        LOGGER.warning("Agentic video understanding failed: %s. Falling back to transcript.", exc)
        return summarize_youtube_video_ai(
            vid,
            detail_level="detailed",
            youtube_api_key=youtube_api_key,
            gemini_api_key=gemini_api_key,
            skip_agentic_retry=True,
        )


def analyze_local_video_file(
    file_path: str,
    prompt: str = "Analyze this screen recording / video, identify actions, errors, or key events with timestamps.",
    model: str | None = None,
    gemini_api_key: str | None = None,
) -> dict[str, Any]:
    """Analyze a local desktop screen recording or video file using Gemini multimodal video understanding."""
    p = Path(file_path).expanduser().resolve()
    if not p.is_file():
        return {
            "success": False,
            "error": "file_not_found",
            "message": f"Captain, video file '{file_path}' exist nahi karti.",
        }

    if not gemini_api_key:
        try:
            from config import load_settings
            s = load_settings()
            gemini_api_key = s.api_key
            if not model:
                model = s.agentic_video_model
        except Exception:
            pass

    if not model:
        model = "gemini-3.7-flash"

    if not gemini_api_key:
        return {
            "success": False,
            "error": "gemini_api_key_missing",
            "message": "Gemini API key configured nahi hai video file analyze karne ke liye.",
        }

    try:
        from automation import _get_cached_genai_client
        client = _get_cached_genai_client(gemini_api_key)

        uploaded = client.files.upload(file=str(p))
        analysis_prompt = (
            f"You are DarkShadow AI Video Troubleshooter. "
            f"Analyze this local video recording for Captain Kuldeep in clear, natural Hinglish.\n"
            f"File: {p.name}\n"
            f"User Goal: {prompt}\n\n"
            f"Structure your response:\n"
            f"1. 🎯 **Recording Overview**\n"
            f"2. ⏱️ **Timestamped Events & Key Actions**\n"
            f"3. 🔍 **Observed Errors / Issues / Highlights**\n"
            f"4. 💡 **Recommended Fix or Conclusion**"
        )
        resp = client.models.generate_content(
            model=model,
            contents=[uploaded, analysis_prompt],
        )
        out = (getattr(resp, "text", "") or "").strip()
        return {
            "success": True,
            "file_name": p.name,
            "file_path": str(p),
            "summary": out,
        }
    except Exception as exc:
        LOGGER.warning("Local video file analysis failed: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "message": f"Captain, video file analyze nahi ho saki: {exc}",
        }


def summarize_youtube_video_ai(
    url_or_query: str,
    detail_level: str = "concise",
    youtube_api_key: str | None = None,
    gemini_api_key: str | None = None,
    skip_agentic_retry: bool = False,
) -> dict[str, Any]:
    """Produce an AI summary of a YouTube video from its transcript, metadata, or Agentic Video Understanding."""
    if not skip_agentic_retry:
        try:
            from config import load_settings
            s = load_settings()
            if s.youtube_agentic_video_enabled:
                agentic_res = analyze_youtube_video_agentic(
                    url_or_query,
                    prompt="Summarize this video concisely for Captain Kuldeep, highlighting key points and actionable takeaways.",
                    youtube_api_key=youtube_api_key,
                    gemini_api_key=gemini_api_key or s.api_key,
                    model=s.agentic_video_model,
                )
                if agentic_res.get("success"):
                    return agentic_res
        except Exception as ag_err:
            LOGGER.debug("Agentic video fallback to transcript: %s", ag_err)

    # Resolve video ID
    vid = extract_youtube_video_id(url_or_query)
    if not vid:
        from automation import extract_youtube_search_results
        res = extract_youtube_search_results(url_or_query, max_results=1)
        if res:
            vid = res[0]["id"]

    if not vid:
        return {
            "success": False,
            "error": "video_not_found",
            "message": f"YouTube par '{url_or_query}' se koi video match nahi hui.",
        }

    details = fetch_video_details(vid, api_key=youtube_api_key)
    title = details.get("title", "YouTube Video") if details else "YouTube Video"
    channel = details.get("channel", "") if details else ""
    duration = details.get("duration", "") if details else ""
    description = details.get("description", "") if details else ""

    transcript = fetch_video_transcript(vid)

    content_text = ""
    if transcript:
        content_text = f"VIDEO TRANSCRIPT (Full spoken text):\n{transcript[:15000]}"
    else:
        content_text = f"VIDEO METADATA & DESCRIPTION:\nTitle: {title}\nChannel: {channel}\nDescription:\n{description[:4000]}"

    # AI Summary with Gemini
    if not gemini_api_key:
        try:
            from config import load_settings
            s = load_settings()
            gemini_api_key = s.api_key
        except Exception:
            pass

    if not gemini_api_key:
        return {
            "success": False,
            "error": "gemini_api_key_missing",
            "message": "Gemini API key configured nahi hai summary generate karne ke liye.",
        }

    try:
        from automation import _get_cached_genai_client
        from google.genai import types

        client = _get_cached_genai_client(gemini_api_key)
        prompt = (
            f"You are DarkShadow AI co-pilot. Summarize the following YouTube video for Captain in natural, clear Hinglish.\n"
            f"Video Title: {title}\n"
            f"Channel: {channel}\n\n"
            f"{content_text}\n\n"
            "Format your output clearly:\n"
            "1. 🎯 **Main Topic / Gist** (1 short sentence)\n"
            "2. 📌 **Key Takeaways** (3-4 concise bullet points)\n"
            "3. 💡 **Actionable Conclusion**\n"
            "Keep it crisp, accurate, and easy to read."
        )

        cfg = types.GenerateContentConfig(
            max_output_tokens=350,
            temperature=0.2,
        )
        model_candidates = [
            "gemini-3.5-flash-lite",
            "gemini-flash-lite-latest",
            "gemini-3.1-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.6-flash",
            "gemini-3.8-flash",
            "gemini-3.7-flash",
        ]
        summary_text = ""
        last_err = None
        for cand in model_candidates:
            try:
                response = client.models.generate_content(
                    model=cand,
                    contents=prompt,
                    config=cfg,
                )
                summary_text = (response.text or "").strip()
                if summary_text:
                    break
            except Exception as m_err:
                last_err = m_err
                LOGGER.debug("Summarizer model %s failed: %s", cand, m_err)

        if not summary_text and last_err:
            raise last_err

        return {
            "success": True,
            "video_id": vid,
            "title": title,
            "channel": channel,
            "duration": duration,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "has_transcript": bool(transcript),
            "summary": summary_text,
        }
    except Exception as exc:
        LOGGER.warning("YouTube video summarization failed: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "message": f"Video summarize nahi ho saki: {exc}",
        }


def analyze_youtube_comments_ai(
    url_or_query: str,
    max_comments: int = 30,
    youtube_api_key: str | None = None,
    gemini_api_key: str | None = None,
) -> dict[str, Any]:
    """Analyze public comments on a YouTube video and compute sentiment analysis."""
    vid = extract_youtube_video_id(url_or_query)
    if not vid:
        from automation import extract_youtube_search_results
        res = extract_youtube_search_results(url_or_query, max_results=1)
        if res:
            vid = res[0]["id"]

    if not vid:
        return {
            "success": False,
            "error": "video_not_found",
            "message": f"YouTube par '{url_or_query}' se koi video match nahi hui.",
        }

    details = fetch_video_details(vid, api_key=youtube_api_key)
    title = details.get("title", "YouTube Video") if details else "YouTube Video"

    comments = fetch_video_comments(vid, max_results=max_comments, api_key=youtube_api_key)
    if not comments:
        return {
            "success": False,
            "error": "comments_unavailable",
            "message": f"'{title}' ke comments access nahi ho sake (comments off ho sakte hain ya API key required hai).",
        }

    formatted_comments = "\n".join(f"- [{c['author']}] ({c['likes']} likes): {c['text']}" for c in comments[:35])

    if not gemini_api_key:
        try:
            from config import load_settings
            s = load_settings()
            gemini_api_key = s.api_key
        except Exception:
            pass

    if not gemini_api_key:
        return {
            "success": False,
            "error": "gemini_api_key_missing",
            "message": "Gemini API key configured nahi hai.",
        }

    try:
        from automation import _get_cached_genai_client
        from google.genai import types

        client = _get_cached_genai_client(gemini_api_key)
        prompt = (
            f"You are DarkShadow AI analyzing public comments for Captain on YouTube video '{title}'.\n\n"
            f"SAMPLE COMMENTS:\n{formatted_comments}\n\n"
            "Provide a concise public sentiment report in natural Hinglish:\n"
            "1. 📊 **Overall Sentiment** (e.g. 85% Positive, 15% Mixed/Critical)\n"
            "2. 👍 **What people loved / Praise** (2 bullet points)\n"
            "3. 👎 **Major complaints / Criticisms** (if any)\n"
            "4. 💬 **General Audience Consensus**\n"
            "Keep it direct and punchy."
        )

        cfg = types.GenerateContentConfig(
            max_output_tokens=300,
            temperature=0.2,
        )
        model_candidates = [
            "gemini-3.5-flash-lite",
            "gemini-flash-lite-latest",
            "gemini-3.1-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.6-flash",
            "gemini-3.8-flash",
            "gemini-3.7-flash",
        ]
        analysis_text = ""
        last_err = None
        for cand in model_candidates:
            try:
                response = client.models.generate_content(
                    model=cand,
                    contents=prompt,
                    config=cfg,
                )
                analysis_text = (response.text or "").strip()
                if analysis_text:
                    break
            except Exception as m_err:
                last_err = m_err
                LOGGER.debug("Comment analysis model %s failed: %s", cand, m_err)

        if not analysis_text and last_err:
            raise last_err

        return {
            "success": True,
            "video_id": vid,
            "title": title,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "comment_count_analyzed": len(comments),
            "top_comments": comments[:10],
            "analysis": analysis_text,
        }
    except Exception as exc:
        LOGGER.warning("YouTube comment analysis failed: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "message": f"Comments analyze nahi ho sake: {exc}",
        }
