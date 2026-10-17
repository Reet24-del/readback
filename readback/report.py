"""Turn scored runs into shareable evidence.

    python -m readback.report clips runs/<run> BUG-002 code-002 phone-007 ...   # critical-span WAVs
    python -m readback.report scorecard                                          # findings/SCORECARD.md
    python -m readback.report headline                                           # numbers for the project page
    python -m readback.report snapshot                                           # results/ for a clone with no API key
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from readback.config import ROOT, RUNS_DIR, SNAPSHOT_DIR
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
    if not plain:
        raise SystemExit("no finished plain run yet; run `python -m readback.runner` first")
    base = max(plain, key=lambda d: info[d].get("jobs", 0))
    attack = next((d for d in reversed(plain) if any(r["category"] == "adversarial" for r in load_scored(d))), base)
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


def headline() -> dict:
    """The numbers the project page shows, from the same runs as SCORECARD.md."""
    runs = sorted((d for d in RUNS_DIR.glob("2026*") if (d / "results.jsonl").exists()), key=lambda d: d.name)
    info = {d: json.loads((d / "run.json").read_text()) if (d / "run.json").exists() else {} for d in runs}
    plain = [d for d in runs if not info[d].get("safespeak")]
    safes = [d for d in runs if info[d].get("safespeak")]
    if not plain or not safes:
        raise SystemExit("need one finished plain run and one finished --safespeak run")
    base = max(plain, key=lambda d: info[d].get("jobs", 0))
    safe = max(safes, key=lambda d: info[d].get("jobs", 0))
    key = lambda r: (r["case_id"], r["voice"])
    before = {key(r): r for r in load_scored(base)}
    after = {key(r): r for r in load_scored(safe)}
    common = [k for k in before if k in after]
    ok = lambda r: r["status"] in ("PASS", "BLOCKED")
    cats = {}
    for k in common:
        cats.setdefault(before[k]["category"], []).append(k)
    return {
        "base": base.name,
        "safe": safe.name,
        "voices": sorted({v for _, v in common}),
        "results": len(common),
        "cases": len({c for c, _ in common}),
        "before": sum(before[k]["status"] == "PASS" for k in common) / len(common),
        "after": sum(ok(after[k]) for k in common) / len(common),
        "misreads_before": sum(before[k]["status"] == "FAIL" for k in common),
        "misreads_after": sum(after[k]["status"] == "FAIL" for k in common),
        "blocked": sum(after[k]["status"] == "BLOCKED" for k in common),
        "hidden": sum(bool(before[k].get("formatted_hides_it")) for k in common),
        "categories": {
            c: (sum(before[k]["status"] == "PASS" for k in ks) / len(ks), sum(ok(after[k]) for k in ks) / len(ks), len(ks))
            for c, ks in sorted(cats.items())
        },
    }


SNAPSHOT_FIELDS = (
    "case_id", "suite", "category", "severity", "voice", "engine", "text", "critical", "value", "status", "method",
    "reason", "heard_span", "verbatim", "formatted", "formatted_hides_it", "needs_ear_check", "error",
)


def snapshot() -> list[Path]:
    """Copy the headline runs into results/ as text only (no audio), for a fresh clone with no API key."""
    h = headline()
    written = []
    for name in (h["base"], h["safe"]):
        src, dst = RUNS_DIR / name, SNAPSHOT_DIR / name
        dst.mkdir(parents=True, exist_ok=True)
        with (dst / "scored.jsonl").open("w") as out:
            for r in load_scored(src):
                row = {k: r[k] for k in SNAPSHOT_FIELDS if k in r}
                row["accept"] = r["accept"][:3]
                if r.get("safespeak"):
                    s = r["safespeak"]
                    row["safespeak"] = {"status": s["status"], "spoken_text": s["spoken_text"], "alerts": s["alerts"]}
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
        (dst / "run.json").write_text((src / "run.json").read_text())
        written.append(dst)
    return written


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("clips")
    c.add_argument("run_dir")
    c.add_argument("prefix")
    c.add_argument("case_ids", nargs="+")
    sub.add_parser("scorecard")
    sub.add_parser("headline")
    sub.add_parser("snapshot")
    args = p.parse_args()
    if args.cmd == "clips":
        for path in export_clips(Path(args.run_dir), args.prefix, args.case_ids):
            print(path.relative_to(ROOT))
    elif args.cmd == "snapshot":
        for d in snapshot():
            print(d.relative_to(ROOT))
    elif args.cmd == "headline":
        print(json.dumps(headline(), indent=2))
    else:
        print(scorecard().relative_to(ROOT))


if __name__ == "__main__":
    main()
