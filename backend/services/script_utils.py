"""
Shared helpers for automation script (JS) used by Validator and Executor.
"""
import re


def _strip_markdown_code_block(script: str) -> str:
    """Remove markdown code fences (e.g. ```js ... ```) so only raw JS remains."""
    script = (script or "").strip()
    # Match ```optional_lang\n...content...\n```
    match = re.search(r"^```(?:\w*)\s*\n(.*?)```\s*$", script, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Unclosed fence: take after first ```optional_lang\n
    if script.startswith("```"):
        first = script.find("\n")
        if first != -1:
            script = script[first + 1 :].strip()
    # Trailing closing fence only (e.g. LLM outputs code then ``` on last line)
    if script.endswith("```"):
        script = script[: script.rfind("```")].rstrip()
    return script


def strip_trailing_prose(script: str) -> str:
    """
    Remove markdown code blocks, then trailing LLM prose that causes TypeError: "" is not a function
    (e.g. '; understand', '; ""', '; ""()', '; done', or trailing lines that are just words/quotes).
    """
    script = _strip_markdown_code_block(script or "")
    script = (script or "").strip()
    if not script:
        return script
    # Trailing call of empty string / identifier that causes "" is not a function
    script = re.sub(r"\s*;\s*[\"']?\s*[\"']?\s*\(\s*\)\s*$", ";", script)
    script = re.sub(r"\s*[\"']\s*[\"']?\s*\(\s*\)\s*$", "", script)
    script = script.strip()
    if not script:
        return script
    # Same line: strip anything after last semicolon if it looks like prose (word or quoted string only)
    idx = script.rfind(";")
    if idx != -1:
        rest = script[idx + 1 :].strip()
        if rest and re.match(r"^([\"'].*[\"']|[a-zA-Z_][a-zA-Z0-9_]*)\s*;?\s*$", rest):
            script = script[: idx + 1].strip()
    # Trailing lines: drop lines that are only prose (single word, quoted string, or empty)
    lines = script.split("\n")
    while lines:
        last = lines[-1].strip().rstrip(";").strip()
        if not last or re.match(r"^[\"'].*[\"']$", last) or re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", last):
            lines.pop()
        else:
            break
    # Drop any line that looks like prose (natural language) to avoid "Unexpected identifier" in JS
    lines = [
        ln for ln in lines
        if not re.match(r"^\s*(You|We|I|The|To|Need|Note|Important|First|Then|Finally|Also|Alternatively)\s", ln, re.I)
        and not re.match(r"^\s*[A-Z][a-z]+\s+[a-z]+\s+[a-z]+", ln)
    ]
    script = "\n".join(lines).strip()
    if re.match(r"^[\s;]*$", script):
        return ""
    return script


def _get_selector(m: re.Match, script: str, end: int) -> str | None:
    """Extract selector from a match; support both '...' and \"...\" so selectors can contain the other quote."""
    g1, g2 = m.group(1), m.group(2) if m.lastindex >= 2 else None
    return (g1 or g2) if (g1 or g2) else None


def _uses_remove(script: str, start: int, limit: int = 200) -> bool:
    """True if .remove() appears in script within limit chars after start (e.g. forEach(...remove()))."""
    snippet = script[start : start + limit]
    return ".remove()" in snippet


def script_to_commands(script: str) -> list[dict]:
    """
    Extract a list of {type, selector?} or {type, x?, y?} from Writer-style JS
    so the extension can run them in ISOLATED world without eval/inline (CSP-safe).
    Handles querySelector/querySelectorAll with ' or " (selectors may contain the other quote),
    getElementById, and .remove() vs hide.
    """
    if not (script or "").strip():
        return []
    out: list[dict] = []
    # Selector pattern: single-quoted (may contain ") or double-quoted (may contain ')
    _q = r"(?:'([^']*)'|\"([^\"]*)\")"

    # querySelectorAll('sel') or querySelectorAll("sel") — hide or remove
    for m in re.finditer(
        r"document\.querySelectorAll\s*\(\s*" + _q + r"\s*\)",
        script,
        re.DOTALL,
    ):
        sel = _get_selector(m, script, m.end())
        if sel:
            action = "remove" if _uses_remove(script, m.end()) else "hide"
            out.append({"type": action, "selector": sel})

    # querySelector('sel') with .click() nearby
    for m in re.finditer(
        r"document\.querySelector\s*\(\s*" + _q + r"\s*\)[\s\S]{0,80}\.click\s*\(\s*\)",
        script,
    ):
        sel = _get_selector(m, script, m.end())
        if sel and not any(c.get("selector") == sel and c.get("type") == "click" for c in out):
            out.append({"type": "click", "selector": sel})

    # querySelector('sel') with .remove() or hide (single element); skip if already in out (e.g. from querySelectorAll)
    for m in re.finditer(
        r"document\.querySelector\s*\(\s*" + _q + r"\s*\)",
        script,
        re.DOTALL,
    ):
        sel = _get_selector(m, script, m.end())
        if not sel or any(c.get("selector") == sel for c in out):
            continue
        if _uses_remove(script, m.end()):
            out.append({"type": "remove", "selector": sel})
        else:
            out.append({"type": "hide", "selector": sel})

    # getElementById('id') or getElementById("id") -> selector #id
    for m in re.finditer(
        r"document\.getElementById\s*\(\s*" + _q + r"\s*\)",
        script,
    ):
        sel = _get_selector(m, script, m.end())
        if sel:
            selector = "#" + sel
            if not any(c.get("selector") == selector for c in out):
                action = "remove" if _uses_remove(script, m.end()) else "hide"
                out.append({"type": action, "selector": selector})

    # window.scrollBy(x, y)
    for m in re.finditer(r"window\.scrollBy\s*\(\s*(-?\d+)\s*,\s*(-?\d+)\s*\)", script):
        out.append({"type": "scroll", "x": int(m.group(1)), "y": int(m.group(2))})
    return out
