"""Turn scored runs into shareable evidence.

    python -m readback.report clips runs/<run> BUG-002 code-002 phone-007 ...   # critical-span WAVs
    python -m readback.report scorecard                                          # findings/SCORECARD.md
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from readback.config import ROOT, RUNS_DIR
from readback.tts import Clip

FINDINGS = ROOT / "findings"


def load_scored(run_dir: Path) -> list[dict]:
    path = run_dir / "scored.jsonl"
    if not path.exists():
        from readback.score import score_run

        score_run(run_dir, use_llm=False)
    return [json.loads(line) for line in path.open()]


def critical_span(run_dir: Path, row: dict) -> Clip | None:
    """Just the critical part of the audio, located with the TTS engine's own word timings."""
    words = [w for w in row.get("tts_words") or [] if w.get("start_ms") is not None]
    crit = re.sub(r"\W", "", row["critical"])
    hits = [w for w in words if (t := re.sub(r"\W", "", w["text"])) and (t in crit or crit in t)]
    if not hits or not row.get("wav"):
        return None
    return Clip.from_wav(run_dir / row["wav"]).slice_ms(hits[0]["start_ms"], hits[-1]["end_ms"])


def export_clips(run_dir: Path, prefix: str, case_ids: list[str]) -> list[Path]:
    rows = {r["case_id"]: r for r in load_scored(run_dir)}
    out = []
    for cid in case_ids:
        row = rows[cid]
        full = Clip.from_wav(run_dir / row["wav"])
        out.append(full.save_wav(FINDINGS / "clips" / f"{prefix}-{cid}-full.wav"))
        if (span := critical_span(run_dir, row)) is not None:
            out.append(span.save_wav(FINDINGS / "clips" / f"{prefix}-{cid}.wav"))
    return out


def _pct(n: int, d: int) -> str:
    return f"{n / d:.0%}" if d else "-"


def scorecard() -> Path:
    runs = sorted((d for d in RUNS_DIR.glob("2026*") if (d / "results.jsonl").exists()), key=lambda d: d.name)
    info = {d: json.loads((d / "run.json").read_text()) if (d / "run.json").exists() else {} for d in runs}
    plain = [d for d in runs if not info[d].get("safespeak")]
    base = max(plain, key=lambda d: info[d].get("jobs", 0))
    attack = next(d for d in reversed(plain) if any(r["category"] == "adversarial" for r in load_scored(d)))
    safe = next((d for d in reversed(runs) if info[d].get("safespeak")), None)

    key = lambda r: (r["case_id"], r["voice"])
    before = {key(r): r for r in load_scored(base) + [r for r in load_scored(attack) if r["category"] == "adversarial"]}
    after = {key(r): r for r in load_scored(safe)} if safe else {}
    voices = sorted({v for _, v in before})
    sources = f"`{base.name}`" + (f" + `{attack.name}` (attacks)" if attack != base else "")

    def table(label: str, groups: dict[str, list]) -> list[str]:
        rows = [f"| {label} | Results | Plain TTS correct | SafeSpeak correct or safely blocked |", "|---|---|---|---|"]
        tot_b = tot_a = tot_n = 0
        for name, ks in groups.items():
            b = sum(before[k]["status"] == "PASS" for k in ks)
            a = sum(after.get(k, {}).get("status") in ("PASS", "BLOCKED") for k in ks)
            tot_b, tot_a, tot_n = tot_b + b, tot_a + a, tot_n + len(ks)
            rows.append(f"| {name} | {len(ks)} | {_pct(b, len(ks))} | {_pct(a, len(ks)) if after else '-'} |")
        rows.append(f"| **all** | **{tot_n}** | **{_pct(tot_b, tot_n)}** | **{_pct(tot_a, tot_n) if after else '-'}** |")
        return rows

    by_cat = {c: [k for k, r in before.items() if r["category"] == c] for c in sorted({r["category"] for r in before.values()})}
    by_voice = {v: [k for k in before if k[1] == v] for v in voices}
    lines = [
        "# Readback scorecard",
        "",
        f"Plain TTS: {sources}" + (f" · SafeSpeak: `{safe.name}`" if safe else ""),
        f"Engine: AssemblyAI Voice Agent API, voices {', '.join(f'`{v}`' for v in voices)}, text sent via `greeting` (spoken word for word).",
        "Heard: AssemblyAI Universal transcription with `format_text=False`.",
        "",
        *table("Category", by_cat),
    ]
    if len(voices) > 1:
        lines += ["", *table("Voice", by_voice)]
    hidden = sum(bool(r.get("formatted_hides_it")) for r in before.values())
    fails = sum(r["status"] == "FAIL" for r in before.values())
    lines += [
        "",
        f"- Plain TTS misread **{fails}** critical values; a formatted-STT check would have hidden **{hidden}** of them.",
        "- \"Correct\" means every critical value was heard as written. UNCLEAR results (abbreviations, names) need an ear check and count as not correct.",
    ]
    if after:
        a_fail = sum(after.get(k, {}).get("status") == "FAIL" for k in before)
        blocked = sum(after.get(k, {}).get("status") == "BLOCKED" for k in before)
        still = sorted(f"{c} ({v})" for c, v in before if after.get((c, v), {}).get("status") in ("FAIL", "UNCLEAR"))
        lines.append(f"- With SafeSpeak: **{a_fail}** misreads, **{blocked}** refused because they couldn't be verified (sent as SMS instead).")
        lines.append(f"- Still not clean with SafeSpeak ({len(still)}, needs an ear check)" + (f": {', '.join(still)}." if still else ": none."))
    out = FINDINGS / "SCORECARD.md"
    out.write_text("\n".join(lines) + "\n")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("clips")
    c.add_argument("run_dir")
    c.add_argument("prefix")
    c.add_argument("case_ids", nargs="+")
    sub.add_parser("scorecard")
    args = p.parse_args()
    if args.cmd == "clips":
        for path in export_clips(Path(args.run_dir), args.prefix, args.case_ids):
            print(path.relative_to(ROOT))
    else:
        print(scorecard().relative_to(ROOT))


if __name__ == "__main__":
    main()
