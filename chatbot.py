"""
chatbot.py - the conversation pipeline.

    user message
        -> nlp.parse_message()        (local intent model + regex entities)
        -> decide what the user wants
        -> calculator.py              (all maths lives there)
        -> reply dictionary for the web page

CGPA and the Target Planner need four numbers, so the bot can also run a short
guided dialog ("What is your current CGPA?") and remember the answers for the
current browser session.  Nothing is sent over the internet.
"""

import json
import os
import random
import re
import threading
from collections import OrderedDict

from chatbot import calculator
from chatbot import nlp

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTENTS_PATH = os.path.join(BASE_DIR, "data", "intents.json")

MAX_SESSIONS = 500          # old sessions are dropped beyond this number
MAX_MESSAGE_LENGTH = 1000

# Guided dialogs: ordered slots and the question that asks for each one
FLOWS = {
    "cgpa": [
        ("current_cgpa", "What is your **current CGPA**? (0.00 - 4.00)"),
        ("completed_credits", "How many **credit hours have you completed** so far? (use 0 if this is your first semester)"),
        ("semester_gpa", "What is your **new semester GPA**? (0.00 - 4.00)"),
        ("semester_credits", "How many **credit hours** did the new semester have?"),
    ],
    "target": [
        ("current_cgpa", "What is your **current CGPA**? (0.00 - 4.00)"),
        ("completed_credits", "How many **credit hours have you completed** so far?"),
        ("target_cgpa", "What **target CGPA** do you want to reach? (0.00 - 4.00)"),
        ("remaining_credits", "How many **credit hours remain** until you finish?"),
    ],
}
# Order in which unlabeled "<n> credits" mentions fill empty slots
CREDIT_FILL_ORDER = {
    "cgpa": ["completed_credits", "semester_credits"],
    "target": ["completed_credits", "remaining_credits"],
}
FLOW_TITLES = {"cgpa": "CGPA update", "target": "target planner", "gpa": "GPA calculation"}
FLOW_TAB = {"gpa": "gpa", "cgpa": "cgpa", "target": "target"}

# Intents that are plain explanations (can be answered in the middle of a dialog)
INFO_INTENTS = {
    "what_is_gpa", "what_is_cgpa", "gpa_formula", "cgpa_formula", "required_gpa", "grade_scale",
    "grade_point_explanation", "credit_hour_explanation", "invalid_input", "help",
}
CANCEL_RE = re.compile(r"\b(cancel|stop|never\s*mind|nevermind|abort|forget\s+it|quit|exit)\b")


