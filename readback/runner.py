"""Run test cases through TTS and both STT passes, one results.jsonl row per case × voice.

    python -m readback.runner --suite medical --voices anna --limit 3
    python -m readback.runner --suite money,generated --voices anna,alba,george
    python -m readback.runner --ids money-001,med-001

TTS audio and STT results are cached by content, so re-running never re-bills.
Output goes to runs/<timestamp>-<engine>/ and runs/latest points at the newest run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from readback import cases as case_lib
from readback.config import RUNS_DIR
from readback.numparse import find_numbers
from readback.stt import cached_transcribe as cached_stt
from readback.tts import DEFAULT_VOICES, ENGINES


async def run_one(case: case_lib.Case, voice: str, engine, run_dir: Path, sem: asyncio.Semaphore, args) -> dict:
    row = {
        "case_id": case.id,
        "suite": case.suite,
        "category": case.category,
        "severity": case.severity,
        "voice": voice,
        "engine": engine.name,
        "text": case.text,
        "critical": case.critical,
        "value": case.value,
        "accept": case.accept_forms(),
        "status": "unscored",
        "error": None,
    }
    async with sem:
        try:
            if args.safespeak:
                return await _run_safespeak(row, case, voice, engine, run_dir, args)
            clip = await engine.asynthesize(case.text, voice)
            wav = clip.save_wav(run_dir / "audio" / f"{case.id}--{voice}.wav")
            row.update(
                wav=str(wav.relative_to(run_dir)),
                duration_ms=clip.duration_ms,
                engine_text=clip.engine_text,
                tts_words=clip.words_as_dicts(),
            )
            if not args.skip_stt:
                verbatim, formatted = await asyncio.gather(
                    asyncio.to_thread(cached_stt, "verbatim", clip, not args.no_cache),
                    asyncio.to_thread(cached_stt, "formatted", clip, not args.no_cache),
                )
                row.update(
                    verbatim=verbatim["text"],
                    verbatim_words=verbatim["words"],
                    formatted=formatted["text"],
                    numbers=[
                        {"text": n.text, "value": n.value, "digits": n.digits, "ordinal": n.ordinal}
                        for n in find_numbers(verbatim["text"])
                    ],
                )
        except Exception as e:  # one failed case must not sink the run
            row["error"] = f"{type(e).__name__}: {e}"
    return row


async def _run_safespeak(row: dict, case: case_lib.Case, voice: str, engine, run_dir: Path, args) -> dict:
    """Same case, but spoken through SafeSpeak; verbatim is what the final attempt sounded like."""
    from readback.safespeak import speak

    result = await speak(case.text, voice, engine, use_cache=not args.no_cache)
    wav = result.clip.save_wav(run_dir / "audio" / f"{case.id}--{voice}.wav")
    row.update(
        wav=str(wav.relative_to(run_dir)),
        duration_ms=result.clip.duration_ms,
        engine_text=result.clip.engine_text,
        tts_words=result.clip.words_as_dicts(),
        verbatim=result.heard,
        formatted=None,
        numbers=[{"text": n.text, "value": n.value, "digits": n.digits, "ordinal": n.ordinal} for n in find_numbers(result.heard)],
        safespeak={
            "status": result.status,
            "spoken_text": result.plan.spoken_text,
            "sanitized": result.plan.sanitized.text,
            "alerts": result.alerts,
            "attempts": result.attempts,
        },
    )
    return row


async def run(args) -> dict:
    selected = case_lib.load(args.suite.split(","))
    if args.ids:
        wanted = set(args.ids.split(","))
        selected = [c for c in selected if c.id in wanted]
        if missing := wanted - {c.id for c in selected}:
            raise SystemExit(f"unknown case ids: {', '.join(sorted(missing))}")
    if args.limit:
        selected = selected[: args.limit]
    voices = args.voices.split(",")
    jobs = [(c, v) for c in selected for v in voices]
    if not jobs:
        raise SystemExit("nothing to run")

    engine = ENGINES[args.engine](use_cache=not args.no_cache)
    run_dir = RUNS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{engine.name}{'-safespeak' if args.safespeak else ''}"
    run_dir.mkdir(parents=True)
    manifest = {
        "engine": engine.name,
        "suites": args.suite,
        "voices": voices,
        "cases": len(selected),
        "jobs": len(jobs),
        "safespeak": args.safespeak,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    print(f"{len(selected)} cases × {len(voices)} voices = {len(jobs)} jobs -> {run_dir.relative_to(RUNS_DIR.parent)}")

    sem = asyncio.Semaphore(args.concurrency)
    errors = 0
    with (run_dir / "results.jsonl").open("w") as out:
        tasks = [asyncio.create_task(run_one(c, v, engine, run_dir, sem, args)) for c, v in jobs]
        for i, task in enumerate(asyncio.as_completed(tasks), 1):
            row = await task
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            if row["error"]:
                errors += 1
                heard = f"ERROR {row['error'][:90]}"
            else:
                heard = repr(row.get("verbatim", row.get("engine_text", "")))[:90]
            print(f"[{i:>3}/{len(jobs)}] {row['case_id']:<16} {row['voice']:<8} {heard}", flush=True)

    manifest.update(finished=time.strftime("%Y-%m-%dT%H:%M:%S%z"), errors=errors)
    (run_dir / "run.json").write_text(json.dumps(manifest, indent=2))
    latest = RUNS_DIR / "latest"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(run_dir.name)
    print(f"\ndone: {len(jobs) - errors} ok, {errors} errors -> {run_dir.relative_to(RUNS_DIR.parent)}/results.jsonl")
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--suite", default="all", help=f"comma-separated, or 'all'. Suites: {', '.join(case_lib.suite_names())}")
    p.add_argument("--ids", help="comma-separated case ids to run (within --suite)")
    p.add_argument("--voices", default=",".join(DEFAULT_VOICES), help="comma-separated voice ids")
    p.add_argument("--engine", default="voice-agent", choices=sorted(ENGINES))
    p.add_argument("--limit", type=int, help="run only the first N cases")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--skip-stt", action="store_true", help="synthesize only")
    p.add_argument("--safespeak", action="store_true", help="speak every case through SafeSpeak (sanitize, spell out, verify)")
    p.add_argument("--no-cache", action="store_true", help="ignore cached TTS/STT results")
    args = p.parse_args()
    manifest = asyncio.run(run(args))
    if manifest["errors"] == manifest["jobs"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
