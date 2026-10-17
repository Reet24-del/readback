"""Play each flagged case twice: plain TTS, then SafeSpeak.

    .venv/bin/python listen/play.py        # all 13 pairs
    .venv/bin/python listen/play.py 7      # start at pair 7

Enter = next pair, r = replay this pair, q = quit.
"""

import json
import subprocess
import sys
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
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    i = start - 1
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
        answer = input("   Enter = next · r = replay · q = quit: ").strip().lower()
        if answer == "q":
            break
        if answer != "r":
            i += 1
    print("\nDone. Tell Claude which plain clips really sounded wrong.")


if __name__ == "__main__":
    main()
