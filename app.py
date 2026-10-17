"""Readback dashboard.

    .venv/bin/python -m streamlit run app.py
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from readback import cases as case_lib
from readback.config import ROOT, RUNS_DIR
from readback.report import critical_span
from readback.safespeak import prepare, speak, speak_raw
from readback.score import score_run
from readback.tts import VOICES

st.set_page_config(page_title="Readback", page_icon="🔊", layout="wide")
PCT = st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)

DEMOS = {
    "Bank debit alert": "₹10,00,000 has been debited from your account on 03/04/2026. If this wasn't you, call 1800 425 1111.",
    "Pharmacy refill": "Hello Mrs. Sharma, your refill is ready. Take 0.5 mg of Clonazepam at night, dosage 1-0-1. Pickup OTP 482910. Next refill due 12/11/2026.",
    "Loan approval": "Your loan of ₹18,50,000 has been approved. EMI of ₹24,999 starts on 05/01/2027.",
    "Hidden-character attack": "You will be charged ₹‮005‬ today. Your refund of ₹5О00 is ready.",
}


# ---------------------------------------------------------------- data


def run_dirs() -> list[Path]:
    dirs = [d for d in RUNS_DIR.glob("2026*") if (d / "results.jsonl").exists()]
    return sorted(dirs, key=lambda d: d.name, reverse=True)


def run_info(d: Path) -> dict:
    try:
        return json.loads((d / "run.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}


@st.cache_data(show_spinner="Scoring run…")
def load_scored(run: str, mtime: float) -> list[dict]:
    d = RUNS_DIR / run
    if not (d / "scored.jsonl").exists() or (d / "scored.jsonl").stat().st_mtime < (d / "results.jsonl").stat().st_mtime:
        score_run(d, use_llm=False)
    return [json.loads(line) for line in (d / "scored.jsonl").open()]


def scored(d: Path) -> list[dict]:
    return load_scored(d.name, (d / "results.jsonl").stat().st_mtime)


def confirmations(d: Path) -> dict:
    p = d / "confirmations.json"
    return json.loads(p.read_text()) if p.exists() else {}


def save_confirmation(d: Path, key: str, verdict: str) -> None:
    data = confirmations(d)
    data[key] = {"verdict": verdict, "at": time.strftime("%Y-%m-%d %H:%M")}
    (d / "confirmations.json").write_text(json.dumps(data, indent=2))


def critical_clip(d: Path, row: dict) -> bytes | None:
    span = critical_span(d, row)
    return span.to_wav_bytes() if span is not None else None


def rates(rows: list[dict], key: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    t = pd.crosstab(df[key], df["status"])
    for col in ("PASS", "FAIL", "UNCLEAR", "BLOCKED", "ERROR"):
        if col not in t:
            t[col] = 0
    judged = t["PASS"] + t["FAIL"] + t["BLOCKED"]
    t["pass rate"] = (t["PASS"] / judged.where(judged > 0)).round(3)
    cols = ["PASS", "FAIL", "UNCLEAR"] + (["BLOCKED"] if t["BLOCKED"].any() else []) + ["pass rate"]
    return t[cols]


# ---------------------------------------------------------------- sidebar

dirs = run_dirs()
if not dirs:
    st.title("Readback")
    st.info("No runs yet. Start one with `python -m readback.runner --suite all --voices anna`.")
    st.stop()

def is_safe(d: Path) -> bool:
    return bool(run_info(d).get("safespeak")) or d.name.endswith("-safespeak")


baseline_dirs = [d for d in dirs if not is_safe(d)]
safe_dirs = [d for d in dirs if is_safe(d)]
NOTES = {c.id: c.notes for c in case_lib.load()}
biggest = max(baseline_dirs, key=lambda d: run_info(d).get("jobs", 0), default=None)

with st.sidebar:
    st.header("Runs")
    base = st.selectbox("Baseline (plain TTS)", baseline_dirs, index=baseline_dirs.index(biggest) if biggest else 0, format_func=lambda d: f"{d.name} · {run_info(d).get('jobs', '?')} jobs")
    safe = st.selectbox("SafeSpeak", safe_dirs, format_func=lambda d: f"{d.name} · {run_info(d).get('jobs', '?')} jobs") if safe_dirs else None
    st.caption("Engine: AssemblyAI Voice Agent API (text sent via `greeting`, spoken word for word). Heard = Universal transcription with `format_text=False`.")

base_rows = scored(base)
safe_rows = scored(safe) if safe else []
# Attack baselines may live in a separate run; take the newest plain run that has them.
attack_base = next((scored(d) for d in baseline_dirs if any(r["category"] == "adversarial" for r in scored(d))), [])
attack_base = [r for r in attack_base if r["category"] == "adversarial"]

st.title("🔊 Readback")
st.markdown("**Does the TTS say exactly what's written?** Readback speaks hard Indian money, medicine, code and date cases through AssemblyAI's TTS, transcribes them back, and flags every critical value that comes out wrong. **SafeSpeak** fixes them before anyone hears them.")

tab_score, tab_fail, tab_attack, tab_safe, tab_demo, tab_find = st.tabs(
    ["Scorecard", "Failures", "Attacks", "Before / after", "Live demo", "Findings"]
)

# ---------------------------------------------------------------- scorecard

with tab_score:
    core = [r for r in base_rows if r["category"] != "adversarial"]
    df = pd.DataFrame(core)
    n_pass, n_fail = (df["status"] == "PASS").sum(), (df["status"] == "FAIL").sum()
    hidden = int(df.get("formatted_hides_it", pd.Series(dtype=bool)).fillna(False).sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cases × voices", len(df))
    c2.metric("Pass rate", f"{n_pass / max(1, n_pass + n_fail):.0%}")
    c3.metric("Critical-value misreads", int(n_fail))
    c4.metric("Hidden by formatted STT", hidden, help="Failures where a formatted transcript shows the original text, so a pipeline checking with formatted STT would never notice.")

    st.subheader("By category")
    st.dataframe(rates(core, "category"), column_config={"pass rate": PCT}, width="stretch")
    st.subheader("By severity")
    st.dataframe(rates(core, "severity"), column_config={"pass rate": PCT}, width="stretch")
    if df["voice"].nunique() > 1:
        st.subheader("By voice")
        st.dataframe(rates(core, "voice"), column_config={"pass rate": PCT}, width="stretch")
    st.caption(f"Run `{base.name}`. Controls must be 100% for the rest to be trusted.")

# ---------------------------------------------------------------- failures

with tab_fail:
    conf = confirmations(base)
    cats = sorted({r["category"] for r in base_rows})
    f1, f2, f3 = st.columns(3)
    pick_cat = f1.multiselect("Category", cats, default=[c for c in cats if c != "adversarial"])
    pick_status = f2.multiselect("Status", ["FAIL", "UNCLEAR"], default=["FAIL", "UNCLEAR"])
    only_open = f3.toggle("Only unchecked", value=False)
    shown = [r for r in base_rows if r["category"] in pick_cat and r["status"] in pick_status]
    if only_open:
        shown = [r for r in shown if f"{r['case_id']}--{r['voice']}" not in conf]
    st.caption(f"{len(shown)} results. Listen, then mark each one. Only confirmed misreads go into bug reports.")
    for r in shown:
        key = f"{r['case_id']}--{r['voice']}"
        mark = conf.get(key, {}).get("verdict")
        badge = {"misread": "✅ confirmed misread", "fine": "↩️ sounded fine"}.get(mark, "👂 needs ear check")
        with st.expander(f"{r['status']} · {r['case_id']} · {r['critical']} · {badge}"):
            a, b = st.columns([3, 2])
            with a:
                st.markdown(f"**Written:** {r['text']}")
                st.markdown(f"**Heard:** {r.get('verbatim', '')}")
                st.markdown(f"**Why:** {r['reason']}")
                if r.get("formatted"):
                    st.caption(f"Formatted STT: {r['formatted']}" + ("  ← hides the bug" if r.get("formatted_hides_it") else ""))
                st.caption("Expected e.g.: " + " · ".join(r["accept"][:3]))
            with b:
                if r.get("wav"):
                    st.audio(str(base / r["wav"]))
                    if (span := critical_clip(base, r)) is not None:
                        st.caption("Just the critical part:")
                        st.audio(span, format="audio/wav")
                x, y = st.columns(2)
                if x.button("Confirmed misread", key=f"m-{key}"):
                    save_confirmation(base, key, "misread")
                    st.rerun()
                if y.button("Sounded fine", key=f"f-{key}"):
                    save_confirmation(base, key, "fine")
                    st.rerun()

# ---------------------------------------------------------------- attacks

with tab_attack:
    st.markdown("Each attack hides something in the text that changes what's **spoken** but not what's **shown**. The expected value is what the screen shows, so a FAIL means the voice and the screen disagree.")
    safe_by_id = {r["case_id"]: r for r in safe_rows if r["category"] == "adversarial"}
    table = []
    for r in attack_base:
        s = safe_by_id.get(r["case_id"], {})
        table.append(
            {
                "attack": r["case_id"].removeprefix("atk-"),
                "screen shows": NOTES.get(r["case_id"], "").split("Screen shows: ", 1)[-1],
                "plain TTS said": r.get("verbatim", ""),
                "plain": r["status"],
                "SafeSpeak said": s.get("verbatim", "—"),
                "SafeSpeak": s.get("status", "—"),
                "alerts": len((s.get("safespeak") or {}).get("alerts", [])),
            }
        )
    if table:
        st.dataframe(pd.DataFrame(table), width="stretch", hide_index=True)
    else:
        st.info("No attack run yet: `python -m readback.runner --suite adversarial --voices anna`.")

# ---------------------------------------------------------------- before / after

with tab_safe:
    if not safe_rows:
        st.info("No SafeSpeak run yet: `python -m readback.runner --suite all --voices anna --safespeak`.")
    else:
        before = {r["case_id"]: r for r in base_rows + attack_base}
        after = {r["case_id"]: r for r in safe_rows}
        common = sorted(set(before) & set(after))
        b_pass = sum(before[c]["status"] == "PASS" for c in common)
        a_safe = sum(after[c]["status"] in ("PASS", "BLOCKED") for c in common)
        b_fail = sum(before[c]["status"] == "FAIL" for c in common)
        a_fail = sum(after[c]["status"] == "FAIL" for c in common)
        c1, c2, c3 = st.columns(3)
        c1.metric("Correct, plain TTS", f"{b_pass / len(common):.0%}")
        c2.metric("Correct or safely blocked, SafeSpeak", f"{a_safe / len(common):.0%}", f"{(a_safe - b_pass) / len(common):+.0%}")
        c3.metric("Misreads", a_fail, f"{a_fail - b_fail:+d}", delta_color="inverse")
        cat_rows = []
        for cat in sorted({before[c]["category"] for c in common}):
            ids = [c for c in common if before[c]["category"] == cat]
            cat_rows.append(
                {
                    "category": cat,
                    "plain TTS": sum(before[c]["status"] == "PASS" for c in ids) / len(ids),
                    "SafeSpeak": sum(after[c]["status"] in ("PASS", "BLOCKED") for c in ids) / len(ids),
                    "cases": len(ids),
                }
            )
        st.dataframe(pd.DataFrame(cat_rows), column_config={"plain TTS": PCT, "SafeSpeak": PCT}, width="stretch", hide_index=True)
        still = [after[c] for c in common if after[c]["status"] in ("FAIL", "UNCLEAR")]
        if still:
            st.subheader(f"Still not clean with SafeSpeak ({len(still)})")
            st.dataframe(
                pd.DataFrame([{"case": r["case_id"], "status": r["status"], "said": (r.get("safespeak") or {}).get("spoken_text", ""), "heard": r.get("verbatim", ""), "why": r["reason"]} for r in still]),
                width="stretch",
                hide_index=True,
            )

# ---------------------------------------------------------------- live demo

with tab_demo:
    st.markdown("Type any message a bank, pharmacy or delivery app might read out. You'll hear plain TTS and SafeSpeak side by side. Presets are cached; new text uses a few seconds of API credit.")
    preset = st.selectbox("Preset", list(DEMOS), index=0)
    text = st.text_area("Message", DEMOS[preset], height=90)
    voice = st.selectbox("Voice", [v for vs in VOICES.values() for v in vs], index=[v for vs in VOICES.values() for v in vs].index("anna"))
    plan = prepare(text)
    with st.expander("What SafeSpeak will say (offline preview)", expanded=True):
        st.markdown(f"> {plan.spoken_text}")
        if plan.sanitized.findings:
            for f in plan.sanitized.findings:
                st.warning(f"{f.severity.upper()} · {f.kind}: {f.detail}")
    if st.button("▶ Speak both", type="primary"):
        with st.spinner("Speaking and transcribing…"):
            raw_clip, raw_heard, raw_checks = asyncio.run(speak_raw(text, voice))
            safe_result = asyncio.run(speak(text, voice))
        l, r = st.columns(2)
        with l:
            st.subheader("Plain TTS")
            st.audio(raw_clip.to_wav_bytes(), format="audio/wav")
            st.markdown(f"**Heard:** {raw_heard}")
            st.dataframe(pd.DataFrame(raw_checks), hide_index=True, width="stretch")
        with r:
            st.subheader(f"SafeSpeak · {safe_result.status}")
            st.audio(safe_result.clip.to_wav_bytes(), format="audio/wav")
            st.markdown(f"**Heard:** {safe_result.heard}")
            st.dataframe(pd.DataFrame(safe_result.attempts[-1]["checks"]), hide_index=True, width="stretch")
            if safe_result.status == "DO_NOT_SPEAK":
                st.error("SafeSpeak could not verify every value, so it would send this as a text message instead of speaking it.")

# ---------------------------------------------------------------- findings

with tab_find:
    for md in sorted((ROOT / "findings").glob("BUG-*.md")):
        with st.expander(md.stem + ": " + md.read_text().splitlines()[0].split(":", 1)[-1].strip(), expanded=md.stem == "BUG-001"):
            body = md.read_text()
            st.markdown(re.sub(r"\]\(clips/", "](findings/clips/", body))
            for clip in sorted((ROOT / "findings" / "clips").glob(f"{md.stem}*.wav")):
                st.caption(clip.name)
                st.audio(str(clip))
