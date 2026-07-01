# Provenance Guard

A backend service that any creative-sharing platform can plug in to classify submitted text as human-written or AI-generated, score its confidence, surface a plain-language transparency label, and let creators appeal a classification they believe is wrong. The goal is not to police creativity — it's to protect attribution and give readers honest context.

---

## 1. Overview

Provenance Guard exposes a small Flask API. A submission runs through **two heterogeneous detection signals**, their scores are combined into a single **confidence score**, that score maps to one of three **transparency labels**, and every decision is written to a structured **audit log**. Creators can **appeal**, which flags the record for human review. The submission endpoint is **rate-limited** to prevent scripted abuse.

```
POST /submit  ──▶  Signal 1 (stylometric)  +  Signal 2 (Groq)  ──▶  combined confidence
                        │                                                    │
                        └──────────────▶  transparency label  ◀─────────────┘
                                                 │
                        audit log  ◀─────────────┘        POST /appeal ──▶ status: under_review
```

## 2. Setup & Run

```bash
pip install -r requirements.txt

# .env in the project root:
#   GROQ_API_KEY=your_key_here

python app.py            # serves on http://localhost:5000
```

Dependencies: `flask`, `flask-limiter`, `groq`, `python-dotenv`.

## 3. API Endpoints

| Method & path | Body | Returns |
|---|---|---|
| `POST /submit` | `{ "text": "...", "creator_id": "..." }` | `content_id`, `attribution`, `confidence`, `transparency_label`, `signals` |
| `POST /appeal` | `{ "content_id": "...", "creator_reasoning": "..." }` | `content_id`, `status`, message |
| `GET /log` | — | `{ "entries": [...] }`, most-recent-first |

**Example — `POST /submit`:**

```bash
curl -s -X POST http://localhost:5000/submit -H "Content-Type: application/json" \
  -d '{"text": "The sun dipped below the horizon...", "creator_id": "test-user-1"}'
```
```json
{
  "content_id": "68035dd5-2080-4640-b1cb-ea7c6843db30",
  "attribution": "likely_human",
  "confidence": 0.69,
  "transparency_label": "✓ Likely Human-Written. ...",
  "signals": { "stylometric": 0.5154, "llm": 0.8 }
}
```

## 4. Detection Signals

The pipeline uses **two deliberately different signals** so their blind spots only partially overlap. One is local/statistical and free; the other is semantic and API-backed. Either can catch what the other misses.

### Signal 1 — Stylometric (local, no API cost)

Combines three metrics into one human-likelihood score in `[0,1]` (weights `0.50 / 0.25 / 0.25`):

- **Sentence-length burstiness** `B = (σ−μ)/(σ+μ)` — humans vary sentence pace for effect; LLMs cluster in a narrow "comfortable" range.
- **Type-token ratio** — lexical diversity; low-temperature LLMs reuse stock vocabulary.
- **Punctuation diversity** — humans use varied, idiosyncratic punctuation (—, ;, parentheses); LLMs lean on commas and periods.

**Why chosen:** it needs no network, costs nothing, can't be rate-limited, and measures *form* — a dimension the semantic signal ignores. **Blind spots:** genre dominates (uniform journalism/legal/academic prose reads AI-like); type-token ratio is length-confounded (short texts inflate toward "human"); it's purely formal, so an AI told to "vary your rhythm" defeats it. It also abstains below 3 sentences.

### Signal 2 — Groq LLM: hedging density + specificity (semantic)

A structured Groq prompt (`llama-3.3-70b-versatile`) returns two 0–1 sub-scores: **hedging density** (epistemic hedges and generic transitions like "it is worth noting", "furthermore") and **specificity** (concrete, lived detail vs. abstraction). Low hedging + high specificity ⇒ human-like.

**Why chosen:** it reads *meaning*, catching AI tells that stylometry can't — e.g. an AI text with varied sentence rhythm but generic, hedged content. **Blind spots:** academic/professional writing hedges by convention (false positives); blog prose mirrors LLM conventions; there's a circularity risk (an LLM judging LLM-ness); short texts raise its hallucination rate.

## 5. Confidence Scoring

Each signal outputs a human-likelihood in `[0,1]`. They're combined by weighted average:

```
confidence = 0.4 · stylometric + 0.6 · Groq
```

**Why this approach.** Groq gets the larger weight because it's semantic and, in testing, more discriminating; the stylometric signal structurally rarely exceeds ~0.5 on its own (sentence-length CV is almost always < 1, so raw burstiness is usually negative). On texts under 3 sentences the stylometric weight drops to 0 — it's statistically meaningless there.

