"""Unit tests for DarkShadow interactive automation, ordinal YouTube selection, and screen tools."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from automation import (
    AutomationContext,
    GLOBAL_AUTOMATION_CONTEXT,
    extract_youtube_search_results,
    parse_ordinal_selection,
    play_youtube,
    search_youtube,
    analyze_screen_content,
    search_product_prices,
)
from natural_automation import handle_natural_automation


def test_parse_ordinal_selection():
    """Verify that natural language ordinals map to correct 1-based indices."""
    assert parse_ordinal_selection("2nd wala chala do") == 2
    assert parse_ordinal_selection("second wala play karo") == 2
    assert parse_ordinal_selection("doosra gana bajao") == 2
    assert parse_ordinal_selection("3rd wala play kar do") == 3
    assert parse_ordinal_selection("teesra song chalao") == 3
    assert parse_ordinal_selection("pehla wala bajao") == 1
    assert parse_ordinal_selection("1st video") == 1
    assert parse_ordinal_selection("4th option") == 4
    assert parse_ordinal_selection("chautha gana") == 4
    assert parse_ordinal_selection("5th track") == 5
    assert parse_ordinal_selection("paanchwa") == 5
    assert parse_ordinal_selection("last wala chalao") == -1
    assert parse_ordinal_selection("aakhri option") == -1

    # Non-ordinal queries should return None
    assert parse_ordinal_selection("Arijit Singh song") is None
    assert parse_ordinal_selection("Kesariya play karo") is None


def test_automation_context_search_results():
    """Verify storing and retrieving indexed search results."""
    ctx = AutomationContext()
    dummy_results = [
        {"id": "vid1", "title": "First Song", "url": "https://www.youtube.com/watch?v=vid1"},
        {"id": "vid2", "title": "Second Song", "url": "https://www.youtube.com/watch?v=vid2"},
        {"id": "vid3", "title": "Third Song", "url": "https://www.youtube.com/watch?v=vid3"},
    ]
    ctx.remember_search_results("test query", dummy_results)

    assert ctx.last_search_query == "test query"
    assert ctx.get_search_result_by_index(1)["id"] == "vid1"
    assert ctx.get_search_result_by_index(2)["id"] == "vid2"
    assert ctx.get_search_result_by_index(3)["id"] == "vid3"
    assert ctx.get_search_result_by_index(-1)["id"] == "vid3"
    assert ctx.get_search_result_by_index(99) is None


def test_play_youtube_ordinal_selection():
    """Verify play_youtube resolves ordinal requests from context."""
    ctx = AutomationContext()
    dummy_results = [
        {"id": "vid1", "title": "Arijit Hit 1", "url": "https://www.youtube.com/watch?v=vid1"},
        {"id": "vid2", "title": "Arijit Hit 2", "url": "https://www.youtube.com/watch?v=vid2"},
    ]
    ctx.remember_search_results("Arijit Singh", dummy_results)

    with patch("automation._open_browser_url") as mock_open:
        mock_open.return_value = MagicMock(success=True)
        res = play_youtube("2nd wala chala do", context=ctx)
        assert res.success is True
        assert res.data.get("from_search_results") is True
        assert res.data.get("index") == 2
        assert res.data.get("selected_video")["id"] == "vid2"
        mock_open.assert_called_once_with(
            "play_youtube",
            "https://www.youtube.com/watch?v=vid2&autoplay=1",
            "YouTube par song chala diya: Arijit Hit 2",
        )


def test_natural_automation_ordinal_playback():
    """Verify handle_natural_automation intercepts ordinal playback."""
    GLOBAL_AUTOMATION_CONTEXT.remember_search_results(
        "romantic hits",
        [
            {"id": "vid11", "title": "Song One", "url": "https://www.youtube.com/watch?v=vid11"},
            {"id": "vid22", "title": "Song Two", "url": "https://www.youtube.com/watch?v=vid22"},
        ],
    )

    with patch("automation._open_browser_url") as mock_open:
        mock_open.return_value = MagicMock(success=True)
        resp = handle_natural_automation("2nd wala chala do")
        assert resp is not None
        assert "2" in resp or "Song Two" in resp


def test_youtube_search_extraction_format():
    """Verify extract_youtube_search_results returns structured list without crashing."""
    results = extract_youtube_search_results("Arijit Singh", max_results=3)
    assert isinstance(results, list)
    for item in results:
        assert "id" in item
        assert "title" in item
        assert "url" in item


def test_product_price_search():
    """Verify product price search handles query and fallback gracefully."""
    with patch("automation._open_browser_url") as mock_open:
        mock_open.return_value = MagicMock(success=True)
        res = search_product_prices("iPhone 15")
        assert res.success is True
        assert "iPhone 15" in res.data.get("query", "")


def test_scroll_screen_and_natural_trigger():
    """Verify scroll_screen and natural scroll triggers."""
    from automation import scroll_screen

    with patch("pyautogui.scroll") as mock_scroll:
        res = scroll_screen(direction="down", amount=5)
        assert res.success is True
        assert res.data["direction"] == "down"
        mock_scroll.assert_called_once_with(-600)

    with patch("pyautogui.scroll") as mock_scroll:
        msg = handle_natural_automation("thoda neeche scroll karo")
        assert msg is not None
        assert "scroll" in msg.lower()


def test_click_screen_element():
    """Verify click_screen_element calculates target positions."""
    from automation import click_screen_element

    with patch("automation._focus_browser_window", return_value=True), \
         patch("pyautogui.size", return_value=(1920, 1080)), \
         patch("pyautogui.moveTo") as mock_move, \
         patch("pyautogui.click") as mock_click:
        res = click_screen_element(target="first_link", x=500, y=400)
        assert res.success is True
        assert res.data["target"] == "first_link"
        assert res.data["x"] == 500
        assert res.data["y"] == 400
        mock_click.assert_called()


def test_control_browser_action():
    """Verify browser navigation triggers appropriate shortcuts."""
    from automation import control_browser_action

    with patch("pyautogui.hotkey") as mock_hotkey, patch("pyautogui.press") as mock_press:
        res_back = control_browser_action(action="back")
        assert res_back.success is True
        mock_hotkey.assert_called_with("alt", "left")

        res_refresh = control_browser_action(action="refresh")
        assert res_refresh.success is True
        mock_press.assert_called_with("f5")


def test_enhance_youtube_music_query_preserves_specific_titles():
    """Verify specific songs with words like 'dil', 'love', 'sad' are NOT replaced with generic playlists."""
    from automation import _enhance_youtube_music_query

    # Specific song titles must NOT be transformed into generic playlists
    res1 = _enhance_youtube_music_query("Dil Chahte Ho")
    assert "dil chahte ho" in res1.lower()
    assert "best hindi romantic" not in res1.lower()

    res2 = _enhance_youtube_music_query("Dil Chahte Ho Jubin Nautiyal Mandy Takhar Payal Dev Official")
    assert "dil chahte ho" in res2.lower()
    assert "best hindi romantic" not in res2.lower()

    # Generic mood queries SHOULD be enhanced
    res_generic = _enhance_youtube_music_query("koi romantic gana")
    assert "Best Hindi Romantic Songs" in res_generic


if __name__ == "__main__":
    print("Running test_parse_ordinal_selection...")
    test_parse_ordinal_selection()
    print("PASSED")

    print("Running test_automation_context_search_results...")
    test_automation_context_search_results()
    print("PASSED")

    print("Running test_play_youtube_ordinal_selection...")
    test_play_youtube_ordinal_selection()
    print("PASSED")

    print("Running test_natural_automation_ordinal_playback...")
    test_natural_automation_ordinal_playback()
    print("PASSED")

    print("Running test_youtube_search_extraction_format...")
    test_youtube_search_extraction_format()
    print("PASSED")

    print("Running test_product_price_search...")
    test_product_price_search()
    print("PASSED")

    print("Running test_scroll_screen_and_natural_trigger...")
    test_scroll_screen_and_natural_trigger()
    print("PASSED")

    print("Running test_click_screen_element...")
    test_click_screen_element()
    print("PASSED")

    print("Running test_control_browser_action...")
    test_control_browser_action()
    print("PASSED")

    print("Running test_enhance_youtube_music_query_preserves_specific_titles...")
    test_enhance_youtube_music_query_preserves_specific_titles()
    print("PASSED")

    print("\nALL INTERACTIVE AUTOMATION TESTS PASSED! [OK]")

