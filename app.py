"""
app.py - Flask backend for the GradeMate GPA & CGPA chatbot.

Routes
    GET  /             the web page
    POST /chat         chatbot conversation (JSON in, JSON out)
    POST /calculate    structured calculator requests from the forms
    GET  /grade-scale  the default grade scale (single source of truth)

Run:  python app.py      then open  http://127.0.0.1:5000
Everything works offline - there is no API key anywhere in this project.
"""

import logging
import os
import sys

from flask import Flask, jsonify, render_template, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from chatbot import calculator          # noqa: E402
from chatbot.chatbot import GPAChatbot, MAX_MESSAGE_LENGTH  # noqa: E402

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024      # reject huge requests
app.json.sort_keys = False                          # keep grades in A+, A, A- ... order
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

bot = GPAChatbot()          # loads (or, if missing, trains) the local model


def json_body():
    """Return the request's JSON object, or None if it is missing/invalid."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def bad_request(message, status=400):
    return jsonify({"ok": False, "error": message}), status


# ----------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/grade-scale", methods=["GET"])
def grade_scale():
    return jsonify({"ok": True, "scale": calculator.get_grade_scale(),
                    "max_gpa": calculator.MAX_GPA})


@app.route("/chat", methods=["POST"])
def chat():
    data = json_body()
    if data is None:
        return bad_request("Please send a JSON body such as {\"message\": \"hello\"}.")

    session_id = str(data.get("session_id") or "default")[:64]

    if data.get("reset") is True:               # the Reset button
        bot.reset_session(session_id)
        return jsonify({"ok": True, "reset": True})

    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        return bad_request("The message is empty. Please type something.")
    if len(message) > MAX_MESSAGE_LENGTH:
        return bad_request(f"The message is too long (maximum {MAX_MESSAGE_LENGTH} characters).", 413)

    try:
        reply = bot.respond(message, session_id=session_id, scale=data.get("grade_scale"))
    except Exception:
        app.logger.exception("Chat failure")
        return bad_request("Sorry, something went wrong while reading that message. Please try again.", 500)
    reply["ok"] = True
    return jsonify(reply)


@app.route("/calculate", methods=["POST"])
def calculate():
    data = json_body()
    if data is None:
        return bad_request("Please send a JSON body.")

    kind = str(data.get("type", "")).lower()
    try:
        if kind == "gpa":
            result = calculator.calculate_gpa(data.get("courses"), data.get("grade_scale"))
        elif kind == "cgpa":
            result = calculator.calculate_cgpa(data.get("current_cgpa"), data.get("completed_credits"),
                                               data.get("semester_gpa"), data.get("semester_credits"))
        elif kind in ("target", "planner"):
            result = calculator.calculate_required_gpa(data.get("current_cgpa"), data.get("completed_credits"),
                                                       data.get("target_cgpa"), data.get("remaining_credits"),
                                                       data.get("grade_scale"))
        else:
            return bad_request("Unknown calculation type. Use 'gpa', 'cgpa' or 'target'.")
    except Exception:
        app.logger.exception("Calculation failure")
        return bad_request("Sorry, the calculation could not be completed.", 500)

    if not result.get("ok"):
        return jsonify(result), 422          # valid JSON, but the numbers are not acceptable
    return jsonify(result)


# ----------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(_):
    if request.path.startswith(("/chat", "/calculate", "/grade-scale")):
        return bad_request("Not found.", 404)
    return render_template("index.html"), 404


@app.errorhandler(405)
def method_not_allowed(_):
    return bad_request("This URL does not support that method.", 405)


@app.errorhandler(413)
def too_large(_):
    return bad_request("The request is too large.", 413)


@app.errorhandler(500)
def server_error(_):
    return bad_request("Unexpected server error. Please try again.", 500)


@app.route("/health", methods=["GET"])
def health():
    """Simple health endpoint for hosting platforms and uptime checks."""
    return jsonify({"ok": True, "service": "GradeMate", "status": "healthy"})


if __name__ == "__main__":
    # 127.0.0.1 is convenient for local use; hosted platforms provide PORT
    # and require the app to listen on all interfaces.
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    print(f"\nGradeMate is starting...  Open http://{host}:{port} in your browser\n")
    app.run(host=host, port=port, debug=False)
