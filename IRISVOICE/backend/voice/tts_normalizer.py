"""
Text Normalizer for TTS

Converts markdown, code snippets, file paths, URLs, and programming symbols
into clean spoken-word equivalents so TTS engines read them naturally.

Two public functions:
  normalize_for_speech(text) — full pipeline, spec-tested
  normalize_text(text)       — legacy alias used by tts.py (backward compat)
"""
import re
from typing import List


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ext_to_speech(ext: str) -> str:
    """Convert a file extension to spoken form.

    Short extensions (≤ 3 chars) are spelled letter-by-letter.
    Longer extensions are read as a word.
    """
    if len(ext) <= 3:
        return " ".join(ext)  # e.g. "py" → "p y", "txt" → "t x t"
    return ext                # e.g. "json" → "json"


def _path_parts_to_speech(parts: List[str]) -> str:
    """Convert a list of path components (after splitting on / or \\) to speech."""
    spoken = []
    for part in parts:
        if not part:
            continue
        if "." in part:
            # Split at last dot for extension detection
            base, ext = part.rsplit(".", 1)
            base = base.replace("_", " ")
            spoken.append(f"{base} dot {_ext_to_speech(ext)}")
        else:
            spoken.append(part.replace("_", " "))
    return ", ".join(spoken)


def _replace_url(m: re.Match) -> str:
    """Replace a URL match with 'a link', preserving trailing sentence punctuation."""
    url = m.group(0)
    tail_m = re.search(r"[.,;:!?]+$", url)
    if tail_m:
        return "a link" + tail_m.group(0)
    return "a link"


def _replace_windows_path(m: re.Match) -> str:
    """Convert a Windows-style path like C:\\Users\\Midas\\file.py to speech."""
    path = m.group(0)
    # Separate trailing sentence punctuation
    tail = ""
    tail_m = re.search(r"[.,;:!?]+$", path)
    if tail_m:
        # Only treat as sentence punctuation if it's a single char or looks like end
        tail = tail_m.group(0)
        path = path[: tail_m.start()]

    drive_m = re.match(r"([A-Za-z]):\\(.*)", path, re.DOTALL)
    if not drive_m:
        return m.group(0)

    drive = drive_m.group(1).upper()
    rest = drive_m.group(2)
    parts = [p for p in rest.split("\\") if p]
    spoken = _path_parts_to_speech(parts)
    result = f"{drive} drive, {spoken}" if spoken else f"{drive} drive"
    return result + tail


def _replace_unix_path(m: re.Match) -> str:
    """Convert a Unix-style path like /var/log/syslog to speech."""
    path = m.group(0)
    tail = ""
    tail_m = re.search(r"[.,;:!?]+$", path)
    if tail_m:
        tail = tail_m.group(0)
        path = path[: tail_m.start()]

    parts = [p for p in path.split("/") if p]
    spoken = _path_parts_to_speech(parts)
    return spoken + tail


# ── Main pipeline ─────────────────────────────────────────────────────────────

def normalize_for_speech(text: str) -> str:
    """
    Convert arbitrary text into clean spoken-word form suitable for TTS.

    Processing order (each step builds on the previous):
      1.  URLs → "a link"
      2.  Inline // comments stripped
      3.  Strikethrough ~~text~~ → text
      4.  Bold **text** / __text__ → text
      5.  Italic *text* → text
      6.  Italic _text_ at word boundaries → text
      7.  Inline code `code` → code (underscores → spaces inside)
      8.  Markdown headers ## ... → plain text
      9.  List markers (- / * / • / N.) at line start stripped
      10. Windows paths (C:\\...) → speech form
      11. Unix paths (/a/b/c) → speech form
      12. Collapse whitespace (newlines → space, runs → single space)
      13. Symbol replacements (!== === -> => >= <= ^)
      14. Mid-sentence periods (". lowercase") → comma
      15. Remaining underscores → spaces
      16. Final strip
    """
    if not text:
        return ""

    # 1. URLs — replace before paths to avoid double-processing
    text = re.sub(r"https?://\S+", _replace_url, text)

    # 2. Inline // comments (strip from // to end of line)
    text = re.sub(r"\s*//[^\n]*", "", text)

    # 3. Strikethrough ~~text~~
    text = re.sub(r"~~(.*?)~~", r"\1", text)

    # 4. Bold: **text** and __text__
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)

    # 5. Italic with single *
    text = re.sub(r"\*(.*?)\*", r"\1", text)

    # 6. Italic with single _ — only at word boundaries (not inside identifiers)
    text = re.sub(r"(?<!\w)_(.*?)_(?!\w)", r"\1", text)

    # 7. Inline code `...` — convert underscores to spaces inside
    text = re.sub(r"`([^`]+)`", lambda m: m.group(1).replace("_", " "), text)

    # 8. Markdown headers: ## Header → Header
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # 9. List markers at line start
    text = re.sub(r"^[•\-\*]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)

    # 10. Windows paths (e.g. C:\Users\Midas\file.py)
    #     Must come before Unix path processing
    text = re.sub(
        r"[A-Za-z]:\\[^\s]+",
        _replace_windows_path,
        text,
    )

    # 11. Unix paths (e.g. /backend/voice/audio_engine.py)
    #     Match: /component[/component]* — at least two path components or one with extension
    text = re.sub(
        r"/(?:[a-zA-Z0-9_.-]+/)+[a-zA-Z0-9_.]+|/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.]+",
        _replace_unix_path,
        text,
    )

    # 12. Collapse whitespace BEFORE symbol substitution so symbol padding (double
    #     spaces) is not then collapsed away.
    text = re.sub(r"[ \t]+", " ", text)    # runs of spaces/tabs → single space
    text = re.sub(r"\n+", " ", text)        # newlines → space
    text = re.sub(r" {2,}", " ", text)      # collapse any double-space from newline merge

    # 13. Symbol replacements — use regex to consume surrounding whitespace so
    #     the replacement's own padding (2 spaces each side) lands cleanly.
    #     Order: longest / most specific first to avoid partial matches.
    text = re.sub(r"\s*!==\s*",  "  is not equal to  ",          text)
    text = re.sub(r"\s*===\s*",  "  is strictly equal to  ",      text)
    text = re.sub(r"\s*>=\s*",   "  greater than or equal to  ",  text)
    text = re.sub(r"\s*<=\s*",   "  less than or equal to  ",     text)
    text = re.sub(r"\s*->\s*",   "  returns  ",                   text)
    text = re.sub(r"\s*=>\s*",   "  maps to  ",                   text)
    text = re.sub(r"\^", "", text)  # caret — just removed

    # 14. Mid-sentence periods: ". lowercase" → ", lowercase"
    #     A period followed by optional space then a lowercase letter
    #     means the sentence continues — convert to comma.
    text = re.sub(r"\.\s+([a-z])", r", \1", text)

    # 15. Remaining underscores (word separators in identifiers) → spaces
    text = text.replace("_", " ")

    return text.strip()


# ── Backward compatibility ────────────────────────────────────────────────────

def normalize_text(text: str) -> str:
    """Legacy alias — used by tts.py. Delegates to the full pipeline."""
    return normalize_for_speech(text)
