import re
import json
from groq import Groq


# ---------------------------------------------------------------------------
# Signal 1: Sentence-Length Burstiness (statistical, no API cost)
#
# Measures the burstiness coefficient B = (σ − μ) / (σ + μ) of sentence
# lengths. LLMs produce sentences in a narrow "comfortable" range (low
# burstiness); human writers vary pace dramatically for rhetorical effect
# (high burstiness). Score is normalized to [0, 1] where 1 = human-like.
#
# Blind spots: genre dominates (AP journalism, legal text look AI-like);
# unreliable on short texts (<6 sentences); Hemingway-style minimalism
# scores as AI; prompting AI to vary rhythm fools this signal entirely.
# ---------------------------------------------------------------------------

def sentence_burstiness(text: str) -> dict:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    lengths = [len(s.split()) for s in sentences if s.strip()]

    if len(lengths) < 3:
        return {
            "score": 0.5,
            "confidence": "low",
            "reason": "too_few_sentences",
            "sentence_count": len(lengths),
        }

    mu = sum(lengths) / len(lengths)
    variance = sum((l - mu) ** 2 for l in lengths) / len(lengths)
    sigma = variance ** 0.5

    if mu + sigma == 0:
        return {
            "score": 0.5,
            "confidence": "low",
            "reason": "degenerate_distribution",
            "sentence_count": len(lengths),
        }

    B = (sigma - mu) / (sigma + mu)
    # B in [-1, +1]; higher = more irregular = more human-like
    # Map to [0, 1]: score of 1 means confident human, 0 means confident AI
    normalized = (B + 1) / 2

    return {
        "score": round(normalized, 4),
        "burstiness": round(B, 4),
        "mean_length": round(mu, 2),
        "std_length": round(sigma, 2),
        "sentence_count": len(lengths),
        "confidence": "high" if len(lengths) >= 6 else "medium",
    }


# ---------------------------------------------------------------------------
# Signal 2: Groq LLM — Hedging Density and Specificity Ratio
#
# Measures two sub-properties via structured Groq prompt:
#   1. Hedging density: frequency of epistemic hedges ("it is worth noting",
#      "one might argue") and generic transitions ("Furthermore"). LLMs hedge
#      constantly due to RLHF training penalizing overconfident wrong answers.
#   2. Specificity ratio: proportion of concrete, personal, verifiable details
#      vs abstract generalizations. LLMs default to abstraction because they
#      lack the grounded personal experience that produces specific detail.
# Score of 1 = human-like (direct, specific); 0 = AI-like (hedged, abstract).
#
# Blind spots: academic/professional writing institutionally requires hedging;
# blog conventions mirror LLM patterns; circularity risk (LLM judging LLM);
# lyric poetry is structurally low-specificity; short texts increase scoring
# hallucination risk.
# ---------------------------------------------------------------------------

_HEDGING_PROMPT = """\
Analyze the following text for two properties. Return ONLY a JSON object with \
these exact keys — no explanation, no markdown, just the JSON.

"hedging_score": float 0.0–1.0
  1.0 = saturated with epistemic hedges and generic transitions \
("it is worth noting", "one might argue", "furthermore", "in many ways", \
"to some extent", "it is important to consider").
  0.0 = direct claims, no hedging.

"specificity_score": float 0.0–1.0
  1.0 = full of concrete, personal, verifiable details (named places, \
sensory particulars, specific times, proper nouns from lived experience).
  0.0 = all abstract generalizations.

Text:
\"\"\"
{text}
\"\"\"\
"""


def groq_linguistic_signal(text: str, client: Groq) -> dict:
    prompt = _HEDGING_PROMPT.format(text=text[:3000])
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    result = json.loads(raw)

    hedging = float(result.get("hedging_score", 0.5))
    specificity = float(result.get("specificity_score", 0.5))

    # High hedging + low specificity → AI-like → low human_score
    ai_likelihood = (hedging + (1.0 - specificity)) / 2.0
    human_score = 1.0 - ai_likelihood

    return {
        "score": round(human_score, 4),
        "hedging": round(hedging, 4),
        "specificity": round(specificity, 4),
    }


# ---------------------------------------------------------------------------
# Combiner: weighted average, down-weighting burstiness on short texts
# ---------------------------------------------------------------------------

def combined_confidence(sig1: dict, sig2: dict) -> dict:
    # Signal 1 is statistically unreliable below 3 sentences
    w1 = 0.0 if sig1.get("sentence_count", 0) < 3 else 0.4
    w2 = 0.6
    total_weight = w1 + w2

    score = (w1 * sig1["score"] + w2 * sig2["score"]) / total_weight

    if score > 0.6:
        label = "human"
    elif score < 0.4:
        label = "ai"
    else:
        label = "uncertain"

    return {
        "human_confidence": round(score, 4),
        "label": label,
        "signals": {
            "burstiness": sig1,
            "linguistic": sig2,
        },
    }
