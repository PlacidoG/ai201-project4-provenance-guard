"""Unit test for the transparency label generator (M5).

Pure function test — no API, no Groq. Confirms all THREE variants are produced,
that the text matches what's written in planning.md, and that the displayed
percentage scales with the score (so the label is not constant).

Run:  python test_labels.py
"""

import sys

from signals import transparency_label

# Labels contain emoji; force UTF-8 so printing works on a Windows cp1252 console.
sys.stdout.reconfigure(encoding="utf-8")

# (confidence score, expected band marker, expected percentage shown)
CASES = [
    (0.12, "Likely AI-Generated", 88),   # AI variant: ai_pct = round((1-0.12)*100)
    (0.40, "Inconclusive", 40),          # uncertain variant: human_pct = 40
    (0.90, "Likely Human-Written", 90),  # human variant: human_pct = 90
]


def main():
    seen = set()
    for score, marker, pct in CASES:
        text = transparency_label(score)
        print(f"\nconfidence={score}")
        print(text)
        assert marker in text, f"expected '{marker}' for score {score}"
        assert f"{pct}%" in text, f"expected '{pct}%' in label for score {score}"
        seen.add(marker)

    # The three variants must be distinct text.
    assert len(seen) == 3, "expected three distinct label variants"
    a, b = transparency_label(0.10), transparency_label(0.95)
    assert a != b, "label must change with the score, not be constant"

    print("\nPASS: all three variants reachable, text matches planning.md, "
          "and the label varies with the score.")


if __name__ == "__main__":
    main()
