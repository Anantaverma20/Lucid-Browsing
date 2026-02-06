"""
Run a JavaScript automation script in a headless Chromium page at the given URL.
Used by the Executor agent to validate scripts on a real page.
Also provides get_page_dom_summary() so the Planner/Writer can see real page structure.
"""
import logging
from dataclasses import dataclass

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from backend import config
from backend.services.script_utils import strip_trailing_prose

logger = logging.getLogger(__name__)

# Prefix for infrastructure (non-script) failures so the route can show where to look.
HEADLESS_INFRA_ERROR_PREFIX = "Headless browser error:"

# Max chars for DOM summary so it fits in LLM context
PAGE_CONTEXT_MAX_CHARS = 6000

# Script run in the page to collect a compact DOM summary (selectors + short text).
# Dynamic and page-agnostic: semantic + common UI + all [id] so hide/remove works on any site.
# Only class names that are valid CSS identifiers are used (no Tailwind-style colons/brackets),
# so the Writer can safely use these strings in querySelector.
# Returns newline-separated lines: "tag#id.class \"text snippet\""
_DOM_SUMMARY_SCRIPT = """
() => {
  const lines = [];
  const maxLines = 150;
  const textLen = 50;
  const seen = new Set();
  const validClass = /^[a-zA-Z_][a-zA-Z0-9_-]*$/;
  const validId = /^[a-zA-Z_][a-zA-Z0-9_-]*$/;
  const add = (el) => {
    if (lines.length >= maxLines || !el || seen.has(el)) return;
    seen.add(el);
    const id = el.id && validId.test(el.id) ? '#' + el.id : '';
    let cls = '';
    if (typeof el.className === 'string' && el.className) {
      const safe = el.className.trim().split(/\\s+/).filter(c => validClass.test(c)).slice(0, 3);
      if (safe.length) cls = '.' + safe.join('.');
    }
    const tag = el.tagName ? el.tagName.toLowerCase() : '?';
    let text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, textLen);
    if (text) text = ' "' + text + '"';
    lines.push(tag + id + cls + text);
  };
  try {
    const semantic = 'section, article, aside, main, header, footer, nav, [role="region"], [role="complementary"], [role="main"], [role="banner"], [role="contentinfo"]';
    const commonUI = '[class*="card"], [class*="widget"], [class*="item"], [class*="block"], [class*="box"], [class*="panel"], [class*="container"], [class*="section"], .sidebar, .side-bar, .feed-item, .promo, .banner, [data-testid], [data-component]';
    const adsWeather = '[id*="ad"], [id*="Ad"], [class*="ad"], [class*="Ad"], [data-ad], .sponsored, [class*="sponsor"], [id*="banner"], [id*="weather"], [id*="Weather"], [class*="weather"], [class*="Weather"]';
    const youtube = 'ytd-rich-item-renderer, ytd-video-renderer, ytd-compact-video-renderer, ytd-grid-video-renderer';
    document.querySelectorAll([semantic, commonUI, adsWeather, youtube].join(', ')).forEach(add);
    document.querySelectorAll('[id]').forEach(el => add(el));
    return lines.join('\\n');
  } catch (e) {
    return 'Error: ' + (e.message || String(e)).slice(0, 200);
  }
}
"""


@dataclass
class HeadlessResult:
    success: bool
    error_message: str


async def run_script_in_headless_browser(url: str, script: str) -> HeadlessResult:
    """
    Open url in headless Chromium, run script in page context, then close.
    Returns HeadlessResult(success=True, error_message="") on success.
    Strips trailing LLM prose before eval to avoid TypeError: "" is not a function.
    """
    script = strip_trailing_prose(script or "")
    if not script:
        logger.info("[Headless] SKIP: empty script")
        return HeadlessResult(success=False, error_message="Empty script after stripping trailing prose.")
    timeout_ms = getattr(config, "HEADLESS_BROWSER_TIMEOUT_MS", 15000) or 15000
    logger.info("[Headless] Running url=%s script_len=%d timeout_ms=%s", url[:60], len(script), timeout_ms)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                # Pass script as argument and eval in page so multi-statement/empty-edge-case is safe
                await page.evaluate("(script) => { (0, eval)(script); }", script)
                logger.info("[Headless] RESULT success=True")
                return HeadlessResult(success=True, error_message="")
            finally:
                await browser.close()
    except PlaywrightTimeout as e:
        msg = f"Timeout: {e!s}"
        logger.warning("Headless browser timeout: %s", msg)
        return HeadlessResult(success=False, error_message=f"{HEADLESS_INFRA_ERROR_PREFIX} {msg[:450]} Check Playwright installation and Chromium.")
    except Exception as e:
        msg = str(e).strip()[:500]
        logger.exception("[Headless] RESULT success=False error=%s", msg[:200])
        return HeadlessResult(success=False, error_message=f"{HEADLESS_INFRA_ERROR_PREFIX} {msg[:450]} Check Playwright installation and Chromium.")


async def get_page_dom_summary(url: str) -> str:
    """
    Load the page in headless Chromium and extract a compact DOM summary (elements
    relevant for ads, sidebars, main content) so the Planner/Writer can use real
    selectors. Returns a string suitable for LLM context (truncated to PAGE_CONTEXT_MAX_CHARS).
    On failure returns empty string; the /automate route will then return an error
    and will not run the pipeline.
    """
    url = (url or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return ""
    timeout_ms = getattr(config, "HEADLESS_BROWSER_TIMEOUT_MS", 15000) or 15000
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                raw = await page.evaluate(_DOM_SUMMARY_SCRIPT)
                summary = (raw or "").strip()
                if len(summary) > PAGE_CONTEXT_MAX_CHARS:
                    summary = summary[: PAGE_CONTEXT_MAX_CHARS - 3].rstrip() + "..."
                return summary
            finally:
                await browser.close()
    except PlaywrightTimeout as e:
        logger.warning("Page context timeout for %s: %s", url[:50], e)
        return ""
    except Exception as e:
        logger.warning("Could not get page DOM summary: %s", e)
        return ""
