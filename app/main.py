from pathlib import Path

from flask import Flask, jsonify, render_template, request

from app.analyzer import analyze_integration

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = Flask(
    __name__,
    template_folder=str(TEMPLATES_DIR),
    static_folder=str(STATIC_DIR)
)


@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json(silent=True) or {}

    error_text = data.get("error_text", "")
    payload_text = data.get("payload_text", "")
    api_response_text = data.get("api_response_text", "")

    if not error_text.strip():
        return jsonify({
            "success": False,
            "message": "Error text is required."
        }), 400

    result = analyze_integration(
        error_text=error_text,
        payload_text=payload_text,
        api_response_text=api_response_text,
    )

    return jsonify({
        "success": True,
        "result": result
    })