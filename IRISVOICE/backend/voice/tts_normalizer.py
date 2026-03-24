"""
Text Normalizer for TTS

Removes characters and formatting that confuse text-to-speech engines.
"""
import re

def normalize_text(text: str) -> str:
    """
    Clean text so TTS reads it naturally without speaking symbols, paths, markdown, etc.
    """
    if not text:
        return ""

    # 1. Remove markdown formatting characters using individual replacements
    text = text.replace('**', '')
    text = text.replace('*', '')
    text = text.replace('_', '')
    text = text.replace('`', '')
    text = text.replace('#', '')
    text = text.replace('>', '')
    text = text.replace('~', '')
    text = text.replace('[', '')
    text = text.replace(']', '')
    text = text.replace('(', '')
    text = text.replace(')', '')
    text = text.replace('{', '')
    text = text.replace('}', '')
    text = text.replace('\\', '')

    # 2. Remove emojis using simple character filtering (most reliable)
    # Filter out characters outside standard ASCII + common punctuation range
    # ord(c) < 128 covers ASCII, and 256 <= ord(c) < 64095 covers emoji ranges
    text = ''.join(c for c in text if ord(c) < 128 or (256 <= ord(c) < 64095))

    # 3. Replace common symbols with spoken equivalents or remove
    replacements = {
        ':': ', ',
        '-': ' dash ',
        '/': ' slash ',
        '\\': ' backslash ',
        '**': '',
        '*': '',
        '_': '',
        '`': '',
        '~': ' approximately ',
        '@': ' at ',
        '#': ' number ',
        '$': ' dollar ',
        '%': ' percent ',
        '^': ' caret ',
        '&': ' and ',
        '|': ' pipe ',
        '->': ' to ',
        '=>': ' becomes ',
        '===': ' equals ',
        '!=': ' not equals ',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # 4. Remove file paths (keep only filename)
    text = re.sub(
        r'(?:[A-Za-z]:)?[/\\](?:[^/\\]+[/\\])*([^/\\.]+(?:\.[^/\\.]+)?)',
        r'\1',  # keep only basename
        text
    )

    # 5. Replace exclamation marks with periods
    text = text.replace('!', '.')

    # 6. Clean URLs (keep domain if short, otherwise remove)
    text = re.sub(
        r'https?://(?:www\.)?([^/\s]+)(?:/[\S]*)?',
        r'\1 website',  # e.g. "example.com website"
        text
    )

    # 7. Collapse extra whitespace, newlines, multiple punctuation
    text = re.sub(r'\s+', ' ', text)           # multiple spaces → one
    text = re.sub(r'\n+', ' ', text)           # newlines → space
    text = re.sub(r'([.!?])\s*([.!?])', r'\1', text)  # repeated punctuation

    return text.strip()

def normalize_for_speech(text: str) -> str:
    """Legacy alias used by tts.py - returns a string, not list."""
    return normalize_text(text)
