"""Capture failure evidence (screenshot + trimmed DOM + URL) into the job's
downloads directory - the raw material for both AI healing and human triage.
The job directory is already kept on failure, so evidence survives the run.
"""

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_STRIP_BLOCKS_RE = re.compile(
    r"<(script|style|svg|noscript|link|meta)\b[^>]*>.*?</\1>|<(script|style|svg|noscript)\b[^>]*/>|<(link|meta)\b[^>]*>",
    re.IGNORECASE | re.DOTALL,
)
# Never send form input values (credentials, account numbers) to the API.
_INPUT_VALUE_RE = re.compile(r'(<(?:input|textarea)\b[^>]*?\bvalue=)(["\']).*?\2', re.IGNORECASE | re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s{2,}")


def trim_dom(html: str, max_chars: int = 60000) -> str:
    """Strip scripts/styles/svg, blank out input values, collapse whitespace,
    truncate. Keeps structure + attributes (ids, classes, aria, text) that the
    model needs to propose a locator."""
    if not html:
        return ""
    trimmed = _STRIP_BLOCKS_RE.sub("", html)
    trimmed = _INPUT_VALUE_RE.sub(r'\1""', trimmed)
    trimmed = _WHITESPACE_RE.sub(" ", trimmed)
    if len(trimmed) > max_chars:
        trimmed = trimmed[:max_chars] + "\n<!-- truncated -->"
    return trimmed


@dataclass
class Evidence:
    url: str
    trimmed_dom: str
    screenshot_path: Optional[str]
    raw_dom_path: Optional[str]


def capture_evidence(page, out_dir: Optional[str], selector: str, dom_max_chars: int = 60000) -> Evidence:
    """Best-effort: evidence capture must never turn one failure into another."""
    url, html, screenshot_path, raw_dom_path = "", "", None, None
    try:
        url = page.url
    except Exception:
        pass
    try:
        html = page.content()
    except Exception:
        pass

    if out_dir:
        try:
            os.makedirs(out_dir, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            raw_dom_path = os.path.join(out_dir, f"healing_{stamp}_dom.html")
            with open(raw_dom_path, "w", encoding="utf-8") as f:
                f.write(f"<!-- url: {url} -->\n<!-- failed selector: {selector} -->\n{html}")
            screenshot_path = os.path.join(out_dir, f"healing_{stamp}.png")
            page.screenshot(path=screenshot_path)
        except Exception as exc:
            logger.warning(f"Evidence capture partial failure (continuing): {exc}")
            if screenshot_path and not os.path.exists(screenshot_path):
                screenshot_path = None

    return Evidence(
        url=url,
        trimmed_dom=trim_dom(html, dom_max_chars),
        screenshot_path=screenshot_path,
        raw_dom_path=raw_dom_path,
    )
