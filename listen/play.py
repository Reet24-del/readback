"""Play each flagged case twice: plain TTS, then SafeSpeak.

    .venv/bin/python listen/play.py --auto  # all 13 pairs, no key presses needed
    .venv/bin/python listen/play.py         # step through: Enter = next pair, r = replay, q = quit
    .venv/bin/python listen/play.py 7       # start at pair 7 (works with --auto too)
"""

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
SCREEN = {  # what the screen shows for the attack cases, whose text hides invisible characters
    "atk-rlo-amount": "₹500 (the text hides a right-to-left override)",
    "atk-wordjoiner-otp": "OTP 482910 (the text hides invisible word joiners)",
    "atk-ssml-sub": "₹5 (the text hides an SSML tag)",
}


def play(path: Path) -> None:
    subprocess.run(["afplay", str(path)], check=False)


def main() -> None:
    pairs = json.loads((HERE / "pairs.json").read_text())
    auto = "--auto" in sys.argv
    numbers = [a for a in sys.argv[1:] if a.isdigit()]
    i = int(numbers[0]) - 1 if numbers else 0
    while 0 <= i < len(pairs):
        p = pairs[i]
        print(f"\n{'─' * 72}\n{p['n']:>2}/{len(pairs)}  {p['bug']}  ·  {p['case']}  ·  voice {p['voice']}")
        print(f"   Written:          {SCREEN.get(p['case'], p['critical'])}")
        print(f"   Plain TTS heard:  {p['plain_heard']}")
        print("   ▶ playing PLAIN TTS…", flush=True)
        play(HERE / f"{p['stem']}-1-plain.wav")
        print(f"   SafeSpeak said:   {p['safe_said']}")
        print("   ▶ playing SAFESPEAK…", flush=True)
        play(HERE / f"{p['stem']}-2-safespeak.wav")
        if auto:
            time.sleep(2)
            i += 1
            continue
        answer = input("   Enter = next · r = replay · q = quit: ").strip().lower()
        if answer == "q":
            break
        if answer != "r":
            i += 1
    print("\nDone. Tell Claude which plain clips really sounded wrong.")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.")
