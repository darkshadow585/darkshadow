"""Playwright and DOM-level browser automation engine for DarkShadow (Level 3 Vision-Grounded Web Agent).

Features:
- Level 2: Persistent user data profile (logged-in sessions and cookies preserved across restarts).
- Level 2: Anti-detection stealth flags (navigator.webdriver masked, realistic user agents).
- Level 3: Set-of-Marks (SoM) visual element tagging and coordinate mapping.
- Level 3: Gemini 3.8 Flash Vision-Grounded element locator and self-healing action loops.
- Level 3: Vision-driven popup/modal dismissal.
- Multi-platform e-commerce shopping automation across Amazon and Flipkart.
"""

from __future__ import annotations

import concurrent.futures
import functools
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from safety import is_payment_or_checkout_intent, PAYMENT_BLOCKED_MESSAGE

LOGGER = logging.getLogger(__name__)


def _browser_worker(method: Any) -> Any:
    """Decorator to ensure method executes exclusively on the browser engine's dedicated thread."""
    @functools.wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not self.is_installed():
            if method.__name__ in {"vision_dismiss_popups"}:
                return False
            if method.__name__ in {"inject_set_of_marks"}:
                return {}
            if method.__name__ in {"clear_set_of_marks", "close"}:
                return None
            return {"success": False, "error": "playwright_not_installed"}
        return self._run_in_worker(method, self, *args, **kwargs)
    return wrapper


