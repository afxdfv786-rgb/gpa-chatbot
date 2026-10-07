"""
nlp.py - everything the chatbot needs to "understand" a message, 100% offline.

1. normalize_text / preprocess_for_model : clean the user's sentence
2. IntentClassifier                       : loads the locally trained
                                            TF-IDF + Logistic Regression model
3. extract_entities                       : regex / rule based parsing of
                                            courses, grades, credits, GPA,
                                            CGPA and target CGPA
4. parse_message                          : returns all of the above together

No external language model or API is used anywhere.
"""

import importlib.util
import os
import pickle
import re
import threading
import warnings

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(BASE_DIR, "model")
MODEL_PATH = os.path.join(MODEL_DIR, "model.pkl")
VECTORIZER_PATH = os.path.join(MODEL_DIR, "vectorizer.pkl")
TRAIN_SCRIPT = os.path.join(BASE_DIR, "training", "train.py")

# Below this probability the message is treated as "not understood" (fallback)
CONFIDENCE_THRESHOLD = 0.30


# ---------------------------------------------------------------------------
# 1. Text cleaning
# ---------------------------------------------------------------------------
def normalize_text(text):
    """Lower-case, unify dashes/quotes and collapse whitespace."""
    text = str(text or "")
    for dash in ("\u2013", "\u2014", "\u2212", "\u2012"):
        text = text.replace(dash, "-")
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def preprocess_for_model(text):
    """
    Cleaning used for BOTH training and prediction.
    Numbers become the word 'num', so "my cgpa is 3.2" and "my cgpa is 3.8"
    look identical to the classifier (the numbers are read by regex later).
    """
    text = normalize_text(text)
    text = re.sub(r"\d+(?:\.\d+)?", " num ", text)
    text = re.sub(r"[^a-z\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# 2. Local intent classifier
# ---------------------------------------------------------------------------
class IntentClassifier:
    """Loads model.pkl + vectorizer.pkl once and predicts intents."""

    def __init__(self):
        self.model = None
        self.vectorizer = None
        self._lock = threading.Lock()

    def _load_files(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with open(VECTORIZER_PATH, "rb") as file:
                vectorizer = pickle.load(file)
            with open(MODEL_PATH, "rb") as file:
                model = pickle.load(file)
        # A different scikit-learn version may produce a warning -> retrain locally
        if any("version" in str(w.message).lower() for w in caught):
            raise RuntimeError("Model was saved with a different scikit-learn version.")
        return model, vectorizer

    @staticmethod
    def _train_locally():
        """Train again on this computer (used if the model files are missing/incompatible)."""
        spec = importlib.util.spec_from_file_location("train_script", TRAIN_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.train(verbose=False)

    def load(self):
        with self._lock:
            if self.model is not None:
                return
            try:
                self.model, self.vectorizer = self._load_files()
            except Exception:
                print("[GradeMate] Preparing the local model (one-time training, offline)...")
                self._train_locally()
                self.model, self.vectorizer = self._load_files()

    def predict(self, text):
        """Return (intent, confidence 0-1)."""
        self.load()
        cleaned = preprocess_for_model(text)
        if not cleaned:
            return "fallback", 1.0
        features = self.vectorizer.transform([cleaned])
        probabilities = self.model.predict_proba(features)[0]
        best = int(probabilities.argmax())
        intent = str(self.model.classes_[best])
        confidence = float(probabilities[best])
        if confidence < CONFIDENCE_THRESHOLD:
            return "fallback", confidence
        return intent, confidence


_classifier = IntentClassifier()


def classify_intent(text):
    return _classifier.predict(text)


# ---------------------------------------------------------------------------
# 3. Entity extraction (regex / rules)
# ---------------------------------------------------------------------------
NUM = r"(?P<num>\d+(?:\.\d+)?)"
UNIT = r"(?:credit[\s-]*hours?|credits?|cr\.?|ch|hours?|hrs?)"
IS = r"(?:\s*(?:is|are|of|was|=|:|at|to be)\s*|\s*)"

# Course line:  "<name> <credits> [credit hours] <grade>"
SEP = r"[\s:,\-|()\[\]]*"
NAME = r"(?P<name>[A-Za-z][A-Za-z0-9 &/']*?)"
COURSE_RE = re.compile(
    NAME + SEP +
    r"(?P<credits>\d+(?:\.\d+)?)\s*" + r"(?:" + UNIT + r"(?![A-Za-z]))?" + SEP +
    r"(?:grade\s*(?:of|is|:)?\s*)?" +
    r"(?P<grade>[A-Za-z][+\-]{0,2})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
# Alternative phrasing:  "A in Programming (3 credits)"
GRADE_FIRST_RE = re.compile(
    r"(?<![A-Za-z])(?P<grade>[A-DF][+\-]?)\s+(?:in|for|on)\s+" + NAME + SEP +
    r"(?P<credits>\d+(?:\.\d+)?)\s*" + UNIT + r"(?![A-Za-z])"
)

# Words that may sneak into the start of a course name ("calculate gpa for ...")
NAME_FILLER = {
    "calculate", "compute", "find", "get", "my", "the", "gpa", "cgpa", "for", "please", "courses",
    "course", "are", "is", "with", "and", "i", "got", "have", "had", "semester", "in", "of", "these",
    "following", "subjects", "subject", "grades", "grade", "a", "an", "can", "you", "help", "me",
    "what", "whats", "what's", "if", "take", "took", "taken", "taking", "scored", "result", "results",
    "this", "using", "from", "calc", "also", "then", "plus", "calculating", "need", "to", "want",
    "know", "check", "tell", "show", "make", "let's", "lets", "new", "total",
}

# Slot patterns. Each list is tried in order; every number may be used only once.
SLOT_PATTERNS = {
    "target_cgpa": [
        rf"(?:target|goal|desired|aim(?:ing)?)\s*(?:final\s+|overall\s+)?(?:cgpa|gpa)?{IS}{NUM}(?!\s*{UNIT})",
        rf"(?:reach|achieve|get\s+to|raise\s+(?:it\s+)?to|improve\s+(?:it\s+)?to|increase\s+(?:it\s+)?to|"
        rf"graduate\s+with|finish\s+with|end\s+with|make\s+it)\s*(?:a\s+|an\s+)?(?:final\s+|overall\s+)?"
        rf"(?:cgpa|gpa)?{IS}{NUM}(?!\s*{UNIT})",
        rf"(?:want|wish|hope|need|like|plan|trying)\w*\s+(?:to\s+)?(?:have\s+|get\s+|be\s+at\s+)?"
        rf"(?:a\s+|an\s+)?(?:final\s+|overall\s+)?(?:cgpa|gpa)?{IS}{NUM}(?!\s*{UNIT})(?!\s*(?:more|left|remaining))",
        rf"{NUM}\s*(?:cgpa|gpa)?\s*(?:as\s+)?(?:my\s+)?(?:target|goal)",
    ],
    "remaining_credits": [
        rf"(?:remaining|left|leftover|rest|upcoming|future|next)\s*(?:of\s+)?(?:{UNIT})?{IS}{NUM}",
        rf"{NUM}\s*(?:{UNIT})?\s*(?:remaining|left|to\s+go|more|ahead|remain|still\s+to\s+(?:take|do|study))",
    ],
    "completed_credits": [
        rf"(?:completed|earned|finished|done|passed|previous|prior|accumulated|taken)\s*(?:credit\s*hours?|credits?|hours?)?{IS}{NUM}",
        rf"{NUM}\s*(?:{UNIT})?\s*(?:completed|earned|finished|done|passed|so\s+far|already|behind)",
        rf"(?:total\s+)?(?:credit\s*hours?|credits?)\s*(?:completed|earned|so\s+far|done){IS}{NUM}",
    ],
    "semester_credits": [
        rf"(?:new|this|current|latest|recent)\s+(?:semester\s+)?(?:credit\s*hours?|credits?){IS}{NUM}",
        rf"(?:new|this|current|latest|recent)?\s*semester\s*(?:credit\s*hours?|credits?)(?:\s+hours?)?{IS}{NUM}",
        rf"(?:new|this|current|latest|recent)\s+(?:credit\s*hours?|credits?){IS}{NUM}",
        rf"{NUM}\s*{UNIT}\s*(?:in\s+|for\s+|this\s+|the\s+)*(?:new\s+|current\s+|latest\s+)?(?:semester|term)",
    ],
    "semester_gpa": [
        rf"(?:semester|term)\s*gpa{IS}{NUM}",
        rf"(?:new|this|latest|recent|current)\s+(?:semester\s+)?gpa{IS}{NUM}",
        rf"gpa\s*(?:this|for\s+the|of\s+the|in\s+the|for\s+this)\s*(?:new\s+)?(?:semester|term){IS}{NUM}",
        rf"{NUM}\s*gpa\s*(?:this|for\s+the|in\s+the|for\s+this)\s*(?:new\s+)?(?:semester|term)",
    ],
    "current_cgpa": [
        rf"(?:current|present|existing|old|previous|overall|cumulative|my)\s*(?:cgpa|cumulative\s+gpa|gpa){IS}{NUM}",
        rf"(?<![a-z])cgpa{IS}{NUM}",
        rf"{NUM}\s*cgpa",
    ],
    "gpa": [
        rf"(?<![a-z])gpa{IS}{NUM}",
        rf"{NUM}\s*gpa",
    ],
}
SLOT_ORDER = ["target_cgpa", "remaining_credits", "completed_credits", "semester_credits",
              "semester_gpa", "current_cgpa", "gpa"]


def _overlaps(span, used):
    return any(span[0] < end and span[1] > start for start, end in used)


def _find_slot(patterns, text, used):
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            span = match.span("num")
            if _overlaps(span, used):
                continue
            used.append(span)
            return float(match.group("num"))
    return None


def _clean_course_name(raw):
    words = raw.strip(" .,:;-|").split()
    while words and words[0].lower().strip("'") in NAME_FILLER:
        words.pop(0)
    name = " ".join(words).strip(" .,:;-|&/")[:40]
    return name.title() if name == name.lower() else name


def _courses_from(regex, text):
    return [{
        "name": _clean_course_name(m.group("name")),
        "credits": float(m.group("credits")),
        "grade": m.group("grade").upper(),
    } for m in regex.finditer(text)]


def extract_courses(text):
    """Find (name, credits, grade) triples in free text. Returns a list of dicts."""
    text = str(text or "").replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    # "A in Programming (3 credits)" is checked first because it is more specific
    return _courses_from(GRADE_FIRST_RE, text) or _courses_from(COURSE_RE, text)


def extract_entities(text):
    """
    Pull numbers and grades out of a message using regular expressions.
    Returns a dictionary; keys that were not found are simply missing.
    """
    original = str(text or "")
    cleaned = normalize_text(original)
    entities = {}

    used = []
    for slot in SLOT_ORDER:
        value = _find_slot(SLOT_PATTERNS[slot], cleaned, used)
        if value is not None:
            entities[slot] = value

    # every "<number> credits" mention, in order (used as a fallback for unlabeled credits)
    unlabeled = []
    for match in re.finditer(rf"{NUM}\s*{UNIT}(?![a-z])", cleaned):
        if not _overlaps(match.span("num"), used):
            unlabeled.append(float(match.group("num")))
    # Range phrasing: "CGPA from 2.5 to 3.0" means current=2.5 and target=3.0.
    if "current_cgpa" not in entities and "target_cgpa" not in entities:
        m = re.search(r"(?:cgpa|gpa)?\s*from\s*(-?\d+(?:\.\d+)?)\s*to\s*(-?\d+(?:\.\d+)?)", cleaned)
        if m:
            entities["current_cgpa"] = float(m.group(1))
            entities["target_cgpa"] = float(m.group(2))
            used.extend([m.span(1), m.span(2)])

    # Contextual credit associations: when a user says both values in one sentence,
    # bind the credit hours to the nearby concept instead of relying on position.
    # Examples: "new semester GPA 3.8 with 18 credits" and
    # "my CGPA is 3.2 with 60 credits".
    if "semester_credits" not in entities:
        m = re.search(r"(?:new|this|current|latest|recent)\s+semester[^,]*?(?:with|having|of)\s*(-?\d+(?:\.\d+)?)\s*credits?", cleaned)
        if m:
            value = float(m.group(1))
            span = m.span(1)
            if not _overlaps(span, used):
                entities["semester_credits"] = value
                used.append(span)
                unlabeled = [v for v in unlabeled if v != value]
    if "completed_credits" not in entities:
        m = re.search(r"(?:current|present|existing|old|previous|overall|cumulative|my)\s*(?:cgpa|cumulative\s+gpa|gpa)\s*(?:is|=|with)?\s*-?\d+(?:\.\d+)?[^,.!?;]*?(?:with|having|and)\s*(-?\d+(?:\.\d+)?)\s*(?:credits?|credit\s+hours?)", cleaned)
        if m:
            # The last numeric match is the credit-hour value.
            nums = list(re.finditer(r"-?\d+(?:\.\d+)?", m.group(0)))
            if nums:
                cm = nums[-1]
                absolute = (m.start() + cm.start(), m.start() + cm.end())
                if not _overlaps(absolute, used):
                    entities["completed_credits"] = float(cm.group())
                    used.append(absolute)
                    unlabeled = [v for v in unlabeled if v != float(cm.group())]
    entities["unlabeled_credits"] = unlabeled
    entities["credits"] = [float(m.group("num")) for m in re.finditer(rf"{NUM}\s*{UNIT}(?![a-z])", cleaned)]

    # stand-alone letter grades such as A, B+, c-
    entities["grades"] = [g.upper() for g in re.findall(r"(?<![A-Za-z0-9.])([A-DF][+\-]?)(?![A-Za-z0-9])", original)]

    entities["courses"] = extract_courses(original)
    entities["numbers"] = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", cleaned)]
    return entities


def parse_bare_number(text):
    """If the whole message is just a number ('3.4', '60 credits'), return it."""
    cleaned = normalize_text(text)
    signed_num = r"(?P<num>-?\d+(?:\.\d+)?)"
    match = re.fullmatch(rf"(?:about|around|approximately|approx\.?|it'?s|its|is|=)?\s*{signed_num}\s*(?:{UNIT}|gpa|cgpa|points?)?\.?", cleaned)
    return float(match.group("num")) if match else None


# ---------------------------------------------------------------------------
# 4. One call that returns everything
# ---------------------------------------------------------------------------
def parse_message(text):
    intent, confidence = classify_intent(text)
    return {
        "raw": text,
        "normalized": normalize_text(text),
        "intent": intent,
        "confidence": round(confidence, 3),
        "entities": extract_entities(text),
    }
