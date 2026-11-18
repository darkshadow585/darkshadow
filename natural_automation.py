"""Explicit natural-language browser automations handled before the LLM."""

from __future__ import annotations

import logging
import re
import urllib.request
import webbrowser
from urllib.parse import quote_plus


LOGGER = logging.getLogger(__name__)
_YOUTUBE = re.compile(r"\byou\s*tube\b|\byoutube\b", re.IGNORECASE)
_ACTION = re.compile(
    r"\b(play|open|chalao|chala do|lagao|laga do|bajao|baja do|"
    r"khol|kholo|kholkar|launch)\b",
    re.IGNORECASE,
)
_PLAY = re.compile(
    r"\b(play|chalao|chala do|lagao|laga do|bajao|baja do)\b",
    re.IGNORECASE,
)
_COMMAND_WORDS = re.compile(
    r"\b(youtube|you tube|play|open|chalao|chala do|lagao|laga do|"
    r"bajao|baja do|khol|kholo|kholkar|launch|please|par|pe|mein|me|"
    r"song|gaana|gana)\b",
    re.IGNORECASE,
)
def _query(message: str) -> str:
    return " ".join(_COMMAND_WORDS.sub(" ", message).split()).strip(" ,.-")


def handle_natural_automation(message: str) -> str | None:
    """Handle explicit natural-language YouTube, search, ordinal, and screen commands before LLM."""
    from automation import (
        GLOBAL_AUTOMATION_CONTEXT,
        parse_ordinal_selection,
        play_youtube,
        search_youtube,
        analyze_screen_content,
    )

    cleaned = message.strip()

    # 1. Handle ordinal selection e.g. "2nd wala chala do", "second wala play karo", "doosra wala bajao"
    ordinal = parse_ordinal_selection(cleaned)
    if ordinal is not None and GLOBAL_AUTOMATION_CONTEXT.last_search_results:
        res = play_youtube(cleaned, context=GLOBAL_AUTOMATION_CONTEXT)
        if res.success:
            return res.message

    # 2. Screen vision check e.g. "screen dekho", "screen par kya chal raha hai"
    if re.search(r"\b(?:screen|display|monitor)\s*(?:par\s*kya\s*(?:hai|chal\s*raha\s*hai)|dekho|dekh|check\s*karo|analyze|padho|batao)\b|\b(?:kya\s*chal\s*raha\s*hai\s*screen\s*par|screen\s*read\s*karo)\b", cleaned, re.I):
        res = analyze_screen_content(prompt=cleaned)
        return res.message

    # 3. YouTube specific actions
    if _YOUTUBE.search(cleaned) and _ACTION.search(cleaned):
        query = _query(cleaned)
        # Search vs Play
        if re.search(r"\b(?:search|khoj|dhundho|list|dikhao)\b", cleaned, re.I):
            res = search_youtube(query, context=GLOBAL_AUTOMATION_CONTEXT)
            return res.message

        if _PLAY.search(cleaned) and query:
            res = play_youtube(query, context=GLOBAL_AUTOMATION_CONTEXT)
            return res.message

        opened = webbrowser.open("https://www.youtube.com", new=2)
        return (
            "Captain, YouTube khol raha hoon."
            if opened
            else "Captain, default browser open nahi ho saka."
        )

    # 4. Scroll screen commands e.g. "scroll down", "thoda neeche scroll karo", "scroll up"
    if re.search(r"\b(?:scroll\s*down|neeche\s*scroll(?:\s*karo)?|thoda\s*neeche(?:\s*karo)?|niche\s*scroll(?:\s*karo)?|scroll\s*karo)\b", cleaned, re.I):
        from automation import scroll_screen
        return scroll_screen(direction="down").message
    if re.search(r"\b(?:scroll\s*up|upar\s*scroll(?:\s*karo)?|thoda\s*upar(?:\s*karo)?)\b", cleaned, re.I):
        from automation import scroll_screen
        return scroll_screen(direction="up").message

    # 5. Click screen element commands e.g. "click the first link", "pehli link click karo"
    if re.search(r"\b(?:click\s+(?:on\s+)?(?:the\s+)?(?:first|1st|pehli)\s+link|first\s+link\s+(?:par\s+)?click(?:\s*karo)?|pehli\s+link\s+(?:kholo|click\s*karo)|click\s+first\s+link)\b", cleaned, re.I):
        from automation import click_screen_element
        return click_screen_element(target="first_link").message
    if re.search(r"\b(?:click\s+(?:on\s+)?(?:the\s+)?(?:second|2nd|doosri)\s+link|second\s+link\s+(?:par\s+)?click(?:\s*karo)?|doosri\s+link\s+(?:kholo|click\s*karo))\b", cleaned, re.I):
        from automation import click_screen_element
        return click_screen_element(target="second_link").message

    # 6. Browser navigation commands e.g. "back jao", "refresh karo", "tab close karo"
    if re.search(r"\b(?:browser\s+)?(?:back\s+jao|piche\s+jao|go\s+back|peeche\s+karo)\b", cleaned, re.I):
        from automation import control_browser_action
        return control_browser_action(action="back").message
    if re.search(r"\b(?:refresh\s*karo|reload\s*karo|page\s*refresh)\b", cleaned, re.I):
        from automation import control_browser_action
        return control_browser_action(action="refresh").message
    # 7. Media Key Controls (Play/Pause, Next, Previous)
    if re.search(r"\b(?:pause(?:\s+(?:the\s+)?(?:song|music|gaana|gana|video))?|gaana\s+(?:roko|pause\s*karo)|video\s+(?:roko|pause\s*karo)|song\s+pause(?:\s*karo)?)\b", cleaned, re.I):
        from automation import trigger_media_key
        return trigger_media_key(key="play_pause").message
    if re.search(r"\b(?:next(?:\s+(?:the\s+)?(?:song|music|gaana|gana|track))?|agla\s+(?:gaana|gana|song)|song\s+next(?:\s*karo)?)\b", cleaned, re.I):
        from automation import trigger_media_key
        return trigger_media_key(key="next").message
    if re.search(r"\b(?:prev(?:ious)?(?:\s+(?:the\s+)?(?:song|music|gaana|gana|track))?|pichhla\s+(?:gaana|gana|song)|purana\s+gaana)\b", cleaned, re.I):
        from automation import trigger_media_key
        return trigger_media_key(key="previous").message

    # 8. Lock PC / Workstation
    if re.search(r"\b(?:lock\s+(?:the\s+)?(?:pc|screen|computer|workstation)|(?:pc|screen|computer)\s+lock(?:\s+karo|\s+kar\s+do)?)\b", cleaned, re.I):
        from automation import lock_workstation
        return lock_workstation().message

    # 9. Clipboard Reading
    if re.search(r"\b(?:read\s+clipboard|get\s+clipboard|clipboard\s+(?:padho|read\s*karo|me\s*kya\s*hai|dekho))\b", cleaned, re.I):
        from automation import get_clipboard_text
        return get_clipboard_text().message

    # 10. Desktop Screenshot
    if re.search(r"\b(?:take\s+(?:a\s+)?screenshot|screenshot\s+(?:lo|le\s+lo|save\s*karo)|screen\s+capture(?:\s+karo)?)\b", cleaned, re.I):
        from automation import save_screenshot
        return save_screenshot().message

    # 11. YouTube AI Video Summarizer
    sum_m = re.search(r"\b(?:summarize\s+(?:the\s+)?(?:video|youtube\s+video)?|(?:video|youtube\s+video)\s*(?:ka\s+)?summary(?:\s+batao|\s+do)?|video\s+explain\s+karo)\s+(.+)$", cleaned, re.I)
    if sum_m:
        from automation import summarize_youtube_video
        return summarize_youtube_video(url_or_name=sum_m.group(1).strip()).message

    # 12. YouTube Comments & Sentiment Analyzer
    com_m = re.search(r"\b(?:analyze\s+(?:the\s+)?(?:comments|comment\s+section)?|comments\s+(?:analyze\s*karo|dekho|padho)|log\s+kya\s+bol\s+rahe\s+hain\s+(?:is\s+video\s+par)?)\s+(.+)$", cleaned, re.I)
    if com_m:
        from automation import analyze_youtube_comments
        return analyze_youtube_comments(url_or_name=com_m.group(1).strip()).message

    # 13. YouTube Video Details
    det_m = re.search(r"\b(?:video\s+details|details\s+(?:of\s+)?video|video\s+metadata)\s+(.+)$", cleaned, re.I)
    if det_m:
        from automation import get_youtube_video_details
        return get_youtube_video_details(url_or_name=det_m.group(1).strip()).message

    return None
