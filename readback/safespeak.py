"""SafeSpeak: make the voice say exactly what the screen shows, or say nothing.

    plan = prepare("Your balance is ₹1,50,000.")      # offline: sanitize + spell out values
    plan.spoken_text  -> "Your balance is one lakh fifty thousand rupees."
    result = await speak("Your balance is ₹1,50,000.", voice="anna")

  1. sanitize     speak what the screen shows (invisible chars, bidi, look-alikes, markup)
  2. find values  money, doses, Rx shorthand, phones, OTPs, codes, dates, times, emails
  3. spell out    each value in plain words, so the TTS normalizer never has to guess
  4. verify       transcribe the audio and check every value came back right
  5. fall back    re-say failed values one word at a time; still wrong -> DO_NOT_SPEAK
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

from readback import verbalize
from readback.cases import UNIT_WORDS, derived_forms
from readback.sanitize import SanitizeResult, sanitize
from readback.verbalize import ONES, TENS, _below_100

SPOKEN, RETRIED, BLOCKED = "SPOKEN", "SPOKEN_AFTER_RETRY", "DO_NOT_SPEAK"

MONTHS = "January February March April May June July August September October November December".split()
_ORD = dict(enumerate(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth "
    "fifteenth sixteenth seventeenth eighteenth nineteenth".split(), 1)) | {20: "twentieth", 30: "thirtieth"}


@dataclass
class Entity:
    kind: str
    original: str
    start: int
    end: int
    spoken: str
    value: dict | None  # what verification checks; None for plain abbreviations ("Dr." -> "Doctor")

    @property
    def fallback(self) -> str:
        """The same words one at a time: the commas make the TTS pause between them."""
        return ", ".join(self.spoken.replace(",", "").split())


@dataclass
class Plan:
    original: str
    sanitized: SanitizeResult
    entities: list[Entity]

    def render(self, fallback: set[int] = frozenset()) -> str:
        out, pos = [], 0
        for i, e in enumerate(self.entities):
            out += [self.sanitized.text[pos : e.start], e.fallback if i in fallback else e.spoken]
            pos = e.end
        return "".join(out + [self.sanitized.text[pos:]])

    @property
    def spoken_text(self) -> str:
        return self.render()


# ---------------------------------------------------------------- word helpers


def ordinal(n: int) -> str:
    if n in _ORD:
        return _ORD[n]
    tens, ones = divmod(n, 10)
    return f"{TENS[tens]} {_ORD[ones]}"


def year_words(y: int) -> str:
    if 2000 <= y <= 2009:
        return "two thousand" + (f" {ONES[y - 2000]}" if y > 2000 else "")
    hi, lo = divmod(y, 100)
    if lo == 0:
        return f"{_below_100(hi)} hundred"
    return f"{_below_100(hi)} {'oh ' + ONES[lo] if lo < 10 else _below_100(lo)}"


def date_words(d: int, m: int, y: int | None) -> str:
    return f"the {ordinal(d)} of {MONTHS[m - 1]}" + (f", {year_words(y)}" if y else "")


def time_words(h: int, mi: int, ampm: str | None) -> str:
    h12 = h % 12 or 12
    suffix = ampm or ("A M" if h < 12 else "P M")
    mm = "" if mi == 0 else (f" oh {ONES[mi]}" if mi < 10 else f" {_below_100(mi)}")
    return f"{_below_100(h12)}{mm} {suffix}"


def spell(s: str) -> str:
    return " ".join(ONES[int(c)] if c.isdigit() else ("dash" if c == "-" else c.upper()) for c in s if c.isalnum() or c == "-")


def digit_groups(*groups: str) -> str:
    return ", ".join(verbalize.digits(g) for g in groups if g)


def say_address(addr: str, spell_domain: bool = False) -> str:
    local, _, domain = addr.partition("@")
    parts = []
    for chunk in re.findall(r"[A-Za-z]+|\d+|[._+-]", local):
        parts.append({".": "dot", "_": "underscore", "-": "dash", "+": "plus"}.get(chunk) or (verbalize.digits(chunk) if chunk.isdigit() else chunk))
    parts.append("at")
    for chunk in re.findall(r"[A-Za-z]+|\d+|[.-]", domain):
        if chunk in ".-":
            parts.append("dot" if chunk == "." else "dash")
        elif spell_domain:
            parts.append(" ".join(chunk.upper()))
        else:
            parts.append(verbalize.digits(chunk) if chunk.isdigit() else chunk)
    return " ".join(parts)


# ---------------------------------------------------------------- finders

Finder = tuple[str, re.Pattern, "callable"]


def _money(m: re.Match) -> tuple[str, dict]:
    return money(m.group(1), m.group(2), m.group(3), m.group(4))


def money(sym: str, digits: str, frac: str | None, scale: str | None) -> tuple[str, dict]:
    scale = (scale or "").lower()
    cur, unit = ("dollars", "USD") if sym == "$" else ("rupees", "INR")
    whole = int(digits.replace(",", ""))
    mult = {"crore": 10**7, "cr": 10**7, "lakh": 10**5, "lakhs": 10**5, "l": 10**5}.get(scale, 1)
    paise = 0
    if mult > 1:
        total = round((whole + (int(frac) / 10 ** len(frac) if frac else 0)) * mult)
    else:
        total, paise = whole, int(frac.ljust(2, "0")) if frac else 0
    words = verbalize.indian(total) if unit == "INR" else verbalize.international(total)
    sub = "paise" if unit == "INR" else "cents"
    if total == 0 and paise:
        spoken = f"{_below_100(paise)} {sub}"
    else:
        spoken = f"{words} {cur}" + (f" and {_below_100(paise)} {sub}" if paise else "")
    value = total + paise / 100 if paise else total
    return spoken, {"type": "amount", "value": value, "unit": unit}


DOSE_UNITS = {
    "mg/dl": ("milligram per deciliter", "milligrams per deciliter", "mg"),
    "mg": (*UNIT_WORDS["mg"], "mg"), "mcg": (*UNIT_WORDS["mcg"], "mcg"), "µg": (*UNIT_WORDS["mcg"], "mcg"),
    "ml": (*UNIT_WORDS["ml"], "ml"), "iu": (*UNIT_WORDS["iu"], "iu"),
    "tab": ("tablet", "tablets", "tab"), "tabs": ("tablet", "tablets", "tab"), "tablet": ("tablet", "tablets", "tab"),
    "tablets": ("tablet", "tablets", "tab"), "unit": ("unit", "units", "units"), "units": ("unit", "units", "units"),
    "drop": ("drop", "drops", "drop"), "drops": ("drop", "drops", "drop"),
}
FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75}


def _dose(m: re.Match) -> tuple[str, dict]:
    raw, unit = m.group(1), m.group(2).lower()
    amount = FRACTIONS.get(raw) or float(raw.replace(",", ""))
    amount = int(amount) if float(amount).is_integer() else amount
    singular, plural, key = DOSE_UNITS[unit]
    if amount == 0.5:
        spoken = f"half a {singular}"
    else:
        num = verbalize.indian(amount) if isinstance(amount, int) else verbalize.decimal(amount)[0]
        spoken = f"{num} {singular if amount == 1 else plural}"
    return spoken, {"type": "dose", "amount": amount, "unit": key}


RX_TIMES = {"OD": "once a day", "BD": "twice a day", "BID": "twice a day", "TDS": "three times a day", "TID": "three times a day",
            "QID": "four times a day", "QDS": "four times a day", "SOS": "only when needed", "PRN": "only when needed", "HS": "at bedtime"}
RX_COUNT = {"0": "none", "1": "one", "2": "two", "½": "half"}


def _rx(m: re.Match) -> tuple[str, dict]:
    a, b, c = (RX_COUNT[g] for g in m.groups())
    return f"{a} in the morning, {b} in the afternoon, and {c} at night", {"type": "text", "value": m.group()}


def _date_dmy(m: re.Match) -> tuple[str, dict] | None:
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if mo > 12 and d <= 12:
        d, mo = mo, d  # unambiguously MM/DD
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return date_words(d, mo, y), {"type": "date", "day": d, "month": mo, "year": y}


def _date_iso(m: re.Match) -> tuple[str, dict] | None:
    y, mo, d = map(int, m.groups())
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return date_words(d, mo, y), {"type": "date", "day": d, "month": mo, "year": y}


def _date_text(m: re.Match) -> tuple[str, dict]:
    d, mon, y = int(m.group(1)), m.group(2)[:3].lower(), int(m.group(3))
    mo = [x[:3].lower() for x in MONTHS].index(mon) + 1
    return date_words(d, mo, y), {"type": "date", "day": d, "month": mo, "year": y}


def _ampm(s: str | None) -> str | None:
    return None if not s else ("P M" if s.lower().startswith("p") else "A M")


def _time_colon(m: re.Match) -> tuple[str, dict] | None:
    h, mi, ap = int(m.group(1)), int(m.group(2)), _ampm(m.group(3))
    if h > 23 or mi > 59:
        return None
    h24 = (h % 12) + (12 if ap == "P M" else 0) if ap else h
    return time_words(h24, mi, ap), {"type": "time", "hour": h24, "minute": mi}


def _time_ampm(m: re.Match) -> tuple[str, dict] | None:
    h, ap = int(m.group(1)), _ampm(m.group(2))
    if not 1 <= h <= 12:
        return None
    h24 = (h % 12) + (12 if ap == "P M" else 0)
    return time_words(h24, 0, ap), {"type": "time", "hour": h24, "minute": 0}


def _digits(*groups_idx):
    def handler(m: re.Match) -> tuple[str, dict]:
        groups = [m.group(i) for i in groups_idx] if groups_idx else [m.group()]
        prefix = "plus nine one, " if m.group().startswith("+91") else ""
        digits = ("91" if prefix else "") + "".join(groups)
        if not groups_idx:
            groups = chunk_digits(groups[0])
        return prefix + digit_groups(*groups), {"type": "digits", "digits": digits}

    return handler


def chunk_digits(s: str) -> list[str]:
    """Groups of three, but never a lone trailing digit: 10 digits -> 3-3-4, 7 -> 3-4."""
    if len(s) <= 4:
        return [s]
    groups = [s[i : i + 3] for i in range(0, len(s), 3)]
    if len(groups[-1]) == 1:
        groups[-2:] = [groups[-2] + groups[-1]]
    return groups


def _long_digits(m: re.Match) -> tuple[str, dict]:
    return digit_groups(*chunk_digits(m.group())), {"type": "digits", "digits": m.group()}


def _money_words(m: re.Match) -> tuple[str, dict]:
    """"499 rupees" with no ₹ sign."""
    return money("₹", m.group(1), m.group(2), None)


def _code(m: re.Match) -> tuple[str, dict] | None:
    chars = re.sub(r"[^A-Z0-9]", "", m.group())
    if len(chars) < 5:
        return None
    return spell(m.group()), {"type": "code", "chars": chars}


def _flight(m: re.Match) -> tuple[str, dict]:
    return f"{' '.join(m.group(1))} {verbalize.digits(m.group(2))}", {"type": "code", "chars": m.group(1) + m.group(2)}


def _fixed(word: str):
    return lambda m: (word, None)


FINDERS: list[Finder] = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), lambda m: (say_address(m.group()), {"type": "email", "address": m.group()})),
    ("upi", re.compile(r"\b[\w.-]+@[a-z]{3,}\b"), lambda m: (say_address(m.group(), spell_domain=True), {"type": "email", "address": m.group()})),
    ("url", re.compile(r"\b(?:https?://)?www\.[\w-]+(?:\.[\w-]+)+(?:/[\w/-]*)?"),
     lambda m: (" ".join({".": "dot", "/": "slash", "-": "dash"}.get(c) or (" ".join(c) if c == "www" else c) for c in re.findall(r"[A-Za-z]+|\d+|[./-]", m.group())), {"type": "text", "value": m.group()})),
    ("money", re.compile(r"(₹|Rs\.?|INR|\$)\s?(\d[\d,]*)(?:\.(\d{1,2}))?(?:\s?(crore|cr|lakhs?|L)\b)?(?:\s?/-)?"), _money),
    ("money", re.compile(r"(?<![\w.,])(\d[\d,]*)(?:\.(\d{1,2}))?\s?rupees\b"), _money_words),
    ("number", re.compile(r"(?<![\d,])\d{1,2}(?:,\d{2})+,\d{3}(?![\d,])"),
     lambda m: (verbalize.indian(int(m.group().replace(",", ""))), {"type": "number", "value": int(m.group().replace(",", ""))})),
    ("dose", re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?|½|¼|¾)\s?(mg/dL|mg|mcg|µg|ml|mL|IU|units?|tabs?|tablets?|drops?)\b"), _dose),
    ("rx", re.compile(r"\b([012½])-([012½])-([012½])\b"), _rx),
    ("rx", re.compile(r"\b(?:OD|BD|BID|TDS|TID|QID|QDS|SOS|PRN|HS)\b"), lambda m: (RX_TIMES[m.group()], {"type": "text", "value": m.group()})),
    ("date", re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), _date_iso),
    ("date", re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b"), _date_dmy),
    ("date", re.compile(r"\b(\d{1,2})\s(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s(\d{4})\b"), _date_text),
    ("time", re.compile(r"\b(\d{1,2}):(\d{2})(?:\s?(AM|PM|am|pm|a\.m\.|p\.m\.))?(?:\s?hrs\b)?"), _time_colon),
    ("time", re.compile(r"\b(\d{1,2})\s?(a\.m\.|p\.m\.|AM|PM|am|pm)(?!\w)"), _time_ampm),
    ("phone", re.compile(r"\+91[\s-]?(\d{5})[\s-]?(\d{5})\b"), _digits(1, 2)),
    ("phone", re.compile(r"\b(1800)[\s-]?(\d{3})[\s-]?(\d{4})\b"), _digits(1, 2, 3)),
    ("phone", re.compile(r"\(?\b(0\d{2,4})\)?[\s-]?(\d{3,4})[\s-]?(\d{4})\b"), _digits(1, 2, 3)),
    ("phone", re.compile(r"\b([6-9]\d{4})[\s-]?(\d{5})\b"), _digits(1, 2)),
    ("phone", re.compile(r"(?i)(?<=\bdial )\d{3,4}\b|(?<=\bcall )\d{3,4}\b"), _digits()),
    ("code", re.compile(r"\b([A-Z]{2})\s(\d{2,4})\b"), _flight),
    ("code", re.compile(r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9]+(?:-[A-Z0-9]+)*\b"), _code),
    ("digits", re.compile(r"(?<![\w,.])\d{5,}(?![\w,]|\.\d)"), _long_digits),
    ("abbrev", re.compile(r"\bDr\.(?=\s[A-Z])"), _fixed("Doctor")),
    ("abbrev", re.compile(r"\bMrs\.(?=\s)"), _fixed("Missus")),
    ("abbrev", re.compile(r"\bMr\.(?=\s)"), _fixed("Mister")),
    ("abbrev", re.compile(r"\bMs\.(?=\s)"), _fixed("Miz")),
    ("abbrev", re.compile(r"\bSt\.(?=\s[A-Z])"), _fixed("Saint")),
    ("abbrev", re.compile(r"\bRd\.(?=\s|$)"), _fixed("Road")),
]


def find_entities(text: str) -> list[Entity]:
    taken: list[tuple[int, int]] = []
    found: list[Entity] = []
    for kind, pattern, handler in FINDERS:
        for m in pattern.finditer(text):
            if any(m.start() < b and a < m.end() for a, b in taken):
                continue
            out = handler(m)
            if out is None:
                continue
            spoken, value = out
            taken.append((m.start(), m.end()))
            found.append(Entity(kind, m.group(), m.start(), m.end(), spoken, value))
    return sorted(found, key=lambda e: e.start)


def prepare(text: str) -> Plan:
    clean = sanitize(text)
    return Plan(text, clean, find_entities(clean.text))


# ---------------------------------------------------------------- speak + verify


@dataclass
class SafeResult:
    status: str
    plan: Plan
    attempts: list[dict] = field(default_factory=list)
    clip: object = None
    heard: str = ""

    @property
    def alerts(self) -> list[str]:
        return [f"{f.kind}: {f.detail}" for f in self.plan.sanitized.findings]


def verify(plan: Plan, said: str, heard: str, fallback: set[int]) -> dict[int, object]:
    from readback.score import score_row

    verdicts = {}
    for i, e in enumerate(plan.entities):
        if e.value is None:
            continue
        form = e.fallback if i in fallback else e.spoken
        row = {"text": said, "critical": form, "value": e.value, "accept": [form, e.spoken, *derived_forms(e.value)], "verbatim": heard, "error": None}
        verdicts[i] = score_row(row, use_llm=False)
    return verdicts


def check_raw(plan: Plan, heard: str) -> list[dict]:
    """Score plain TTS output (no SafeSpeak) against the values SafeSpeak found in the text."""
    from readback.score import score_row

    checks = []
    for e in plan.entities:
        if e.value is None:
            continue
        row = {"text": plan.sanitized.text, "critical": e.original, "value": e.value, "accept": [e.spoken, *derived_forms(e.value)], "verbatim": heard, "error": None}
        v = score_row(row, use_llm=False)
        checks.append({"value": e.original, "status": v.status, "reason": v.reason})
    return checks


async def speak_raw(text: str, voice: str = "anna", engine=None, use_cache: bool = True) -> tuple[object, str, list[dict]]:
    """Plain TTS, for comparison: (clip, what was heard, a check per value)."""
    from readback.stt import cached_transcribe
    from readback.tts import VoiceAgentTTS

    engine = engine or VoiceAgentTTS(use_cache=use_cache)
    clip = await engine.asynthesize(text, voice)
    heard = (await asyncio.to_thread(cached_transcribe, "verbatim", clip, use_cache))["text"]
    return clip, heard, check_raw(prepare(text), heard)


async def speak(text: str, voice: str = "anna", engine=None, use_cache: bool = True) -> SafeResult:
    from readback.stt import cached_transcribe
    from readback.tts import VoiceAgentTTS

    engine = engine or VoiceAgentTTS(use_cache=use_cache)
    plan = prepare(text)
    result = SafeResult(BLOCKED, plan)
    fallback: set[int] = set()
    for attempt in (1, 2):
        said = plan.render(fallback)
        clip = await engine.asynthesize(said, voice)
        heard = (await asyncio.to_thread(cached_transcribe, "verbatim", clip, use_cache))["text"]
        verdicts = verify(plan, said, heard, fallback)
        failed = {i for i, v in verdicts.items() if v.status == "FAIL"}
        result.attempts.append(
            {
                "said": said,
                "heard": heard,
                "checks": [
                    {"value": plan.entities[i].original, "status": v.status, "reason": v.reason} for i, v in verdicts.items()
                ],
            }
        )
        result.clip, result.heard = clip, heard
        if not failed:
            result.status = SPOKEN if attempt == 1 else RETRIED
            return result
        fallback |= failed
    return result
