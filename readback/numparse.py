"""Turn spoken English number words back into values, Indian scales included.

Each number span gets two readings, because the same words mean different things:
  value  - the cardinal reading: "one lakh fifty thousand" -> 150000, "zero point five" -> 0.5
  digits - the digit-string reading used for phones and codes:
           "nine eight seven double six" -> "98766", "eighteen hundred" -> "1800"
"""

from __future__ import annotations

import re
from dataclasses import dataclass

UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine".split())}
TEENS = {w: i + 10 for i, w in enumerate("ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: (i + 2) * 10 for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
ORD_UNITS = {w: i + 1 for i, w in enumerate("first second third fourth fifth sixth seventh eighth ninth".split())}
ORD_TEENS = {w: i + 10 for i, w in enumerate("tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth".split())}
ORD_TENS = {"twentieth": 20, "thirtieth": 30}
SCALES = {
    "thousand": 1_000,
    "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
    "million": 1_000_000,
    "crore": 10_000_000, "crores": 10_000_000,
    "billion": 1_000_000_000,
}
REPEAT = {"double": 2, "triple": 3}
ZERO_ALIASES = {"oh", "o", "nought", "naught"}

_TOKEN = re.compile(r"[a-z]+|\d[\d,]*(?:\.\d+)?")
_LITERAL = re.compile(r"\d[\d,]*(?:\.\d+)?")
_SENTENCE_BREAK = re.compile(r"[.!?;:]")


def _kind(tok: str) -> str | None:
    if tok in UNITS:
        return "unit"
    if tok in TEENS:
        return "teen"
    if tok in TENS:
        return "tens"
    if tok in ORD_UNITS:
        return "ord_unit"
    if tok in ORD_TEENS:
        return "ord_teen"
    if tok in ORD_TENS:
        return "ord_tens"
    if tok == "hundred":
        return "hundred"
    if tok in SCALES:
        return "scale"
    if tok in REPEAT:
        return "repeat"
    if tok in ZERO_ALIASES:
        return "zero_alias"
    if _LITERAL.fullmatch(tok):
        return "lit"
    return None


def _small_value(tok: str) -> int:
    for table in (UNITS, TEENS, TENS, ORD_UNITS, ORD_TEENS, ORD_TENS):
        if tok in table:
            return table[tok]
    raise KeyError(tok)


def _digit(tok: str) -> str | None:
    """A single spoken digit, for decimals and digit-by-digit reads."""
    if tok in UNITS:
        return str(UNITS[tok])
    if tok in ZERO_ALIASES:
        return "0"
    if tok.isdigit():
        return tok
    return None


def _literal_value(tok: str) -> int | float:
    plain = tok.replace(",", "")
    return float(plain) if "." in plain else int(plain)


def _tidy(v: float) -> int | float:
    v = round(v, 9)
    return int(v) if float(v).is_integer() else v


def parse_cardinal(tokens: list[str]) -> int | float | None:
    """Value of a grammatical cardinal ("two lakh fifty thousand"), else None ("five five")."""
    if not tokens:
        return None

    if "point" in tokens:
        i = tokens.index("point")
        whole = parse_cardinal(tokens[:i]) if i else 0
        if whole is None:
            return None
        frac, j = "", i + 1
        while j < len(tokens) and (d := _digit(tokens[j])) is not None:
            frac, j = frac + d, j + 1
        if not frac:
            return None
        scale = 1
        for t in tokens[j:]:
            if t in SCALES:
                scale *= SCALES[t]
            elif t == "hundred":
                scale *= 100
            else:
                return None
        return _tidy((whole + float("0." + frac)) * scale)

    total = current = 0
    last: str | None = None
    for idx, t in enumerate(tokens):
        if t == "and":
            if last not in ("hundred", "scale"):
                return None
            continue
        if t == "a":
            nxt = tokens[idx + 1] if idx + 1 < len(tokens) else ""
            if (nxt == "hundred" or nxt in SCALES) and last in (None, "scale"):
                current, last = 1, "unit"
                continue
            return None

        k = _kind(t)
        if k in ("unit", "ord_unit"):
            if last in ("unit", "teen", "lit"):
                return None
            current, last = current + _small_value(t), "unit"
        elif k in ("teen", "ord_teen"):
            if last in ("unit", "teen", "tens", "lit"):
                return None
            current, last = current + _small_value(t), "teen"
        elif k in ("tens", "ord_tens"):
            if last in ("unit", "teen", "tens", "lit"):
                return None
            current, last = current + _small_value(t), "tens"
        elif k == "hundred":
            if last == "hundred":
                return None
            current, last = (current or 1) * 100, "hundred"
        elif k == "scale":
            total, current, last = total + (current or 1) * SCALES[t], 0, "scale"
        elif k == "lit":
            if last is not None:
                return None
            current, last = _literal_value(t), "lit"
        else:
            return None
    return _tidy(total + current)


def to_digits(tokens: list[str]) -> str | None:
    """Digit-string reading: greedy longest cardinal chunks, plus double/triple/oh."""
    out: list[str] = []
    i, n = 0, len(tokens)
    while i < n:
        t = tokens[i]
        if t in REPEAT and i + 1 < n and (d := _digit(tokens[i + 1])) is not None:
            out.append(d * REPEAT[t])
            i += 2
            continue
        if t in ZERO_ALIASES:
            out.append("0")
            i += 1
            continue
        if _kind(t) == "lit":
            out.append(t.replace(",", ""))
            i += 1
            continue
        for j in range(n, i, -1):
            seg = tokens[i:j]
            if "point" in seg or seg[-1] == "and" or any(s in REPEAT or s in ZERO_ALIASES or _kind(s) == "lit" for s in seg):
                continue
            v = parse_cardinal(seg)
            if v is not None:
                out.append(str(int(v)))
                i = j
                break
        else:
            return None
    return "".join(out)


@dataclass
class NumberSpan:
    text: str  # the original words, as they appear in the input
    start: int  # char offsets into the input
    end: int
    tokens: list[str]
    value: int | float | None
    digits: str | None
    ordinal: bool


def find_numbers(text: str) -> list[NumberSpan]:
    lowered = text.lower().replace("-", " ")
    matches = list(_TOKEN.finditer(lowered))
    toks = [m.group() for m in matches]
    n = len(toks)

    def is_core(i: int) -> bool:
        return 0 <= i < n and _kind(toks[i]) not in (None, "zero_alias")

    marked = [is_core(i) for i in range(n)]
    for i, t in enumerate(toks):
        if marked[i]:
            continue
        prev_num, next_num = is_core(i - 1), is_core(i + 1)
        if t == "o" and i + 1 < n and toks[i + 1] == "clock":  # "five o'clock" is a time, not "50"
            continue
        if t in ZERO_ALIASES and (prev_num or next_num or (i + 1 < n and toks[i + 1] in ZERO_ALIASES)):
            marked[i] = True
        elif t == "point" and i + 1 < n and _digit(toks[i + 1]) is not None:
            marked[i] = True
        elif t == "and" and prev_num and next_num:
            marked[i] = True
        elif t == "a" and i + 1 < n and (toks[i + 1] == "hundred" or toks[i + 1] in SCALES):
            marked[i] = True

    spans: list[NumberSpan] = []
    i = 0
    while i < n:
        if not marked[i]:
            i += 1
            continue
        j = i + 1
        while j < n and marked[j] and not _SENTENCE_BREAK.search(lowered[matches[j - 1].end() : matches[j].start()]):
            j += 1
        run = toks[i:j]
        # Drop dangling connectors at the edges ("and", "a" with nothing to join).
        while run and run[-1] in ("and", "a", "point"):
            run, j = run[:-1], j - 1
        if run:
            start, end = matches[i].start(), matches[j - 1].end()
            spans.append(
                NumberSpan(
                    text=text[start:end],
                    start=start,
                    end=end,
                    tokens=run,
                    value=parse_cardinal(run),
                    digits=to_digits(run),
                    ordinal=any(_kind(t) and _kind(t).startswith("ord") for t in run),
                )
            )
        i = max(j, i + 1)
    return spans
