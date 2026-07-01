import uuid

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from signals import (
    groq_linguistic_signal,
    stylometric_signal,
    combined_confidence,
    transparency_label,
)
from audit import log_entry, get_log, update_entry, utc_now

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],            # no global limit; only /submit is rate-limited
    storage_uri="memory://",      # in-memory (per-process) store, fine for local dev
)


@app.errorhandler(429)
def ratelimited(e):
    return jsonify({"error": "rate limit exceeded — slow down and try again shortly"}), 429


@app.route("/")
def home():
    return "Provenance Guard is running."


@app.post("/submit")
@limiter.limit("10 per minute;100 per day")
def submit():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    creator_id = (body.get("creator_id") or "").strip()

    if not text or not creator_id:
        return jsonify({"error": "both 'text' and 'creator_id' are required"}), 400

    content_id = str(uuid.uuid4())

    # Run both detection signals and combine them into a real confidence score.
    stylo = stylometric_signal(text)            # signal 1: {score, ...}
    groq = groq_linguistic_signal(text)         # signal 2: {score, hedging, specificity}
    result = combined_confidence(stylo, groq)
    label_text = transparency_label(result["confidence"])

    log_entry({
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": utc_now(),
        "attribution": result["attribution"],
        "confidence": result["confidence"],      # combined human-likelihood
        "stylometric_score": stylo["score"],      # signal 1, individual
        "llm_score": groq["score"],               # signal 2, individual
        "transparency_label": label_text,         # what the reader was shown
        "status": "classified",
    })

    return jsonify({
        "content_id": content_id,
        "attribution": result["attribution"],
        "confidence": result["confidence"],
        "transparency_label": label_text,        # reader-facing text; varies with the score
        "signals": result["signals"],            # both individual scores, for transparency
    })


@app.post("/appeal")
def appeal():
    body = request.get_json(silent=True) or {}
    content_id = (body.get("content_id") or "").strip()
    creator_reasoning = (body.get("creator_reasoning") or "").strip()

    if not content_id or not creator_reasoning:
        return jsonify({"error": "both 'content_id' and 'creator_reasoning' are required"}), 400

    # Update the original audit entry in place: flip status and attach the
    # appeal, preserving all original decision fields. No re-classification.
    updated = update_entry(
        content_id,
        status="under_review",
        appeal_reasoning=creator_reasoning,
        appeal_timestamp=utc_now(),
    )
    if not updated:
        return jsonify({"error": f"no content found with id '{content_id}'"}), 404

    return jsonify({
        "content_id": content_id,
        "status": "under_review",
        "message": "Your appeal has been received. This content is now under review by a human moderator.",
    })


@app.get("/log")
def log():
    return jsonify({"entries": get_log()})


if __name__ == "__main__":
    app.run(port=5000, debug=True)
