"""Calibration test for the combined confidence score (M4 integration).

Runs both signals + combined_confidence() DIRECTLY on 4 deliberately chosen
inputs and prints all THREE scores separately (stylometric, llm, combined) so
a misbehaving signal is immediately visible.

Run:  python test_scoring.py
Needs GROQ_API_KEY in .env.
"""

from dotenv import load_dotenv

from signals import stylometric_signal, groq_linguistic_signal, combined_confidence

load_dotenv()

INPUTS = {
    "clearly_ai": (
        "Artificial intelligence represents a transformative paradigm shift in modern "
        "society. It is important to note that while the benefits of AI are numerous, it "
        "is equally essential to consider the ethical implications. Furthermore, "
        "stakeholders across various sectors must collaborate to ensure responsible "
        "deployment."
    ),
    "clearly_human": (
        "ok so i finally tried that new ramen place downtown and honestly? underwhelming. "
        "the broth was fine but they put WAY too much sodium in it and i was thirsty for "
        "like three hours after. my friend got the spicy version and said it was better. "
        "probably won't go back unless someone drags me there"
    ),
    "borderline_formal_human": (
        "The relationship between monetary policy and asset price inflation has been "
        "extensively studied in the literature. Central banks face a fundamental tension "
        "between their mandate for price stability and the unintended consequences of "
        "prolonged low interest rates on equity and real estate valuations."
    ),
    "borderline_edited_ai": (
        "I've been thinking a lot about remote work lately. There are genuine tradeoffs — "
        "flexibility and no commute on one side, isolation and blurred work-life boundaries "
        "on the other. Studies show productivity varies widely by individual and role type."
    ),
}

# What I expect before running (intuition):
EXPECTED = {
    "clearly_ai": "likely_ai",
    "clearly_human": "likely_human",
    "borderline_formal_human": "uncertain / likely_human (human, but formal)",
    "borderline_edited_ai": "uncertain (mid-range)",
}


def main():
    rows = []
    for name, text in INPUTS.items():
        stylo = stylometric_signal(text)
        groq = groq_linguistic_signal(text)
        result = combined_confidence(stylo, groq)
        rows.append((name, stylo["score"], groq["score"], result["confidence"], result["attribution"]))

        print(f"\n=== {name} ===")
        print(text)
        print(f"  stylometric : {stylo['score']:.3f}  ({stylo})")
        print(f"  llm (groq)  : {groq['score']:.3f}  ({groq})")
        print(f"  COMBINED    : {result['confidence']:.3f} -> {result['attribution']} ('{result['label']}')")
        print(f"  expected    : {EXPECTED[name]}")

    print("\n\n########## SUMMARY (confidence = combined human-likelihood) ##########")
    header = f"{'input':<26}{'stylo':>7}{'llm':>7}{'combined':>10}   attribution"
    print(header)
    print("-" * len(header))
    for name, s, l, c, attr in rows:
        print(f"{name:<26}{s:>7.2f}{l:>7.2f}{c:>10.2f}   {attr}")

    cats = {attr for *_, attr in rows}
    print(f"\ndistinct categories reached: {sorted(cats)}  (target: >= 3)")
    print(f"combined score range: {min(r[3] for r in rows):.2f} .. {max(r[3] for r in rows):.2f}")


if __name__ == "__main__":
    main()
