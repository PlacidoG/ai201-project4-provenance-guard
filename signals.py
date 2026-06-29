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
# Signal 2 (stylometric, statistical, no API cost): combines THREE local
# metrics into one human-likelihood score in [0, 1].
#
#   1. Sentence-length burstiness (reuses sentence_burstiness) — humans vary
#      sentence pace; LLMs cluster in a narrow "comfortable" range.
#   2. Type-token ratio (lexical diversity) — humans draw on a wider, more
#      surprising vocabulary; low-temperature LLMs reuse stock wording.
#   3. Punctuation diversity — humans deploy varied/idiosyncratic punctuation
#      (—, ;, parentheses, …); LLMs lean on commas and periods.
#
# Combination: weighted average with burstiness primary (it is the most
# robust of the three). The TTR/punctuation ramps are coarse, tunable
# heuristics — part of why the semantic Groq signal carries the larger weight
# in the combiner.
#
# Blind spots: genre dominates burstiness (uniform journalism/legal/academic
# reads AI-like); TTR is length-confounded (short texts inflate toward
# "human", long texts deflate); punctuation diversity needs enough text and is
# defeated by plain human style or punctuation-rich formal AI.
# ---------------------------------------------------------------------------

def stylometric_signal(text: str) -> dict:
    burst = sentence_burstiness(text)          # metric 1, already [0,1] in burst["score"]
    n_sent = burst.get("sentence_count", 0)

    words = re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower())
    n_words = len(words)

    # metric 2: type-token ratio, mapped to a human-likelihood ramp
    ttr = len(set(words)) / n_words if n_words else 0.0
    ttr_human = max(0.0, min((ttr - 0.45) / 0.40, 1.0))

    # metric 3: punctuation diversity (distinct expressive marks present)
    expressive = set(";:—–()?!\"'…")
    distinct = len({ch for ch in text if ch in expressive})
    punct_human = min(distinct / 4, 1.0)

    score = 0.50 * burst["score"] + 0.25 * ttr_human + 0.25 * punct_human

    return {
        "score": round(score, 4),
        "burstiness": burst.get("burstiness"),
        "type_token_ratio": round(ttr, 4),
        "punctuation_diversity": distinct,
        "sentence_count": n_sent,
        "reliability": "low" if n_sent < 3 else ("medium" if n_sent < 6 else "high"),
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


def groq_linguistic_signal(text: str, client: Groq | None = None) -> dict:
    # Allow standalone use (e.g. the test harness) by building a client from
    # the GROQ_API_KEY env var when one is not injected by the caller.
    if client is None:
        client = Groq()

    prompt = _HEDGING_PROMPT.format(text=text[:3000])
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        # Malformed model output: fall back to a neutral score rather than
        # crashing the caller. Surfaced via "error" for the audit log.
        return {"score": 0.5, "hedging": 0.5, "specificity": 0.5, "error": "unparseable_model_output"}

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
# Combiner: weighted average of the two signals, mapped to 3 label categories
# via the creator-protective asymmetric thresholds (see planning.md).
#
# confidence = combined human-likelihood in [0, 1]:
#   1 = confidently human, 0 = confidently AI, 0.5 = maximally uncertain.
# The stylometric signal is down-weighted to 0 on texts < 3 sentences, where
# it is statistically meaningless.
# ---------------------------------------------------------------------------

def combined_confidence(stylo: dict, groq: dict) -> dict:
    w_sty = 0.0 if stylo.get("sentence_count", 0) < 3 else 0.4
    w_llm = 0.6
    confidence = (w_sty * stylo["score"] + w_llm * groq["score"]) / (w_sty + w_llm)

    # Asymmetric, creator-protective bands: stronger evidence required to
    # accuse ("likely_ai") than to clear ("likely_human").
    if confidence < 0.30:
        attribution, label = "likely_ai", "Likely AI-generated"
    elif confidence > 0.55:
        attribution, label = "likely_human", "Likely human-written"
    else:
        attribution, label = "uncertain", "Uncertain"

    return {
        "confidence": round(confidence, 4),     # combined human-likelihood [0,1]
        "attribution": attribution,             # machine value
        "label": label,                         # human-readable category
        "signals": {
            "stylometric": stylo["score"],
            "llm": groq["score"],
        },
    }