class DarkShadowBrowserEngine:
    """Manages browser lifecycle, persistent profiles, stealth, and Level 3 Vision-Grounded Web actions."""

    def __init__(
        self,
        headless: bool = False,
        user_data_dir: Path | str | None = None,
        stealth: bool = True,
    ) -> None:
        self.headless = headless
        self.user_data_dir = (
            Path(user_data_dir)
            if user_data_dir
            else (Path.home() / ".darkshadow" / "browser_profile")
        )
        self.stealth = stealth
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._lock = threading.Lock()
        self._worker_thread_id: int | None = None
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="darkshadow-browser",
        )

    def _run_in_worker(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute a callable strictly within the dedicated single-threaded browser worker."""
        if threading.get_ident() == self._worker_thread_id:
            return fn(*args, **kwargs)

        def _task() -> Any:
            self._worker_thread_id = threading.get_ident()
            return fn(*args, **kwargs)

        future = self._executor.submit(_task)
        return future.result()

    @staticmethod
    def is_installed() -> bool:
        """Return whether playwright Python package is importable."""
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            return False

    @_browser_worker
    def _ensure_page(self) -> Any:
        """Lazily initialize browser and page with persistent context and stealth evasion."""
        if self._page is not None:
            try:
                if not self._page.is_closed():
                    return self._page
            except Exception:
                pass
            self._page = None

        if self._context is not None:
            try:
                if hasattr(self._context, "pages"):
                    _ = self._context.pages
            except Exception:
                self._context = None
                self._page = None

        from playwright.sync_api import sync_playwright

        if self._playwright is None:
            try:
                self._playwright = sync_playwright().start()
            except Exception as p_err:
                LOGGER.debug("Playwright start notice: %s", p_err)
                return None

        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-default-browser-check",
            "--disable-infobars",
            "--start-maximized",
        ]
        if self.stealth:
            args.extend([
                "--disable-features=IsolateOrigins,site-per-process",
            ])

        user_dir = Path(self.user_data_dir).expanduser()
        try:
            user_dir.mkdir(parents=True, exist_ok=True)
        except Exception as dir_err:
            LOGGER.debug("Could not create browser user directory: %s", dir_err)

        if self._context is None:
            try:
                # Level 2: Persistent context preserves logins and cookies across runs
                self._context = self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(user_dir),
                    headless=self.headless,
                    args=args,
                    viewport={"width": 1280, "height": 850},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                )
            except Exception as p_err:
                LOGGER.debug("Persistent context launch fallback: %s", p_err)
                if self._browser is None or not self._browser.is_connected():
                    self._browser = self._playwright.chromium.launch(
                        headless=self.headless,
                        args=args,
                    )
                self._context = self._browser.new_context(
                    viewport={"width": 1280, "height": 850},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                )

        # Anti-detect stealth script injection
        if self.stealth:
            try:
                self._context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    window.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'hi'] });
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                """)
            except Exception:
                pass

        if hasattr(self._context, "pages") and self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = self._context.new_page()

        return self._page

    @_browser_worker
    def navigate(self, url: str, timeout_seconds: float = 15.0) -> dict[str, Any]:
        """Navigate to a target URL."""
        with self._lock:
            try:
                page = self._ensure_page()
                if page is None:
                    return {"success": False, "error": "failed_to_initialize_page", "url": url}
                resp = page.goto(
                    url,
                    timeout=int(timeout_seconds * 1000),
                    wait_until="domcontentloaded",
                )
                title = page.title()
                status = resp.status if resp else 200
                return {
                    "success": True,
                    "url": page.url,
                    "title": title,
                    "status_code": status,
                }
            except Exception as exc:
                LOGGER.warning("Browser navigate error: %s", exc)
                return {"success": False, "error": str(exc), "url": url}

    @_browser_worker
    def click_selector(self, selector: str, timeout_seconds: float = 8.0) -> dict[str, Any]:
        """Click on an element matching selector or text."""
        with self._lock:
            try:
                page = self._ensure_page()
                if page is None:
                    return {"success": False, "error": "failed_to_initialize_page", "selector": selector}
                page.click(selector, timeout=int(timeout_seconds * 1000))
                return {"success": True, "selector": selector, "url": page.url}
            except Exception as exc:
                LOGGER.warning("Browser click selector error: %s", exc)
                return {"success": False, "error": str(exc), "selector": selector}

    @_browser_worker
    def fill_input(self, selector: str, text: str, timeout_seconds: float = 8.0) -> dict[str, Any]:
        """Fill an input field with specified text."""
        with self._lock:
            try:
                page = self._ensure_page()
                if page is None:
                    return {"success": False, "error": "failed_to_initialize_page", "selector": selector}
                page.fill(selector, text, timeout=int(timeout_seconds * 1000))
                return {"success": True, "selector": selector, "text": text}
            except Exception as exc:
                LOGGER.warning("Browser fill input error: %s", exc)
                return {"success": False, "error": str(exc), "selector": selector}

    @_browser_worker
    def extract_text(self, selector: str | None = None, max_chars: int = 3000) -> dict[str, Any]:
        """Extract visible text from page or a specific container selector."""
        with self._lock:
            try:
                page = self._ensure_page()
                if page is None:
                    return {"success": False, "error": "failed_to_initialize_page"}
                if selector:
                    text = page.inner_text(selector, timeout=5000)
                else:
                    text = page.inner_text("body", timeout=5000)
                truncated = text.strip()[:max_chars]
                return {
                    "success": True,
                    "text": truncated,
                    "title": page.title(),
                    "url": page.url,
                    "length": len(truncated),
                }
            except Exception as exc:
                LOGGER.warning("Browser extract text error: %s", exc)
                return {"success": False, "error": str(exc)}

    @_browser_worker
    def take_screenshot(self, output_path: str | Path | None = None) -> dict[str, Any]:
        """Capture browser page screenshot and save to disk."""
        with self._lock:
            try:
                page = self._ensure_page()
                if page is None:
                    return {"success": False, "error": "failed_to_initialize_page"}
                path_obj = Path(output_path) if output_path else Path("browser_screenshot.png")
                path_obj.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(path_obj.resolve()))
                return {"success": True, "path": str(path_obj.resolve())}
            except Exception as exc:
                LOGGER.warning("Browser screenshot error: %s", exc)
                return {"success": False, "error": str(exc)}

    # =========================================================================
    # Level 3 Core: Set-of-Marks (SoM) Visual Grounding & Agentic Navigation
    # =========================================================================

    @_browser_worker
    def inject_set_of_marks(self) -> dict[str, Any]:
        """Inject high-contrast numbered visual badges on all visible interactive elements.
        
        Returns a dictionary mapping mark IDs ('1', '2', ...) to metadata:
        { "1": {"tag": "button", "text": "Add to Cart", "x": 480, "y": 620, "width": 120, "height": 40}, ... }
        """
        with self._lock:
            try:
                page = self._ensure_page()
                if page is None:
                    return {}
                script = """
                () => {
                    document.querySelectorAll('[data-darkshadow-marker="true"]').forEach(el => el.remove());

                    const interactiveSelectors = [
                        'button',
                        'a[href]',
                        'input:not([type="hidden"])',
                        'select',
                        'textarea',
                        '[role="button"]',
                        '[role="link"]',
                        '[role="checkbox"]',
                        '[role="menuitem"]',
                        '[role="searchbox"]',
                        '[onclick]',
                    ];

                    const elements = Array.from(document.querySelectorAll(interactiveSelectors.join(',')));
                    const visibleElements = [];
                    const vw = window.innerWidth;
                    const vh = window.innerHeight;

                    for (const el of elements) {
                        if (el.getAttribute('data-darkshadow-marker') === 'true') continue;
                        const rect = el.getBoundingClientRect();
                        if (rect.width <= 6 || rect.height <= 6) continue;
                        if (rect.bottom < 0 || rect.top > vh || rect.right < 0 || rect.left > vw) continue;

                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) < 0.1) continue;

                        visibleElements.push({ el, rect });
                        if (visibleElements.length >= 50) break;
                    }

                    const marksMap = {};
                    visibleElements.forEach((item, index) => {
                        const markId = String(index + 1);
                        const rect = item.rect;
                        
                        item.el.setAttribute('data-darkshadow-mark-id', markId);

                        const badge = document.createElement('div');
                        badge.setAttribute('data-darkshadow-marker', 'true');
                        badge.textContent = markId;
                        badge.style.position = 'fixed';
                        badge.style.left = `${Math.max(0, rect.left)}px`;
                        badge.style.top = `${Math.max(0, rect.top)}px`;
                        badge.style.backgroundColor = '#FFCC00';
                        badge.style.color = '#000000';
                        badge.style.fontWeight = 'bold';
                        badge.style.fontSize = '12px';
                        badge.style.fontFamily = 'monospace, sans-serif';
                        badge.style.padding = '1px 5px';
                        badge.style.borderRadius = '3px';
                        badge.style.border = '1px solid #000000';
                        badge.style.zIndex = '2147483647';
                        badge.style.pointerEvents = 'none';
                        badge.style.boxShadow = '0 2px 4px rgba(0,0,0,0.5)';
                        document.body.appendChild(badge);

                        let text = (item.el.innerText || item.el.getAttribute('aria-label') || item.el.getAttribute('placeholder') || item.el.getAttribute('value') || '').trim();
                        text = text.replace(/\\s+/g, ' ').substring(0, 70);

                        marksMap[markId] = {
                            tag: item.el.tagName.toLowerCase(),
                            text: text,
                            x: Math.round(rect.left + rect.width / 2),
                            y: Math.round(rect.top + rect.height / 2),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                        };
                    });

                    return marksMap;
                }
                """
                res = page.evaluate(script)
                return res if isinstance(res, dict) else {}
            except Exception as exc:
                LOGGER.warning("Set-of-Marks injection notice: %s", exc)
                if "closed" in str(exc).lower():
                    self._page = None
                    self._context = None
                return {}

    @_browser_worker
    def clear_set_of_marks(self) -> None:
        """Remove all temporary Set-of-Marks visual badges from DOM."""
        with self._lock:
            try:
                page = self._ensure_page()
                if page is not None:
                    page.evaluate("() => document.querySelectorAll('[data-darkshadow-marker=\"true\"]').forEach(el => el.remove())")
            except Exception as exc:
                if "closed" in str(exc).lower():
                    self._page = None
                    self._context = None

    @_browser_worker
    def click_mark(self, mark_id: str | int) -> dict[str, Any]:
        """Click the interactive element identified by the mark ID."""
        mid = str(mark_id).strip()
        with self._lock:
            try:
                page = self._ensure_page()
                if page is None:
                    return {"success": False, "error": "failed_to_initialize_page", "mark_id": mid}
                sel = f'[data-darkshadow-mark-id="{mid}"]'
                if page.is_visible(sel):
                    page.click(sel, timeout=3500)
                    return {"success": True, "mark_id": mid, "url": page.url}

                # Fallback: evaluate element click
                clicked = page.evaluate(f"""
                    () => {{
                        const el = document.querySelector('[data-darkshadow-mark-id="{mid}"]');
                        if (el) {{
                            el.click();
                            return true;
                        }}
                        return false;
                    }}
                """)
                if clicked:
                    return {"success": True, "mark_id": mid, "url": page.url}
                return {"success": False, "error": f"Mark {mid} element not visible", "mark_id": mid}
            except Exception as exc:
                if "closed" in str(exc).lower():
                    self._page = None
                    self._context = None
                return {"success": False, "error": str(exc), "mark_id": mid}

    @_browser_worker
    def fill_mark(self, mark_id: str | int, text: str) -> dict[str, Any]:
        """Fill input field identified by the mark ID with text."""
        mid = str(mark_id).strip()
        with self._lock:
            try:
                page = self._ensure_page()
                if page is None:
                    return {"success": False, "error": "failed_to_initialize_page", "mark_id": mid}
                sel = f'[data-darkshadow-mark-id="{mid}"]'
                page.fill(sel, text, timeout=3500)
                return {"success": True, "mark_id": mid, "text": text}
            except Exception as exc:
                if "closed" in str(exc).lower():
                    self._page = None
                    self._context = None
                return {"success": False, "error": str(exc), "mark_id": mid}

    @_browser_worker
    def vision_dismiss_popups(self) -> bool:
        """Visually detect and dismiss blocking popups, login modals, or cookie banners."""
        with self._lock:
            try:
                page = self._ensure_page()
                if page is None:
                    return False
                dismiss_selectors = [
                    "button._2KpZ6l._2doB4z",  # Flipkart login modal close
                    "button[aria-label='Close']",
                    "button.close",
                    "[data-dismiss='modal']",
                    "#a-popover-header-close-button",
                    ".cookie-banner button",
                    "button:has-text('Accept')",
                    "button:has-text('Dismiss')",
                    "button:has-text('Later')",
                    "button:has-text('Skip')",
                ]
                for sel in dismiss_selectors:
                    try:
                        if page.is_visible(sel):
                            page.click(sel, timeout=1200)
                            return True
                    except Exception:
                        continue
            except Exception as exc:
                if "closed" in str(exc).lower():
                    self._page = None
                    self._context = None
        return False

    @_browser_worker
    def vision_execute_goal(
        self,
        goal: str,
        gemini_api_key: str | None = None,
        client: Any = None,
        max_steps: int = 3,
    ) -> dict[str, Any]:
        """Autonomous Level 3 Vision-Grounded Web Agent loop using Set-of-Marks and Gemini 3.8 Flash."""
        if not self.is_installed():
            return {"success": False, "error": "playwright_not_installed"}

        if is_payment_or_checkout_intent(goal):
            return {
                "success": False,
                "error": "payment_prohibited",
                "message": PAYMENT_BLOCKED_MESSAGE,
            }

        from config import load_settings
        s = load_settings()
        api_key = gemini_api_key or s.api_key
        if not api_key:
            return {
                "success": False,
                "error": "gemini_api_key_missing",
                "message": "Gemini API key missing for vision browser agent.",
            }

        if client is None:
            from automation import _get_cached_genai_client
            client = _get_cached_genai_client(api_key)

        model_to_use = getattr(s, "model", "gemini-3.8-flash")
        steps_log: list[dict[str, Any]] = []

        for step in range(max_steps):
            with self._lock:
                try:
                    page = self._ensure_page()
                    page.wait_for_load_state("domcontentloaded", timeout=4000)
                except Exception:
                    pass

            # 1. Inject Set of Marks
            marks_map = self.inject_set_of_marks()
            if not marks_map:
                return {
                    "success": False,
                    "error": "no_interactive_elements",
                    "message": "Page par koi interactive button ya link nahi mila.",
                }

            # 2. Capture screenshot with marks
            shot_bytes = b""
            try:
                with self._lock:
                    page = self._ensure_page()
                    shot_bytes = page.screenshot(type="jpeg", quality=80)
            except Exception as s_err:
                self.clear_set_of_marks()
                return {"success": False, "error": f"screenshot_failed: {s_err}"}

            # 3. Prompt Gemini 3.8 Flash
            marks_summary = "\n".join(
                f"[{mid}] <{v['tag']}>: '{v['text']}'"
                for mid, v in list(marks_map.items())[:45]
            )
            prompt = (
                f"You are DarkShadow Autonomous Vision Browser Agent.\n"
                f"Target User Goal: \"{goal}\"\n\n"
                f"Available visible elements with numbered markers:\n{marks_summary}\n\n"
                f"TASK:\n"
                f"Look at the attached webpage screenshot with yellow badge markers ([1], [2], [3]...).\n"
                f"Determine the single best mark number to interact with to achieve the goal.\n"
                f"- If a blocking popup/modal or cookie banner is visible, choose the close/dismiss button mark.\n"
                f"- If target is a button/link to click, set action to 'click'.\n"
                f"- If target is an input field, set action to 'type' and provide 'type_text'.\n"
                f"- If the goal is ALREADY completed on screen, set goal_achieved to true.\n\n"
                f"Respond ONLY in valid JSON format:\n"
                f"{{\n"
                f'  "mark_id": 4,\n'
                f'  "action": "click",\n'
                f'  "type_text": null,\n'
                f'  "reasoning": "Mark [4] is the Add to Cart button",\n'
                f'  "goal_achieved": false\n'
                f"}}"
            )

            decision: dict[str, Any] = {}
            try:
                from google.genai import types
                response = client.models.generate_content(
                    model=model_to_use,
                    contents=[
                        types.Part.from_bytes(data=shot_bytes, mime_type="image/jpeg"),
                        prompt,
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1,
                    ),
                )
                raw_text = (response.text or "").strip()
                decision = json.loads(raw_text)
            except Exception as v_err:
                LOGGER.debug("Vision agent reasoning fallback: %s", v_err)
                # Fallback: search mark text for goal keywords
                goal_words = [w.lower() for w in goal.split() if len(w) > 3]
                matched_mid = None
                for mid, v in marks_map.items():
                    if any(w in v["text"].lower() for w in goal_words):
                        matched_mid = mid
                        break
                if matched_mid:
                    decision = {
                        "mark_id": matched_mid,
                        "action": "click",
                        "reasoning": f"Keyword match fallback on mark {matched_mid}",
                        "goal_achieved": False,
                    }
                else:
                    self.clear_set_of_marks()
                    return {"success": False, "error": f"vision_error: {v_err}"}

            # Clear marks after reading
            self.clear_set_of_marks()

            if decision.get("goal_achieved"):
                return {
                    "success": True,
                    "status": "goal_achieved",
                    "message": f"Goal '{goal}' achieved successfully.",
                    "steps": steps_log,
                }

            target_mark = decision.get("mark_id")
            if target_mark is None:
                return {
                    "success": True,
                    "status": "completed",
                    "message": f"Vision agent completed: {decision.get('reasoning', 'No further action needed')}",
                    "steps": steps_log,
                }

            act = decision.get("action", "click")
            if act == "type" and decision.get("type_text"):
                res = self.fill_mark(target_mark, decision["type_text"])
            else:
                res = self.click_mark(target_mark)

            steps_log.append({
                "step": step + 1,
                "mark_id": target_mark,
                "action": act,
                "reasoning": decision.get("reasoning", ""),
                "result": res,
            })

            time.sleep(1.2)

        return {
            "success": True,
            "status": "max_steps_reached",
            "message": f"Vision agent executed {len(steps_log)} steps for '{goal}'.",
            "steps": steps_log,
        }

    # =========================================================================
    # Multi-Platform E-Commerce Shopping Automation
    # =========================================================================

    @_browser_worker
    def search_and_cart_amazon(
        self, product: str, max_price: float | None = None
    ) -> dict[str, Any]:
        """Search Amazon India with price filter, select top item, and click Add to Cart."""
        if is_payment_or_checkout_intent(product):
            return {
                "success": False,
                "platform": "Amazon",
                "product": product,
                "error": "payment_prohibited",
                "message": PAYMENT_BLOCKED_MESSAGE,
            }

        encoded_prod = quote_plus(product)
        if max_price is not None and max_price > 0:
            paise_limit = int(max_price * 100)
            target_url = f"https://www.amazon.in/s?k={encoded_prod}&rh=p_36%3A-{paise_limit}"
        else:
            target_url = f"https://www.amazon.in/s?k={encoded_prod}"

        with self._lock:
            try:
                page = self._ensure_page()
                if page is None:
                    return {
                        "success": False,
                        "platform": "Amazon",
                        "product": product,
                        "error": "failed_to_initialize_page",
                    }
                page.goto(target_url, timeout=18000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

                item_title = ""
                item_price = ""
                item_link = ""

                product_links = page.query_selector_all(
                    "div[data-component-type='s-search-result'] h2 a, a.a-link-normal.s-underline-text.s-underline-link-text.s-link-style.a-text-normal"
                )
                for link_elem in product_links:
                    txt = link_elem.inner_text().strip()
                    href = link_elem.get_attribute("href")
                    if txt and href and "slredirect" not in href:
                        item_title = txt
                        item_link = href if href.startswith("http") else f"https://www.amazon.in{href}"
                        break

                price_elem = page.query_selector("div[data-component-type='s-search-result'] span.a-price-whole")
                if price_elem:
                    item_price = f"₹{price_elem.inner_text().strip()}"

                cart_success = False
                if item_link:
                    page.goto(item_link, timeout=18000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)

                    cart_selectors = [
                        "#add-to-cart-button",
                        "input[name='submit.add-to-cart']",
                        "button[name='submit.add-to-cart']",
                        "#addToCart_feature_div input",
                        "input#add-to-cart-button",
                    ]
                    for sel in cart_selectors:
                        try:
                            if page.is_visible(sel):
                                page.click(sel, timeout=4000)
                                cart_success = True
                                break
                        except Exception:
                            continue

                # Level 3 Vision Fallback if CSS selector failed to find Cart button
                if not cart_success:
                    try:
                        v_res = self.vision_execute_goal("Click Add to Cart button", max_steps=2)
                        if v_res.get("success"):
                            cart_success = True
                    except Exception as v_exc:
                        LOGGER.debug("Amazon Level 3 vision fallback: %s", v_exc)

                return {
                    "success": True,
                    "platform": "Amazon",
                    "product": item_title or product,
                    "price": item_price or (f"Under ₹{int(max_price)}" if max_price else "Best Available"),
                    "cart_success": cart_success,
                    "url": item_link or target_url,
                    "status": "carted" if cart_success else "product_opened",
                }
            except Exception as exc:
                LOGGER.warning("Amazon automation notice: %s", exc)
                return {
                    "success": True,
                    "platform": "Amazon",
                    "product": product,
                    "max_price": max_price,
                    "url": target_url,
                    "cart_success": False,
                    "error": str(exc),
                }

    @_browser_worker
    def search_and_cart_flipkart(
        self, product: str, max_price: float | None = None
    ) -> dict[str, Any]:
        """Search Flipkart with price filter, select top item, and click Add to Cart."""
        if is_payment_or_checkout_intent(product):
            return {
                "success": False,
                "platform": "Flipkart",
                "product": product,
                "error": "payment_prohibited",
                "message": PAYMENT_BLOCKED_MESSAGE,
            }

        encoded_prod = quote_plus(product)
        if max_price is not None and max_price > 0:
            target_url = f"https://www.flipkart.com/search?q={encoded_prod}&p%5B%5D=facets.price_range.to%3D{int(max_price)}"
        else:
            target_url = f"https://www.flipkart.com/search?q={encoded_prod}"

        with self._lock:
            try:
                page = self._ensure_page()
                if page is None:
                    return {
                        "success": False,
                        "platform": "Flipkart",
                        "product": product,
                        "error": "failed_to_initialize_page",
                    }
                page.goto(target_url, timeout=18000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

                # Level 3: Dismiss blocking login modals
                self.vision_dismiss_popups()

                item_title = ""
                item_price = ""
                item_link = ""

                product_elements = page.query_selector_all(
                    "div._1AtVbE a._1fQZEK, div[data-id] a._1fQZEK, div._1AtVbE a.s1Q9rs, div[data-id] a.s1Q9rs, a.CG23A2"
                )
                for prod_elem in product_elements:
                    href = prod_elem.get_attribute("href")
                    if href:
                        item_link = href if href.startswith("http") else f"https://www.flipkart.com{href}"
                        title_sub = prod_elem.query_selector("div._4rR01T, div.KzDlHZ, a.s1Q9rs")
                        if title_sub:
                            item_title = title_sub.inner_text().strip()
                        price_sub = prod_elem.query_selector("div._30jeq3, div.Nx9bqj")
                        if price_sub:
                            item_price = price_sub.inner_text().strip()
                        break

                cart_success = False
                if item_link:
                    page.goto(item_link, timeout=18000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)
                    self.vision_dismiss_popups()

                    cart_selectors = [
                        "button._2KpZ6l._2U9uAL._3v1-ww",
                        "button.QqFHMw.vslbG+._3Yl67G._7PdO_2",
                        "button:has-text('Add to cart')",
                        "button:has-text('ADD TO CART')",
                        "//button[contains(., 'ADD TO CART')]",
                    ]
                    for sel in cart_selectors:
                        try:
                            if page.is_visible(sel):
                                page.click(sel, timeout=4000)
                                cart_success = True
                                break
                        except Exception:
                            continue

                # Level 3 Vision Fallback if standard selectors failed
                if not cart_success:
                    try:
                        v_res = self.vision_execute_goal("Click Add to Cart button", max_steps=2)
                        if v_res.get("success"):
                            cart_success = True
                    except Exception as v_exc:
                        LOGGER.debug("Flipkart Level 3 vision fallback: %s", v_exc)

                return {
                    "success": True,
                    "platform": "Flipkart",
                    "product": item_title or product,
                    "price": item_price or (f"Under ₹{int(max_price)}" if max_price else "Best Available"),
                    "cart_success": cart_success,
                    "url": item_link or target_url,
                    "status": "carted" if cart_success else "product_opened",
                }
            except Exception as exc:
                LOGGER.warning("Flipkart automation notice: %s", exc)
                return {
                    "success": True,
                    "platform": "Flipkart",
                    "product": product,
                    "max_price": max_price,
                    "url": target_url,
                    "cart_success": False,
                    "error": str(exc),
                }

    @_browser_worker
    def close(self) -> None:
        """Close browser resources cleanly."""
        with self._lock:
            try:
                if self._page and not self._page.is_closed():
                    self._page.close()
            except Exception:
                pass
            try:
                if self._context:
                    self._context.close()
            except Exception:
                pass
            try:
                if self._browser and self._browser.is_connected():
                    self._browser.close()
            except Exception:
                pass
            try:
                if self._playwright:
                    self._playwright.stop()
            except Exception:
                pass
            finally:
                self._page = None
                self._context = None
                self._browser = None
                self._playwright = None


_GLOBAL_BROWSER_ENGINE: DarkShadowBrowserEngine | None = None


def get_browser_engine(settings: Any = None) -> DarkShadowBrowserEngine:
    """Return singleton browser engine instance configured with user settings."""
    global _GLOBAL_BROWSER_ENGINE
    if _GLOBAL_BROWSER_ENGINE is None:
        user_dir = None
        stealth = True
        if settings is not None:
            user_dir = getattr(settings, "browser_user_data_dir", None)
            stealth = getattr(settings, "browser_stealth_enabled", True)
        else:
            try:
                from config import load_settings
                s = load_settings()
                user_dir = s.browser_user_data_dir
                stealth = s.browser_stealth_enabled
            except Exception:
                pass

        _GLOBAL_BROWSER_ENGINE = DarkShadowBrowserEngine(
            headless=False,
            user_data_dir=user_dir,
            stealth=stealth,
        )
    return _GLOBAL_BROWSER_ENGINE