The combined score maps to three bands via **creator-protective, asymmetric thresholds**:

```
confidence < 0.30   →  likely_ai       (strong evidence required to accuse)
0.30 – 0.55         →  uncertain       (wide band; protects attribution)
confidence > 0.55   →  likely_human
```

The band is intentionally asymmetric: a false "AI" label harms a real creator more than a false "human" pass, so we demand more evidence to accuse. `confidence` is an *expressed confidence indicator*, not a calibrated statistical posterior — the labels always say "likely," never "certainly."

**Meaningful variation (real numbers, from Milestone 4 testing):**

| Case | stylometric | Groq | **combined** | label |
|---|---|---|---|---|
| Casual "ramen review" (higher confidence) | 0.56 | 0.80 | **0.71** | `likely_human` |
| "Remote work" lightly-edited AI (lower confidence) | 0.51 | 0.25 | **0.36** | `uncertain` |

The scores are visibly different (0.71 vs 0.36) — the scorer produces a spread, not a constant near 0.5.

## 6. Transparency Label — the Three Variants

The label returned by `/submit` is chosen by band, and the displayed percentage scales with the score (so 0.95 and 0.56 both read "Likely Human-Written" but show different numbers). Exact text produced by `transparency_label()`:

**High-confidence AI** (`confidence < 0.30`; shows AI-confidence = `round((1 − confidence) · 100)`%):
> ⚠️ Likely AI-Generated. Our automated analysis indicates this content was most likely produced with an AI tool. Confidence: `{ai_pct}`%. This is an automated assessment, not a certainty — if you wrote this yourself, you can contest it.

**High-confidence human** (`confidence > 0.55`; shows human-confidence = `round(confidence · 100)`%):
> ✓ Likely Human-Written. Our automated analysis found the hallmarks of human authorship in this content. Confidence: `{human_pct}`%.

**Uncertain** (`0.30 ≤ confidence ≤ 0.55`; shows human-authorship = `round(confidence · 100)`%):
> ❓ Inconclusive. Our system could not determine with confidence whether this content was written by a person or generated with AI assistance. Human-authorship score: `{human_pct}`%. Treat this result as provisional.

## 7. Appeals Workflow

Any creator holding a `content_id` can contest a classification via `POST /appeal` with `creator_reasoning`. The system looks up the content's audit entry and **updates it in place**: `status` → `under_review`, plus `appeal_reasoning` and `appeal_timestamp` — while **preserving every original decision field** (attribution, confidence, both signal scores, the label the reader saw). There is **no automated re-classification**; a human moderator reviews. A reviewer opening the queue sees the original text's decision, both signal scores (which signal drove the verdict), the label shown, and the creator's reasoning.

```bash
curl -s -X POST http://localhost:5000/appeal -H "Content-Type: application/json" \
  -d '{"content_id": "<id>", "creator_reasoning": "I wrote this myself..."}'
```
```json
{ "content_id": "<id>", "status": "under_review",
  "message": "Your appeal has been received. This content is now under review by a human moderator." }
```

## 8. Rate Limiting

`POST /submit` is limited to **10 per minute; 100 per day**, per client IP (in-memory store). `/log` and `/appeal` are unlimited.

**Reasoning — not arbitrary:** a genuine creator submits their own work a handful of times, revising and re-checking; 10/minute is far above that human cadence while still stopping a script that would otherwise fire hundreds of requests a second. The daily cap of 100 bounds sustained abuse (and Groq API cost) while leaving generous headroom for a busy legitimate user. The per-IP key means one abuser can't degrade the service for everyone. A production deployment would additionally key on authenticated account and swap the in-memory store for Redis.

**Evidence** — 12 rapid requests against the 10/min limit:
```
200
200
200
200
200
200
200
200
200
200
429
429
```
The 11th and 12th requests are throttled. The `429` body is JSON: `{"error": "rate limit exceeded — slow down and try again shortly"}`.

## 9. Audit Log

Every submission appends one structured JSONL line (`audit_log.jsonl`, written by `audit.py` — a real file, not console output). Fields: `timestamp`, `content_id`, `creator_id`, `attribution`, `confidence`, `stylometric_score`, `llm_score` (both individual signal scores), `transparency_label`, and `status`. An appeal updates the same record in place, adding `appeal_reasoning` + `appeal_timestamp` and flipping `status` to `under_review`. Retrieve via `GET /log`.

Three live entries (all three bands, plus one appealed record):

