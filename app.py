import uuid

from flask import Flask, request, jsonify

from signals import groq_linguistic_signal, stylometric_signal, combined_confidence
from audit import log_entry, get_log, utc_now

app = Flask(__name__)


@app.route("/")
def home():
    return "Provenance Guard is running."


@app.post("/submit")
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

    log_entry({
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": utc_now(),
        "attribution": result["attribution"],
        "confidence": result["confidence"],      # combined human-likelihood
        "stylometric_score": stylo["score"],      # signal 1, individual
        "llm_score": groq["score"],               # signal 2, individual
        "status": "classified",
    })

    return jsonify({
        "content_id": content_id,
        "attribution": result["attribution"],
        "confidence": result["confidence"],
        "label": result["label"],
        "signals": result["signals"],            # both individual scores, for transparency
    })


@app.get("/log")
def log():
    return jsonify({"entries": get_log()})


if __name__ == "__main__":
    app.run(port=5000, debug=True)
