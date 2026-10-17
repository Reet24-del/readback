"""Day-1 end-to-end check: text -> TTS -> WAV -> both STT passes.

    python -m readback.smoke "Take 0.5 mg of Clonazepam at night." --voice anna
"""

from __future__ import annotations

import argparse
import time

from readback.config import RUNS_DIR
from readback.numparse import find_numbers
from readback.stt import transcribe_formatted, transcribe_verbatim
from readback.tts import ENGINES


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("text", nargs="?", default="Take 0.5 mg of Clonazepam at night.")
    p.add_argument("--voice", default="anna")
    p.add_argument("--engine", default="voice-agent", choices=sorted(ENGINES))
    p.add_argument("--no-cache", action="store_true", help="always call the TTS, even if cached")
    p.add_argument("--skip-stt", action="store_true", help="only synthesize")
    args = p.parse_args()

    engine = ENGINES[args.engine](use_cache=not args.no_cache)

    t0 = time.perf_counter()
    clip = engine.synthesize(args.text, args.voice)
    wav = clip.save_wav(RUNS_DIR / "smoke" / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.voice}.wav")
    print(f"input        : {args.text!r}")
    print(f"voice        : {args.voice} ({args.engine})")
    print(f"audio        : {clip.duration_ms} ms -> {wav}")
    print(f"engine says  : {clip.engine_text!r}")
    timed = [f"{w.text}@{w.start_ms}-{w.end_ms}" for w in clip.words]
    print(f"word timings : {' '.join(timed) or '(none)'}")
    print(f"tts time     : {time.perf_counter() - t0:.1f}s")

    if args.skip_stt:
        return

    verbatim = transcribe_verbatim(clip)
    print(f"\nheard (verbatim) : {verbatim.text!r}")
    for n in find_numbers(verbatim.text):
        print(f"  number span {n.text!r}: value={n.value} digits={n.digits}")

    formatted = transcribe_formatted(clip)
    print(f"heard (formatted): {formatted.text!r}")


if __name__ == "__main__":
    main()