```json
{
  "entries": [
    {
      "attribution": "uncertain", "confidence": 0.3292,
      "content_id": "290a2cd7-ebe5-4d59-ac7b-663980e5dce1", "creator_id": "lin-q",
      "llm_score": 0.3, "stylometric_score": 0.373, "status": "classified",
      "timestamp": "2026-07-01T02:35:04.495580Z",
      "transparency_label": "❓ Inconclusive. ... Human-authorship score: 33%. Treat this result as provisional."
    },
    {
      "attribution": "likely_human", "confidence": 0.6862,
      "content_id": "a9d08ff6-cab7-4894-9483-d172c9be1d82", "creator_id": "deshawn-w",
      "llm_score": 0.8, "stylometric_score": 0.5154, "status": "classified",
      "timestamp": "2026-07-01T02:35:03.552076Z",
      "transparency_label": "✓ Likely Human-Written. ... Confidence: 69%."
    },
    {
      "appeal_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical.",
      "appeal_timestamp": "2026-07-01T02:35:04.735068Z",
      "attribution": "likely_ai", "confidence": 0.2695,
      "content_id": "68035dd5-2080-4640-b1cb-ea7c6843db30", "creator_id": "maria-k",
      "llm_score": 0.2, "stylometric_score": 0.3738, "status": "under_review",
      "timestamp": "2026-07-01T02:35:02.698749Z",
      "transparency_label": "⚠️ Likely AI-Generated. ... Confidence: 73%. ... you can contest it."
    }
  ]
}
```

## 10. Known Limitations

**Formal and non-native-English human writing is the clearest failure mode.** In testing, a genuine human academic paragraph (monetary policy) scored `likely_ai` (0.20). This is not random error — it's a direct consequence of the signals:

- **Signal 2 (Groq)** reads scholarly hedging ("has been extensively studied", "a fundamental tension") and abstraction as AI markers — the documented academic-writing blind spot. It returned 0.20.
- On that short, formal text (2 sentences) **Signal 1 abstains** (weight → 0), so Groq alone decided, with nothing to moderate it.

Non-native English speakers are especially exposed: ESL writing often favors uniform structure and formulaic transitions, tripping both signals toward AI. This is an equity risk, and it's precisely why the thresholds are creator-protective and why the appeals workflow exists as the human safety net. (A live example of exactly this appeal is in the audit log above.)

## 11. Spec Reflection

**How the spec helped.** Writing the false-positive trace in `planning.md` *before* coding — walking a real human's formal paragraph through the system — is what forced the creator-protective **asymmetric thresholds** (`0.30/0.55`, not a symmetric `0.5` split) and the "always say *likely*" label wording. Designing that failure case on paper shaped the confidence and label logic before a line of scoring was written.

**How the implementation diverged.** The spec originally said appeals should "**append** an appeal record alongside — never overwriting — the original decision." The implementation instead **updates the original audit entry in place** (flipping `status`, adding the appeal fields). Why: the acceptance test required `GET /log` to show *the content's entry itself* as `under_review` with `appeal_reasoning` populated. In-place update satisfies that while still never destroying the original decision — all classification fields are preserved — so the spec's intent (an immutable original decision, visibly appealed) holds even though the mechanism changed.

## 12. AI Usage

This project was built with an AI coding assistant, milestone by milestone. Specific instances:

1. **Signal design.** I directed the assistant to propose two *heterogeneous* detection signals and to state each one's blind spot. It produced sentence-length burstiness + a Groq hedging/specificity signal. I **revised** the first: rather than a single burstiness metric, I had it expand Signal 1 into three stylometric metrics (burstiness + type-token ratio + punctuation diversity) combined `0.50/0.25/0.25`, to reduce reliance on any one brittle statistic.

2. **Confidence calibration.** I directed it to implement the combined scorer and test four deliberately chosen inputs. The formal-human input scored `likely_ai`; the assistant printed both signal scores, diagnosed that the stylometric signal was abstaining and leaving Groq unchecked, and **recommended a code change** ("damp lone-signal accusations" — treat an abstaining signal as a neutral vote). I **overrode** that recommendation: I chose to keep the scoring unchanged and rely on the appeals workflow instead, to avoid overfitting the combiner to a handful of examples. That decision is recorded in `planning.md`'s calibration findings.

3. **Appeals storage.** The assistant first followed the spec's "append a separate appeal record" design. I **redirected** it to update the existing audit entry in place (so `GET /log` shows the entry as `under_review`) while preserving the original decision fields — the divergence documented in section 11.