class GPAChatbot:
    def __init__(self, intents_path=INTENTS_PATH):
        with open(intents_path, "r", encoding="utf-8") as file:
            data = json.load(file)
        self.responses = {i["tag"]: i["responses"] for i in data["intents"]}
        self.suggestions = {i["tag"]: i.get("suggestions", []) for i in data["intents"]}
        self._sessions = OrderedDict()
        self._lock = threading.Lock()
        nlp._classifier.load()          # load (or locally train) the model once at start-up

    # ------------------------------------------------------------------ sessions
    def _session(self, session_id):
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = {"flow": None, "slots": {}, "gpa_tries": 0}
                while len(self._sessions) > MAX_SESSIONS:
                    self._sessions.popitem(last=False)
            self._sessions.move_to_end(session_id)
            return self._sessions[session_id]

    def reset_session(self, session_id):
        with self._lock:
            self._sessions.pop(session_id, None)

    # ------------------------------------------------------------------ helpers
    def _pick(self, tag):
        return random.choice(self.responses.get(tag) or self.responses["fallback"])

    @staticmethod
    def _reply(text, intent, confidence=1.0, result=None, suggestions=None, tab=None, waiting=False):
        return {
            "reply": text,
            "intent": intent,
            "confidence": round(float(confidence), 3),
            "result": result,
            "suggestions": suggestions or [],
            "ui_tab": tab,
            "waiting": waiting,
        }

    def _answer_intent(self, intent, confidence, scale=None):
        """Plain explanation for an intent (no calculation)."""
        text = self._pick(intent)
        result = None
        if intent == "grade_scale":
            result = {"type": "scale", "scale": scale or calculator.get_grade_scale()}
        tab = {"grade_scale": "scale"}.get(intent)
        return self._reply(text, intent, confidence, result=result,
                           suggestions=self.suggestions.get(intent), tab=tab)

    # ------------------------------------------------------------------ flows
    def _start_flow(self, session, flow):
        session["flow"] = flow
        session["slots"] = {}
        session["gpa_tries"] = 0

    def _fill_slots(self, flow, entities, text, session):
        """Copy numbers found in the message into the session's slots."""
        slots = session["slots"]
        names = [name for name, _ in FLOWS[flow]]

        found = {k: entities[k] for k in names if k in entities}
        generic = entities.get("gpa")
        if generic is not None:
            if flow == "cgpa":
                if "semester_gpa" not in found:
                    found["semester_gpa"] = generic
                elif "current_cgpa" not in found:
                    found["current_cgpa"] = generic
            elif flow == "target" and "current_cgpa" not in found:
                found["current_cgpa"] = generic

        missing_credit_slots = [s for s in CREDIT_FILL_ORDER[flow] if s not in found and s not in slots]
        for value, slot in zip(entities.get("unlabeled_credits", []), missing_credit_slots):
            found[slot] = value

        # a bare number answers the question that was just asked
        if not found:
            number = nlp.parse_bare_number(text)
            if number is not None:
                for name in names:
                    if name not in slots:
                        found[name] = number
                        break
        return found

    def _flow_step(self, flow, session, entities, text, scale):
        """Store new values, validate them and either ask the next question or calculate."""
        slots = session["slots"]
        found = self._fill_slots(flow, entities, text, session)

        for name, value in found.items():
            check = calculator.validate_field(name, value)
            if not check["ok"]:
                slots.pop(name, None)
                question = dict(FLOWS[flow])[name]
                return self._reply(f"{check['error']}\n\n{question}", f"{flow}_flow", tab=FLOW_TAB[flow], waiting=True)
            slots[name] = value

        for name, question in FLOWS[flow]:
            if name not in slots:
                prefix = "Got it. " if found else "Please send a number. "
                return self._reply(prefix + question, f"{flow}_flow", tab=FLOW_TAB[flow], waiting=True,
                                   suggestions=["Cancel"])

        # all four values are known -> calculate
        values = dict(slots)
        session["flow"], session["slots"] = None, {}
        return self._run_flow_calculation(flow, values, scale)

    def _run_flow_calculation(self, flow, values, scale):
        if flow == "cgpa":
            result = calculator.calculate_cgpa(values["current_cgpa"], values["completed_credits"],
                                               values["semester_gpa"], values["semester_credits"])
            intent = "calculate_cgpa"
        else:
            result = calculator.calculate_required_gpa(values["current_cgpa"], values["completed_credits"],
                                                       values["target_cgpa"], values["remaining_credits"], scale)
            intent = "target_cgpa"
        return self._reply_from_result(result, intent)

    def _reply_from_result(self, result, intent):
        if not result.get("ok"):
            return self._reply(f"I couldn't calculate that: {result['error']}", "invalid_input",
                               suggestions=["Help", "Grade Scale"])
        followups = {
            "gpa": ["Calculate CGPA", "Target Planner"],
            "cgpa": ["Target Planner", "Calculate GPA"],
            "target": ["Calculate CGPA", "Calculate GPA"],
        }[result["type"]]
        return self._reply(result["message"], intent, result=result, suggestions=followups,
                           tab=FLOW_TAB[result["type"]])

    def _gpa_from_courses(self, courses, scale):
        return self._reply_from_result(calculator.calculate_gpa(courses, scale), "calculate_gpa")

    # ------------------------------------------------------------------ main entry
    def respond(self, message, session_id="default", scale=None):
        """Return a reply dictionary for one user message."""
        text = str(message or "").strip()
        if not text:
            return self._reply("Please type a message, for example: *Calculate my GPA*.", "fallback")
        text = text[:MAX_MESSAGE_LENGTH]

        session = self._session(session_id)
        parsed = nlp.parse_message(text)
        intent, confidence, entities = parsed["intent"], parsed["confidence"], parsed["entities"]
        normalized = parsed["normalized"]
        courses = entities["courses"]
        slot_hits = [k for k in ("current_cgpa", "completed_credits", "semester_gpa", "semester_credits",
                                 "target_cgpa", "remaining_credits") if k in entities]

        # --- global commands -------------------------------------------------
        if intent == "reset" and not courses:
            self.reset_session(session_id)
            return self._answer_intent("reset", confidence)
        if session["flow"] and CANCEL_RE.search(normalized):
            session["flow"], session["slots"] = None, {}
            return self._reply("No problem, I've cancelled that. What would you like to do next?", "cancel",
                               suggestions=["Calculate GPA", "Calculate CGPA", "Target Planner"])

        # --- inside a guided dialog -------------------------------------------
        flow = session["flow"]
        if flow in FLOWS:
            if courses and not slot_hits:          # a course list while planning -> calculate the GPA instead
                session["flow"], session["slots"] = None, {}
                return self._gpa_from_courses(courses, scale)
            has_data = bool(slot_hits) or entities.get("gpa") is not None or entities["unlabeled_credits"] \
                or nlp.parse_bare_number(text) is not None
            if not has_data and intent in INFO_INTENTS:
                answer = self._answer_intent(intent, confidence, scale)
                name = next(n for n, _ in FLOWS[flow] if n not in session["slots"])
                answer["reply"] += f"\n\nBack to your {FLOW_TITLES[flow]}: {dict(FLOWS[flow])[name]}"
                answer["waiting"] = True
                return answer
            return self._flow_step(flow, session, entities, text, scale)

        if flow == "gpa":
            if courses:
                session["flow"] = None
                return self._gpa_from_courses(courses, scale)
            if not (intent in INFO_INTENTS or intent in ("greeting", "thanks", "goodbye")):
                session["gpa_tries"] += 1
                if session["gpa_tries"] >= 3:
                    session["flow"] = None
                return self._reply(
                    "I couldn't find any courses in that. Please write each course as "
                    "**name, credit hours, grade**, for example:\n*Programming 3 A, Database 3 B+, English 2 A-*\n\n"
                    "You can also use the GPA form on the right.",
                    "calculate_gpa", tab="gpa", waiting=True, suggestions=["Cancel"])

        # --- free-text calculations (no dialog needed) -------------------------
        planner_words = re.search(r"\b(target|goal|reach|achieve|required|need(?:ed)?\s+to\s+(?:get|score)|remaining|left)\b", normalized)
        if courses and len(slot_hits) < 2:
            return self._gpa_from_courses(courses, scale)

        if len(slot_hits) >= 2 or (slot_hits and intent in ("calculate_cgpa", "target_cgpa", "required_gpa")):
            if "target_cgpa" in slot_hits or "remaining_credits" in slot_hits or intent in ("target_cgpa",) \
                    or (planner_words and "semester_gpa" not in slot_hits):
                flow = "target"
            else:
                flow = "cgpa"
            self._start_flow(session, flow)
            return self._flow_step(flow, session, entities, text, scale)

        # --- intents that start something ------------------------------------
        if intent == "calculate_gpa":
            self._start_flow(session, "gpa")
            return self._reply(self._pick("calculate_gpa"), intent, confidence, tab="gpa",
                               suggestions=self.suggestions.get(intent), waiting=True)
        if intent in ("calculate_cgpa", "target_cgpa"):
            flow = "cgpa" if intent == "calculate_cgpa" else "target"
            self._start_flow(session, flow)
            intro = self._pick(intent)
            first_question = FLOWS[flow][0][1]
            return self._reply(f"{intro}\n\n**Let's start:** {first_question}", intent, confidence,
                               tab=FLOW_TAB[flow], waiting=True, suggestions=["Cancel"])

        # --- everything else is an explanation or small talk -------------------
        if intent == "fallback":
            return self._reply(self._pick("fallback"), "fallback", confidence,
                               suggestions=self.suggestions.get("fallback"))
        return self._answer_intent(intent, confidence, scale)
