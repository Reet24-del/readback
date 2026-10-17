"""Score a run: PASS / FAIL / UNCLEAR / ERROR for every case × voice.

    python -m readback.score               # scores runs/latest
    python -m readback.score runs/<dir> --no-llm

Order of checks for each result:
  1. an accepted reading appears in the verbatim transcript         -> PASS
  2. a type-specific checker compares the heard value to the truth  -> PASS / FAIL / UNCLEAR
  3. UNCLEAR (and name/email non-passes) go to the LLM judge        -> PASS / FAIL / UNCLEAR
Writes scored.jsonl and summary.json next to results.jsonl.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from rapidfuzz import fuzz

from readback.config import RUNS_DIR
from readback.numparse import SCALES, NumberSpan, find_numbers, parse_cardinal, to_digits

PASS, FAIL, UNCLEAR, ERROR, BLOCKED = "PASS", "FAIL", "UNCLEAR", "ERROR", "BLOCKED"


@dataclass
class Verdict:
    status: str
    method: str
    reason: str
    heard_span: str = ""


# ---------------------------------------------------------------- helpers


def tokens(s: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", s.lower().replace("'", "")).split()


def has_phrase(hay: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(hay[i : i + n] == needle for i in range(len(hay) - n + 1))


def _eq(a, b) -> bool:
    return a is not None and b is not None and math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)


def _fmt(x) -> str:
    return f"{x:,}" if isinstance(x, int) else f"{x:g}"


def aligned_span(row: dict, spans: list[NumberSpan]) -> NumberSpan | None:
    """The heard number span that sits where the critical span was written, by position."""
    if len(spans) == 1:
        return spans[0]
    start = row["text"].find(row["critical"])
    end = start + len(row["critical"])
    written = find_numbers(row["text"])
    idx = next((i for i, s in enumerate(written) if s.start < end and s.end > start), None)
    if idx is not None and len(written) == len(spans):
        return spans[idx]
    return None


# ---------------------------------------------------------------- checkers


def check_number(row: dict, heard: str) -> Verdict:
    want = row["value"]["value"]
    spans = find_numbers(heard)
    if not any(_eq(x.value, want) for x in spans):
        # "two point five rupees crore": right number, currency word in the wrong place.
        without_cur = re.sub(r"\b(rupees?|dollars?|rs)\b", " ", heard, flags=re.I)
        if any(_eq(x.value, want) for x in find_numbers(without_cur)):
            return Verdict(UNCLEAR, "value", f"the value {_fmt(want)} is there, but the currency word is in the wrong place")
    s = aligned_span(row, spans)
    if s is None:
        if any(_eq(x.value, want) for x in spans):
            return Verdict(PASS, "value", f"heard {_fmt(want)}")
        if spans:  # accepted readings already failed, and no spoken number equals the value
            heard_nums = ", ".join(repr(x.text) for x in spans)
            return Verdict(FAIL, "value", f"no spoken number equals {_fmt(want)} (heard {heard_nums})", spans[0].text)
        return Verdict(UNCLEAR, "value", "no numbers were spoken")
    if _eq(s.value, want):
        return Verdict(PASS, "value", f"heard {_fmt(want)}", s.text)
    if s.value is None:
        return Verdict(FAIL, "value", f"heard {s.text!r}, which is not a standard reading of {_fmt(want)}", s.text)
    return Verdict(FAIL, "value", f"heard {s.text!r} = {_fmt(s.value)}, expected {_fmt(want)}", s.text)


UNIT_ALIASES = {
    "mg": ["milligram", "milligrams", "mg", "m g"],
    "ml": ["milliliter", "milliliters", "millilitre", "millilitres", "ml", "m l", "mil", "mils"],
    "mcg": ["microgram", "micrograms", "mcg", "m c g"],
    "g": ["gram", "grams", "g"],
    "iu": ["international unit", "international units", "iu", "i u"],
    "tab": ["tab", "tabs", "tablet", "tablets"],
    "units": ["unit", "units"],
    "drop": ["drop", "drops"],
}


def check_dose(row: dict, heard: str) -> Verdict:
    v = row["value"]
    num = check_number({**row, "value": {"type": "number", "value": v["amount"]}}, heard)
    if num.status != PASS:
        return Verdict(num.status, "dose", num.reason, num.heard_span)
    spans = find_numbers(heard)
    s = aligned_span(row, spans) or next(x for x in spans if _eq(x.value, v["amount"]))
    after = tokens(heard[s.end : s.end + 40])[:4]
    aliases = UNIT_ALIASES.get(v["unit"].lower(), [v["unit"].lower()])
    if any(has_phrase(after, tokens(a)) for a in aliases):
        return Verdict(PASS, "dose", f"heard {s.text} {v['unit']}", s.text)
    return Verdict(FAIL, "dose", f"amount right but unit {v['unit']!r} not heard (heard {' '.join(after)!r})", s.text)


def check_digits(row: dict, heard: str) -> Verdict:
    want = row["value"]["digits"]
    spans = find_numbers(heard)
    s = aligned_span(row, spans)
    spoken_as_words = s is not None and not any(t[0].isdigit() for t in s.tokens)
    if spoken_as_words and s.value is not None and len(want) >= 3 and s.value >= 100:
        return Verdict(FAIL, "digits", f"read as the number {s.text!r} instead of digit by digit", s.text)
    if s is not None and any(t in SCALES for t in s.tokens):
        return Verdict(FAIL, "digits", f"read as an amount ({s.text!r}) instead of digit by digit", s.text)
    if s is not None and s.digits == want:
        return Verdict(PASS, "digits", f"heard {want}", s.text)
    if want in "".join(x.digits or "" for x in spans):
        return Verdict(PASS, "digits", f"heard {want} across {len(spans)} groups")
    if s is not None:
        return Verdict(FAIL, "digits", f"heard {s.digits or s.text!r}, expected {want}", s.text)
    if spans:
        heard_nums = ", ".join(repr(x.text) for x in spans)
        return Verdict(FAIL, "digits", f"the digits {want} were never spoken in order (heard {heard_nums})", spans[0].text)
    return Verdict(UNCLEAR, "digits", "no numbers were spoken")


LETTER_NAMES = {
    "zed": "Z", "zee": "Z", "ex": "X", "why": "Y", "bee": "B", "see": "C", "sea": "C", "dee": "D", "ef": "F",
    "eff": "F", "gee": "G", "aitch": "H", "jay": "J", "kay": "K", "el": "L", "em": "M", "en": "N", "pee": "P",
    "cue": "Q", "queue": "Q", "ar": "R", "ess": "S", "tee": "T", "vee": "V",
}


def spelled_windows(heard: str) -> list[str]:
    """Runs of spelled letters and digits in the transcript, e.g. "m h twelve a b" -> "MH12AB".

    The transcriber often writes spelled-out letters as one capitalised word ("ABCD zero one"),
    so an ALL-CAPS token counts as letters, while "Gstin" or "Wix" is a word.
    """
    raw = re.findall(r"[A-Za-z0-9]+", heard.replace("'", ""))
    caps = {t.lower() for t in raw if t.isalpha() and t.isupper() and 2 <= len(t) <= 8}
    toks = [t.lower() for t in raw]
    windows, cur, i = [], "", 0
    while i < len(toks):
        t = toks[i]
        if t in ("dash", "hyphen") and cur:
            pass  # "nine f three a dash seven seven b two": separators are not part of the code
        elif (len(t) == 1 and t.isalpha()) or t in caps:
            cur += t.upper()
        elif t in LETTER_NAMES:
            cur += LETTER_NAMES[t]
        elif t == "double" and i + 1 < len(toks) and len(toks[i + 1]) == 1 and toks[i + 1].isalpha():
            cur, i = cur + toks[i + 1].upper() * 2, i + 1
        elif re.fullmatch(r"[a-z0-9]*\d[a-z0-9]*", t) and not t.isdigit():
            cur += t.upper()  # the transcript wrote the code itself, e.g. "mh12ab1234"
        else:
            j = i
            while j < len(toks) and (to_digits([toks[j]]) is not None or toks[j] in ("double", "triple", "hundred")):
                j += 1
            digits = to_digits(toks[i:j]) if j > i else None
            if digits is not None:
                cur, i = cur + digits, j
                continue
            if cur:
                windows.append(cur)
            cur = ""
        i += 1
    if cur:
        windows.append(cur)
    return windows


def check_code(row: dict, heard: str) -> Verdict:
    want = re.sub(r"[^A-Z0-9]", "", row["value"]["chars"].upper())
    norm = lambda s: s.replace("O", "0")  # spoken "oh" is ambiguous between O and 0
    windows = spelled_windows(heard)
    if any(norm(want) in norm(w) for w in windows):
        return Verdict(PASS, "chars", f"heard {want}")
    if not windows:
        return Verdict(UNCLEAR, "chars", "no spelled-out code found in the transcript")
    best = max(windows, key=lambda w: fuzz.ratio(norm(w), norm(want)))
    if fuzz.ratio(norm(best), norm(want)) >= 60:
        return Verdict(FAIL, "chars", f"heard {best}, expected {want}", best)
    return Verdict(UNCLEAR, "chars", f"closest spelled run {best!r} does not resemble {want}")


MONTH_NAMES = dict(enumerate("january february march april may june july august september october november december".split(), 1))
MONTHS = {m: i for i, m in MONTH_NAMES.items()} | {m[:3]: i for i, m in MONTH_NAMES.items()} | {"sept": 9}


def _split_day_year(toks: list[str]) -> tuple[int | None, int | None]:
    """"third twenty twenty six" -> (3, 2026); "twenty fourth" -> (24, None)."""
    for k in range(len(toks), 0, -1):
        d = parse_cardinal(toks[:k])
        if d is None or not (1 <= d <= 31):
            continue
        rest = toks[k:]
        if not rest:
            return int(d), None
        y = parse_cardinal(rest)
        if y is None or y < 1000:
            digits = to_digits(rest)
            y = int(digits) if digits and len(digits) == 4 else None
        if y is not None:
            return int(d), int(y)
    return None, None


def _year_of(toks: list[str]) -> int | None:
    y = parse_cardinal(toks)
    if y is not None and y >= 1000:
        return int(y)
    digits = to_digits(toks)
    return int(digits) if digits and len(digits) == 4 else None


def check_date(row: dict, heard: str) -> Verdict:
    v = row["value"]
    low = heard.lower()
    found = [(m.start(), MONTHS[m.group(1)]) for m in re.finditer(r"\b(" + "|".join(MONTHS) + r")\b", low)]
    if not found:
        return Verdict(UNCLEAR, "date", "no month name was spoken")
    pos, month = found[0]
    spans = find_numbers(heard)
    before = [s for s in spans if s.end <= pos and pos - s.end <= 12]
    after = [s for s in spans if s.start >= pos and s.start - pos <= 14]
    day = year = None
    if before:
        day, year = _split_day_year(before[-1].tokens)
        if after and year is None:
            year = _year_of(after[0].tokens)
    elif after:
        day, year = _split_day_year(after[0].tokens)
        if year is None and len(after) > 1:
            year = _year_of(after[1].tokens)
    said = f"{MONTH_NAMES[month]} {day}" + (f" {year}" if year else "")
    if month == v["month"] and day == v["day"] and (not v.get("year") or year in (None, v["year"])):
        if v.get("year") and year is None:
            return Verdict(FAIL, "date", f"heard {said} but the year {v['year']} was dropped", said)
        return Verdict(PASS, "date", f"heard {said}", said)
    if month == v["day"] and day == v["month"]:
        return Verdict(FAIL, "date", f"heard {said}: day and month swapped (US MM/DD reading of a DD/MM date)", said)
    return Verdict(FAIL, "date", f"heard {said}, expected {MONTH_NAMES[v['month']]} {v['day']}", said)


def check_time(row: dict, heard: str) -> Verdict:
    h, m = row["value"]["hour"], row["value"]["minute"]
    h12 = h % 12 or 12
    ok = {f"{h}{m:02d}", f"{h12}{m:02d}"}
    if m == 0:
        ok |= {str(h), str(h12), f"{h}00"}
    spans = find_numbers(heard)
    if any(s.digits in ok or (s.value is not None and str(int(s.value)) in ok) for s in spans if s.digits or s.value):
        return Verdict(PASS, "time", f"heard {h:02d}:{m:02d}")
    s = aligned_span(row, spans)
    if s is not None:
        return Verdict(FAIL, "time", f"heard {s.text!r}, expected {h:02d}:{m:02d}", s.text)
    return Verdict(UNCLEAR, "time", "could not find the spoken time")


SPOKEN_PUNCT = {"at": "@", "dot": ".", "underscore": "_", "dash": "-", "hyphen": "-", "minus": "-", "slash": "/"}


def check_email(row: dict, heard: str) -> Verdict:
    want = row["value"]["address"].lower()
    toks = tokens(heard)
    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        if t in SPOKEN_PUNCT:
            out.append(SPOKEN_PUNCT[t])
        else:
            j = i
            while j < len(toks) and toks[j] not in SPOKEN_PUNCT and to_digits([toks[j]]) is not None:
                j += 1
            if j > i and (d := to_digits(toks[i:j])) is not None:
                out.append(d)
                i = j
                continue
            out.append(t)
        i += 1
    joined = "".join(out)
    if want in joined:
        return Verdict(PASS, "email", f"heard {want}")
    score = fuzz.partial_ratio(want, joined)
    return Verdict(UNCLEAR if score >= 85 else FAIL, "email", f"closest match {score:.0f}% to {want}")


def check_text(row: dict, heard: str) -> Verdict:
    H = " ".join(tokens(heard))
    literal = " ".join(tokens(row["critical"]))
    if literal and has_phrase(tokens(heard), tokens(row["critical"])) and not re.search(r"\b(?:st|rd|dr|mr|ms)\b", literal):
        # The transcriber wrote it exactly as written (URLs, plain names). Abbreviations stay
        # unclear: "St." in the transcript can't tell us whether the voice said Saint or Street.
        return Verdict(PASS, "text", "transcript matches the written text exactly")
    best = max((fuzz.partial_ratio(" ".join(tokens(a)), H) for a in row["accept"]), default=0)
    if best >= 92:
        return Verdict(PASS, "text", f"close match ({best:.0f}%) to an accepted reading")
    return Verdict(UNCLEAR, "text", f"best match to an accepted reading is {best:.0f}%")


CHECKERS = {
    "amount": check_number,
    "number": check_number,
    "dose": check_dose,
    "digits": check_digits,
    "code": check_code,
    "date": check_date,
    "time": check_time,
    "email": check_email,
    "text": check_text,
}


def score_row(row: dict, use_llm: bool = True) -> Verdict:
    if row.get("error"):
        return Verdict(ERROR, "none", row["error"])
    if (row.get("safespeak") or {}).get("status") == "DO_NOT_SPEAK":
        return Verdict(BLOCKED, "safespeak", "SafeSpeak could not verify the value, so it refused to speak it")
    heard = row.get("verbatim")
    if heard is None:
        return Verdict(UNCLEAR, "none", "no transcript (the run used --skip-stt)")
    if row["value"].get("unit") == "INR":
        heard = re.sub(r"\b(?:pays|paisa|pice)\b", "paise", heard, flags=re.I)  # common STT spellings of "paise"
    H = tokens(heard)
    for a in row["accept"]:
        if has_phrase(H, tokens(a)):
            return Verdict(PASS, "accept", f"heard {a!r}", a)

    verdict = CHECKERS[row["value"]["type"]](row, heard)
    needs_llm = verdict.status == UNCLEAR or (row["value"]["type"] in ("text", "email") and verdict.status != PASS)
    if use_llm and needs_llm:
        from readback.judge import judge

        try:
            status, reason = judge(row)
            return Verdict(status, "llm", f"{reason} (rules: {verdict.reason})", verdict.heard_span)
        except Exception as e:  # the judge is a bonus; never lose the rule verdict over it
            why = "judge unavailable on this plan" if type(e).__name__ == "JudgeUnavailable" else f"judge failed: {type(e).__name__}"
            return Verdict(verdict.status, verdict.method, f"{verdict.reason} ({why}; needs an ear check)", verdict.heard_span)
    return verdict


def formatted_hides_it(row: dict) -> bool:
    """True when the formatted transcript shows the input as written, i.e. a formatted-STT check would miss the bug."""
    crit = re.sub(r"[^0-9a-z]", "", row["critical"].lower())
    fmt = re.sub(r"[^0-9a-z]", "", (row.get("formatted") or "").lower())
    return bool(crit) and crit in fmt


# ---------------------------------------------------------------- CLI


def score_run(run_dir: Path, use_llm: bool = True) -> dict:
    rows = [json.loads(line) for line in (run_dir / "results.jsonl").open()]
    scored = []
    for row in rows:
        v = score_row(row, use_llm)
        row.update(status=v.status, method=v.method, reason=v.reason, heard_span=v.heard_span)
        row["needs_ear_check"] = v.status in (FAIL, UNCLEAR)
        row["formatted_hides_it"] = v.status == FAIL and formatted_hides_it(row)
        scored.append(row)
    scored.sort(key=lambda r: (r["category"], r["case_id"], r["voice"]))

    with (run_dir / "scored.jsonl").open("w") as f:
        for r in scored:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def rate(group: list[dict]) -> dict:
        c = Counter(r["status"] for r in group)
        judged = c[PASS] + c[FAIL] + c[BLOCKED]
        return {
            **{k: c[k] for k in (PASS, FAIL, UNCLEAR, ERROR, BLOCKED)},
            "pass_rate": round(c[PASS] / judged, 3) if judged else None,
            # A blocked message is safe: nobody heard a wrong value.
            "safe_rate": round((c[PASS] + c[BLOCKED]) / judged, 3) if judged else None,
        }

    by = lambda key: {k: rate(g) for k, g in sorted(_group(scored, key).items())}
    summary = {
        "run": run_dir.name,
        "total": rate(scored),
        "by_category": by("category"),
        "by_severity": by("severity"),
        "by_voice": by("voice"),
        "fails": [f"{r['case_id']}--{r['voice']}" for r in scored if r["status"] == FAIL],
        "formatted_would_hide": sum(r["formatted_hides_it"] for r in scored),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def _group(rows: list[dict], key: str) -> dict[str, list[dict]]:
    g: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        g[r[key]].append(r)
    return g


def print_summary(summary: dict, run_dir: Path) -> None:
    t = summary["total"]
    blocked = f", {t[BLOCKED]} blocked" if t[BLOCKED] else ""
    print(f"\n{summary['run']}: {t[PASS]} pass, {t[FAIL]} fail, {t[UNCLEAR]} unclear, {t[ERROR]} error{blocked}")
    print(f"\n{'category':<12} {'pass':>5} {'fail':>5} {'uncl':>5} {'rate':>6}")
    for cat, r in summary["by_category"].items():
        rate = f"{r['pass_rate']:.0%}" if r["pass_rate"] is not None else "-"
        print(f"{cat:<12} {r[PASS]:>5} {r[FAIL]:>5} {r[UNCLEAR]:>5} {rate:>6}")
    print(f"\nformatted STT would have hidden {summary['formatted_would_hide']} of the {t[FAIL]} failures")
    print(f"-> {run_dir / 'scored.jsonl'}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run_dir", nargs="?", default=str(RUNS_DIR / "latest"))
    p.add_argument("--no-llm", action="store_true", help="rules only; unclear cases stay UNCLEAR")
    args = p.parse_args()
    run_dir = Path(args.run_dir).resolve()
    if not (run_dir / "results.jsonl").exists():
        raise SystemExit(f"no results.jsonl in {args.run_dir}; run `python -m readback.runner` first")
    print_summary(score_run(run_dir, not args.no_llm), run_dir)


if __name__ == "__main__":
    main()
