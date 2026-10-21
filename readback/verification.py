"""Bind each value to its position instead of accepting it elsewhere in a reply."""

import re

from readback.score import tokens


def value_windows(text: str, spans: list[tuple[int, int]], heard: str) -> list[str | None]:
    """Split a transcript on the words between values. Missing/ambiguous anchors
    mean we cannot verify the association. Never fall back to searching globally.
    Punctuation and casing may differ, but the surrounding words must survive.
    """
    if not spans:
        return []
    # Keep original offsets/casing: code checkers distinguish ABCD from a word,
    # and numeric parsers need decimal points in 0.5 to survive alignment.
    words = [m for m in re.finditer(r"[A-Za-z0-9']+", heard) if tokens(m.group())]
    h = [tokens(m.group())[0] for m in words]
    gaps = [tokens(text[:spans[0][0]])]
    gaps += [tokens(text[a[1]:b[0]]) for a, b in zip(spans, spans[1:])]
    gaps.append(tokens(text[spans[-1][1]:]))
    boundaries = []
    cursor = 0
    for i, gap in enumerate(gaps):
        # Short outer anchors tolerate unrelated introductions or trailing speech.
        gap = gap[-4:] if i == 0 else gap[:4] if i == len(gaps) - 1 else gap
        if not gap:
            if i in (0, len(gaps) - 1):
                boundaries.append((0, 0) if i == 0 else (len(h), len(h)))
                continue
            return [None] * len(spans)  # adjacent values cannot be attributed safely
        hits = [j for j in range(cursor, len(h) - len(gap) + 1) if h[j:j + len(gap)] == gap]
        if len(hits) != 1:
            return [None] * len(spans)
        start = hits[0]
        boundaries.append((start, start + len(gap)))
        cursor = start + len(gap)
    def offset(i):
        return words[i].start() if i < len(words) else len(heard)

    return [heard[offset(left[1]):offset(right[0])] for left, right in zip(boundaries, boundaries[1:])]
