"""Independent test harness for both detection signals (M3 + M4).

Calls the signal functions DIRECTLY — not through the Flask endpoint — so we
can confirm each returns a score (float in [0,1], not a binary flag) before
integration. M4 adds the stylometric signal and a two-signal comparison on the
SAME inputs to see where the signals agree and where they diverge.

Run:  python test_signals.py
Needs GROQ_API_KEY in .env (for the Groq signal).
"""

from dotenv import load_dotenv
from groq import Groq

from signals import groq_linguistic_signal, stylometric_signal

load_dotenv()

# Contrasting inputs: hedge-heavy/abstract (AI-like) vs specific/direct (human-like),
# plus a short borderline case.
SAMPLES = {
    "clearly_ai": (
        "It is worth noting that, in many ways, technology has profoundly "
        "transformed society. Furthermore, one might argue that it is important "
        "to consider the broad implications. Generally speaking, to some extent, "
        "these developments have reshaped how we live and interact."
    ),
    "clearly_human": (
        "My grandmother's kitchen on Bleecker Street smelled like burnt anise "
        "every Sunday. She'd slap my hand away from the biscotti, swearing in "
        "Calabrian, while the radiator clicked twice before the heat kicked in. "
        "I hated those mornings. I'd give anything for one now."
    ),
    "short_borderline": "The meeting is at three. Bring the report.",
}


def band(score: float) -> str:
    """Map a human-likelihood score to an attribution band (asymmetric)."""
    if score < 0.30:
        return "likely_ai"
    if score > 0.55:
        return "likely_human"
    return "uncertain"


def main():
    client = Groq()
    groq_scores = {}
    stylo_scores = {}

    print("########## SIGNAL 1 — Groq (semantic) ##########")
    for name, text in SAMPLES.items():
        out = groq_linguistic_signal(text, client)
        groq_scores[name] = out["score"]
        print(f"\n=== {name} ===")
        print(text)
        print("->", out)

    print("\n\n########## SIGNAL 2 — stylometric (local, 3 metrics) ##########")
    for name, text in SAMPLES.items():
        out = stylometric_signal(text)
        stylo_scores[name] = out["score"]
        print(f"\n=== {name} ===")
        print(text)
        print("->", out)

    print("\n\n########## TWO-SIGNAL COMPARISON (same inputs) ##########")
    header = f"{'input':<18}{'groq':>7}{'stylo':>8}   {'groq_band':<14}{'stylo_band':<14}verdict"
    print(header)
    print("-" * len(header))
    for name in SAMPLES:
        g = groq_scores[name]
        s = stylo_scores[name]
        gb, sb = band(g), band(s)
        verdict = "AGREE" if gb == sb else "DIVERGE"
        print(f"{name:<18}{g:>7.2f}{s:>8.2f}   {gb:<14}{sb:<14}{verdict}")

    print(
        "\nReading the divergences tells you each signal's strengths: where Groq "
        "catches semantic tells (hedging/abstraction) that stylometry misses, and "
        "where short/low-reliability text makes stylometry abstain."
    )


if __name__ == "__main__":
    main()
