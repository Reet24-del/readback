"""Make what a TTS will *say* match what a person *sees*.

Each trick here changes speech without changing (or while faking) the display:
  - invisible format characters (zero-width space, bidi overrides) inside numbers and codes
  - non-ASCII digits (Devanagari, Arabic-Indic, full-width) that look or mean the same
  - Cyrillic/Greek letters disguised as Latin ones inside codes ("MН12" with a Cyrillic Н)
  - SSML-style tags smuggled into plain text
The cleaned text is safe to speak; the findings are alerts in their own right.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Bidi overrides/isolates reorder what is displayed without changing what is read.
BIDI_CONTROLS = set("‪‫‬‭‮⁦⁧⁨⁩‎‏")
# ZWJ/ZWNJ are legitimate inside Indic and Arabic words, so only flag them next to ASCII.
JOINERS = {"‌", "‍"}

CONFUSABLES = {
    # Cyrillic
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X",
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    # Greek
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P",
    "Τ": "T", "Υ": "Y", "Χ": "X", "ο": "o", "ν": "v",
}

_TAG = re.compile(r"</?\s*[a-zA-Z][\w:-]*(?:\s+[^<>]*)?/?>")
_TOKEN = re.compile(r"\S+")


@dataclass
class Finding:
    kind: str  # invisible | bidi | digit | confusable | compat | markup
    severity: str  # critical | warning
    char: str
    detail: str


@dataclass
class SanitizeResult:
    original: str
    text: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.text != self.original

    @property
    def critical(self) -> bool:
        return any(f.severity == "critical" for f in self.findings)


def _cp(ch: str) -> str:
    return f"U+{ord(ch):04X} {unicodedata.name(ch, '?')}"


_OVERRIDE = re.compile("([‭‮])(.*?)(‬|$)", re.S)


def _apply_overrides(text: str, findings: list[Finding]) -> str:
    """Lay out bidi overrides the way a screen does, so we speak what the user sees.

    U+202E (RLO) shows everything up to U+202C (PDF) right-to-left, so "‮005‬"
    is displayed as "500". Reading the logical order instead is the attack.
    """

    def visual(m: re.Match) -> str:
        mark, body = m.group(1), m.group(2)
        findings.append(Finding("bidi", "critical", _cp(mark), f"{body!r} is displayed as {body[::-1] if mark == '‮' else body!r}"))
        return body[::-1] if mark == "‮" else body

    return _OVERRIDE.sub(visual, text)


def _strip_format_chars(text: str, findings: list[Finding]) -> str:
    out = []
    for i, ch in enumerate(text):
        if unicodedata.category(ch) != "Cf":
            out.append(ch)
            continue
        if ch in JOINERS:
            prev = text[i - 1] if i else ""
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if not (prev.isascii() or nxt.isascii()):
                out.append(ch)  # shaping a non-Latin word: leave it alone
                continue
        if ch in BIDI_CONTROLS:
            findings.append(Finding("bidi", "critical", _cp(ch), "reorders what is displayed vs. what is read"))
        else:
            near = text[max(0, i - 6) : i + 7].replace(ch, "·")
            findings.append(Finding("invisible", "critical", _cp(ch), f"hidden inside {near!r}"))
    return "".join(out)


def _ascii_digits(text: str, findings: list[Finding]) -> str:
    out = []
    for ch in text:
        if ch.isdigit() and not ch.isascii():
            try:
                d = unicodedata.decimal(ch)
            except ValueError:  # superscripts and the like; NFKC handles those
                out.append(ch)
                continue
            findings.append(Finding("digit", "warning", _cp(ch), f"non-ASCII digit read as {d}"))
            out.append(str(d))
        else:
            out.append(ch)
    return "".join(out)


def _unconfuse(text: str, findings: list[Finding]) -> str:
    def fix(m: re.Match) -> str:
        tok = m.group()
        has_latin = any(c.isascii() and c.isalnum() for c in tok)
        bad = [c for c in tok if c in CONFUSABLES]
        if not (has_latin and bad):
            return tok  # an all-Cyrillic or all-Greek word is just that language
        for c in bad:
            findings.append(Finding("confusable", "critical", _cp(c), f"looks like {CONFUSABLES[c]!r} inside {tok!r}"))
        return "".join(CONFUSABLES.get(c, c) for c in tok)

    return _TOKEN.sub(fix, text)


def _is_disguise_block(ch: str) -> bool:
    cp = ord(ch)
    return 0xFF00 <= cp <= 0xFFEF or 0x1D400 <= cp <= 0x1D7FF  # full/half-width, math alphanumerics


def _normalize_compat(text: str, findings: list[Finding]) -> str:
    """NFKC, except vulgar fractions and superscripts (category No): "½ tab" must stay "½ tab"."""
    for ch in dict.fromkeys(c for c in text if _is_disguise_block(c) and not c.isdigit()):
        findings.append(Finding("compat", "warning", _cp(ch), f"read as {unicodedata.normalize('NFKC', ch)!r}"))
    out, buf = [], []
    for ch in text:
        if unicodedata.category(ch) == "No":
            out.append(unicodedata.normalize("NFKC", "".join(buf)))
            out.append(ch)
            buf = []
        else:
            buf.append(ch)
    out.append(unicodedata.normalize("NFKC", "".join(buf)))
    return "".join(out)


_LETTER_IN_NUMBER = re.compile(r"(?<=\d)([OolI])(?=[OolI]*\d)")
_EMPHASIS = re.compile(r"(\*\*|__|\*|_|~~|`)(?=\S)(.+?)(?<=\S)\1")


def _letters_in_numbers(text: str, findings: list[Finding]) -> str:
    """"₹5O00" with a letter O (or l/I for 1) between digits is displayed as a number: say it as one."""

    def fix(m: re.Match) -> str:
        digit = "0" if m.group(1) in "Oo" else "1"
        findings.append(Finding("confusable", "critical", m.group(1), f"letter {m.group(1)!r} inside a number, read as {digit}"))
        return digit

    return _LETTER_IN_NUMBER.sub(fix, text)


def _is_identifier_underscore(m: re.Match) -> bool:
    """snake_case and emails like rahul_k@ are not emphasis."""
    return m.group(1) in ("_", "__") and bool(re.search(r"\w_|_\w", m.group()))


def _strip_markup(text: str, findings: list[Finding]) -> str:
    # Repeat until stable: "<<b>b>" and "***x***" only reveal their inner layer once the outer one is gone.
    for _ in range(10):
        before = text
        for m in _TAG.finditer(text):
            findings.append(Finding("markup", "warning", m.group(), "markup tag in plain text"))
        text = _TAG.sub("", text)
        for m in _EMPHASIS.finditer(text):
            if not _is_identifier_underscore(m):
                findings.append(Finding("markup", "warning", m.group(1), "markdown emphasis in plain text"))
        text = _EMPHASIS.sub(lambda m: m.group() if _is_identifier_underscore(m) else m.group(2), text)
        if text == before:
            break
    return text


def sanitize(text: str) -> SanitizeResult:
    findings: list[Finding] = []
    s = _apply_overrides(text, findings)
    s = _strip_format_chars(s, findings)
    s = _ascii_digits(s, findings)
    s = _unconfuse(s, findings)
    s = _normalize_compat(s, findings)
    s = _letters_in_numbers(s, findings)
    s = _strip_markup(s, findings)
    s = re.sub(r"[ \t]{2,}", " ", s).strip()
    return SanitizeResult(text, s, findings)
