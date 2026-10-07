"""
calculator.py - the mathematical engine of the GPA / CGPA chatbot.

This module is completely independent from Flask and from the NLP code.
Every public function returns a plain dictionary:

    {"ok": True,  ...results...}                      on success
    {"ok": False, "error": "message", "field": "x"}   on invalid input

so callers never have to deal with exceptions or stack traces.

Calculations use Python's Decimal type, which avoids floating-point surprises
such as 3.675 being rounded to 3.67 instead of 3.68.
"""

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
import math

# ---------------------------------------------------------------------------
# SETTINGS - change the grading scale (or the GPA ceiling) in ONE place only
# ---------------------------------------------------------------------------
MAX_GPA = 4.0            # highest allowed GPA / CGPA
MIN_GPA = 0.0            # lowest allowed GPA / CGPA
MAX_CREDITS = 500        # sanity limit for any credit-hour field

GRADE_SCALE = {          # default grade -> grade point mapping
    "A+": 4.0,
    "A": 4.0,
    "A-": 3.7,
    "B+": 3.3,
    "B": 3.0,
    "B-": 2.7,
    "C+": 2.3,
    "C": 2.0,
    "C-": 1.7,
    "D+": 1.3,
    "D": 1.0,
    "F": 0.0,
}

# Human friendly names of the input fields (used in error messages)
FIELD_LABELS = {
    "current_cgpa": "Current CGPA",
    "completed_credits": "Completed credit hours",
    "semester_gpa": "New semester GPA",
    "semester_credits": "New semester credit hours",
    "target_cgpa": "Target CGPA",
    "remaining_credits": "Remaining credit hours",
}

# field -> (kind, allow_zero)   kind is "gpa" (0-4 range) or "credits"
FIELD_RULES = {
    "current_cgpa": ("gpa", True),
    "completed_credits": ("credits", True),    # a new student may have 0
    "semester_gpa": ("gpa", True),
    "semester_credits": ("credits", False),
    "target_cgpa": ("gpa", True),
    "remaining_credits": ("credits", False),
}


class CalculationError(ValueError):
    """Raised internally for invalid input; converted to an error dict."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.message = message
        self.field = field


def _error(message, field=None):
    return {"ok": False, "error": message, "field": field}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _dec(value):
    """Convert a float/int/str to Decimal using its printed form (3.3 -> 3.3)."""
    return Decimal(str(value))


def _round2(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _num(value, places=2):
    """Format a Decimal without useless trailing zeros (8.00 -> 8, 2.50 -> 2.5)."""
    text = f"{value:.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _parse_number(value, label, field):
    """Turn user input into a finite Decimal or raise CalculationError."""
    if value is None or isinstance(value, bool):
        raise CalculationError(f"{label} is required.", field)
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
        if value == "":
            raise CalculationError(f"{label} is required.", field)
    try:
        number = _dec(value)
    except (InvalidOperation, ValueError):
        raise CalculationError(f"{label} must be a number (you entered '{value}').", field)
    if not number.is_finite():
        raise CalculationError(f"{label} must be a valid number.", field)
    return number


def _check_field(field, value):
    """Validate one named field and return its Decimal value."""
    label = FIELD_LABELS.get(field, field)
    kind, allow_zero = FIELD_RULES[field]
    number = _parse_number(value, label, field)

    if kind == "gpa":
        if number < _dec(MIN_GPA):
            raise CalculationError(f"{label} cannot be below {MIN_GPA:.2f}.", field)
        if number > _dec(MAX_GPA):
            raise CalculationError(f"{label} cannot be above {MAX_GPA:.2f}.", field)
    else:  # credits
        if number < 0 or (number == 0 and not allow_zero):
            if field == "remaining_credits":
                raise CalculationError(
                    "Remaining credit hours must be greater than 0 - "
                    "there is nothing left to plan with zero credits.", field)
            raise CalculationError(f"{label} must be greater than 0.", field)
        if number > MAX_CREDITS:
            raise CalculationError(f"{label} looks too large (maximum {MAX_CREDITS}).", field)
    return number


def validate_field(field, value):
    """Public helper: validate a single field (used by the chat wizard)."""
    try:
        return {"ok": True, "value": float(_check_field(field, value))}
    except CalculationError as exc:
        return _error(exc.message, exc.field)


# ---------------------------------------------------------------------------
# Grade scale handling
# ---------------------------------------------------------------------------
def get_grade_scale():
    """Return a copy of the default grade scale."""
    return dict(GRADE_SCALE)


def _normalize_grade_text(grade):
    text = str(grade).strip().upper()
    for dash in ("\u2013", "\u2014", "\u2212", "\u2012"):
        text = text.replace(dash, "-")
    return text.replace(" ", "")


def validate_grade_scale(scale):
    """Check a custom grade scale. Returns {"ok", "scale"} or an error dict."""
    if scale is None:
        return {"ok": True, "scale": get_grade_scale()}
    if not isinstance(scale, dict) or not scale:
        return _error("The grade scale must be a non-empty set of grade/point pairs.")
    clean = {}
    for grade, points in scale.items():
        key = _normalize_grade_text(grade)
        if not key:
            return _error("The grade scale contains an empty grade name.")
        try:
            value = _parse_number(points, f"Grade point for {key}", None)
        except CalculationError as exc:
            return _error(exc.message)
        if value < 0 or value > _dec(MAX_GPA):
            return _error(f"Grade point for {key} must be between 0 and {MAX_GPA:.1f}.")
        clean[key] = float(value)
    return {"ok": True, "scale": clean}


def validate_grade(grade, grade_scale=None):
    """
    Check that `grade` exists in the scale.
    Returns {"ok": True, "grade": "A-", "points": 3.7} or an error dict.
    """
    scale = grade_scale if grade_scale is not None else GRADE_SCALE
    if grade is None or str(grade).strip() == "":
        return _error("Grade is required.", "grade")
    key = _normalize_grade_text(grade)
    scale_upper = {k.upper(): v for k, v in scale.items()}
    if key not in scale_upper:
        valid = ", ".join(scale.keys())
        return _error(f"'{str(grade).strip()}' is not a valid grade. Valid grades: {valid}.", "grade")
    return {"ok": True, "grade": key, "points": float(scale_upper[key])}


def performance_label(gpa):
    """A neutral, generic description of a GPA value."""
    gpa = float(gpa)
    if gpa >= 3.7:
        return "Excellent"
    if gpa >= 3.3:
        return "Very good"
    if gpa >= 3.0:
        return "Good"
    if gpa >= 2.0:
        return "Satisfactory"
    return "Needs improvement"


# ---------------------------------------------------------------------------
# 1. Semester GPA
# ---------------------------------------------------------------------------
def calculate_gpa(courses, grade_scale=None):
    """
    courses: list of {"name": str, "credits": number, "grade": "A-"} dictionaries
             (or (name, credits, grade) tuples).
    GPA = sum(grade point x credit hours) / sum(credit hours)
    """
    try:
        scale_check = validate_grade_scale(grade_scale)
        if not scale_check["ok"]:
            return scale_check
        scale = scale_check["scale"]

        if not isinstance(courses, (list, tuple)) or len(courses) == 0:
            raise CalculationError("Please add at least one course (name, credit hours and grade).", "courses")

        rows = []
        steps = []
        total_credits = Decimal("0")
        total_points = Decimal("0")

        for index, course in enumerate(courses, start=1):
            if isinstance(course, (list, tuple)) and len(course) == 3:
                course = {"name": course[0], "credits": course[1], "grade": course[2]}
            if not isinstance(course, dict):
                raise CalculationError(f"Course {index} is not valid.", "courses")

            name = str(course.get("name") or "").strip() or f"Course {index}"
            where = f"Course {index} ({name})" if course.get("name") else f"Course {index}"

            # credit hours
            credits = _parse_number(course.get("credits"), f"{where}: credit hours", "credits")
            if credits <= 0:
                raise CalculationError(f"{where}: credit hours must be greater than 0.", "credits")
            if credits > 30:
                raise CalculationError(f"{where}: credit hours look too large (maximum 30 per course).", "credits")

            # grade
            checked = validate_grade(course.get("grade"), scale)
            if not checked["ok"]:
                raise CalculationError(f"{where}: {checked['error']}", "grade")

            points = _dec(checked["points"])
            quality = points * credits
            total_credits += credits
            total_points += quality

            rows.append({
                "name": name,
                "credits": float(credits),
                "grade": checked["grade"],
                "grade_points": float(points),
                "quality_points": float(_round2(quality)),
            })
            steps.append(f"{name}: {_num(points)} x {_num(credits)} = {_num(quality)}")

        gpa_exact = total_points / total_credits
        gpa = _round2(gpa_exact)

        return {
            "ok": True,
            "type": "gpa",
            "gpa": float(gpa),
            "total_credits": float(total_credits),
            "total_quality_points": float(_round2(total_points)),
            "courses": rows,
            "steps": steps,
            "formula": "GPA = sum(Grade Point x Credit Hours) / sum(Credit Hours)",
            "calculation": f"{_num(total_points)} / {_num(total_credits)} = {_num(gpa_exact, 4)} -> {gpa:.2f}",
            "performance": performance_label(gpa),
            "max_gpa": MAX_GPA,
            "message": (f"Your semester GPA is {gpa:.2f} from {_num(total_credits)} credit hours "
                        f"and {_num(total_points)} quality points."),
        }
    except CalculationError as exc:
        return _error(exc.message, exc.field)
    except Exception:  # never leak a stack trace
        return _error("Something went wrong while calculating the GPA. Please check your entries.")


# ---------------------------------------------------------------------------
# 2. Cumulative GPA
# ---------------------------------------------------------------------------
def calculate_cgpa(current_cgpa, completed_credits, semester_gpa, semester_credits):
    """
    New CGPA = (CGPA x previous credits + semester GPA x semester credits)
               / (previous credits + semester credits)
    """
    try:
        cgpa = _check_field("current_cgpa", current_cgpa)
        prev_credits = _check_field("completed_credits", completed_credits)
        sem_gpa = _check_field("semester_gpa", semester_gpa)
        sem_credits = _check_field("semester_credits", semester_credits)

        previous_points = cgpa * prev_credits
        semester_points = sem_gpa * sem_credits
        total_credits = prev_credits + sem_credits
        total_points = previous_points + semester_points

        new_exact = total_points / total_credits
        new_cgpa = _round2(new_exact)
        change = _round2(new_exact - cgpa)

        if prev_credits == 0:
            note = "Since you have no completed credits yet, your CGPA equals your first semester GPA."
        elif change > 0:
            note = f"Your CGPA goes up by {change:.2f}."
        elif change < 0:
            note = f"Your CGPA goes down by {abs(change):.2f}."
        else:
            note = "Your CGPA stays the same."

        return {
            "ok": True,
            "type": "cgpa",
            "new_cgpa": float(new_cgpa),
            "previous_cgpa": float(cgpa),
            "change": float(change),
            "total_credits": float(total_credits),
            "total_quality_points": float(_round2(total_points)),
            "previous_quality_points": float(_round2(previous_points)),
            "semester_quality_points": float(_round2(semester_points)),
            "formula": ("New CGPA = (Current CGPA x Previous Credits + Semester GPA x Semester Credits) "
                        "/ (Previous Credits + Semester Credits)"),
            "steps": [
                f"Previous quality points: {_num(cgpa)} x {_num(prev_credits)} = {_num(previous_points)}",
                f"Semester quality points: {_num(sem_gpa)} x {_num(sem_credits)} = {_num(semester_points)}",
                f"Total: ({_num(previous_points)} + {_num(semester_points)}) / {_num(total_credits)} "
                f"= {_num(new_exact, 4)} -> {new_cgpa:.2f}",
            ],
            "performance": performance_label(new_cgpa),
            "max_gpa": MAX_GPA,
            "message": f"Your updated CGPA is {new_cgpa:.2f}. {note}",
        }
    except CalculationError as exc:
        return _error(exc.message, exc.field)
    except Exception:
        return _error("Something went wrong while calculating the CGPA. Please check your entries.")


# ---------------------------------------------------------------------------
# 3. Target CGPA planner
# ---------------------------------------------------------------------------
def calculate_required_gpa(current_cgpa, completed_credits, target_cgpa, remaining_credits,
                           grade_scale=None):
    """
    Required GPA = (Target x (Completed + Remaining) - Current x Completed) / Remaining
    """
    try:
        scale_check = validate_grade_scale(grade_scale)
        if not scale_check["ok"]:
            return scale_check
        scale = scale_check["scale"]

        cgpa = _check_field("current_cgpa", current_cgpa)
        completed = _check_field("completed_credits", completed_credits)
        target = _check_field("target_cgpa", target_cgpa)
        remaining = _check_field("remaining_credits", remaining_credits)

        total_final = completed + remaining
        needed_points = target * total_final
        have_points = cgpa * completed
        required_exact = (needed_points - have_points) / remaining
        max_cgpa = (have_points + _dec(MAX_GPA) * remaining) / total_final
        min_cgpa = have_points / total_final            # if every remaining grade is 0

        base = {
            "ok": True,
            "type": "target",
            "current_cgpa": float(cgpa),
            "target_cgpa": float(target),
            "completed_credits": float(completed),
            "remaining_credits": float(remaining),
            "total_final_credits": float(total_final),
            "max_possible_cgpa": float(_round2(max_cgpa)),
            "formula": ("Required GPA = (Target CGPA x Total Final Credits - Current CGPA x Completed Credits) "
                        "/ Remaining Credits"),
            "max_gpa": MAX_GPA,
        }
        calc_line = (f"({_num(target)} x {_num(total_final)} - {_num(cgpa)} x {_num(completed)}) "
                     f"/ {_num(remaining)} = {_num(required_exact, 4)}")

        # Case 1: target is already guaranteed, even with a 0.00 GPA from now on
        if required_exact <= 0:
            base.update({
                "status": "secured",
                "achievable": True,
                "required_gpa": 0.0,
                "steps": [calc_line, "A zero or negative result means no minimum GPA is needed."],
                "message": (f"Target already achieved. Even with a 0.00 GPA in the remaining "
                            f"{_num(remaining)} credit hours, your CGPA would stay at "
                            f"{_round2(min_cgpa):.2f} or higher, which meets your target of "
                            f"{_num(target)}."),
            })
            return base

        # Case 2: impossible even with the maximum GPA in every remaining course
        if required_exact > _dec(MAX_GPA):
            extra = None
            if target < _dec(MAX_GPA):
                # extra credits n at MAX_GPA so that (have + MAX*n)/(completed+n) >= target
                n = completed * (target - cgpa) / (_dec(MAX_GPA) - target)
                extra = math.ceil(n) if 0 < n <= 200 else None
            message = (f"This target is not achievable with a maximum GPA of {MAX_GPA:.1f}. "
                       f"You would need an average of {_round2(required_exact):.2f} in the remaining "
                       f"{_num(remaining)} credit hours. The highest CGPA you can reach is "
                       f"{_round2(max_cgpa):.2f}.")
            if extra:
                message += (f" You would need about {extra} more credit hours at {MAX_GPA:.1f} "
                            f"to reach {_num(target)}.")
                base["credits_needed_at_max"] = extra
            base.update({
                "status": "impossible",
                "achievable": False,
                "required_gpa": float(_round2(required_exact)),
                "steps": [calc_line],
                "message": message,
            })
            return base

        # Case 3: achievable. Round UP so the displayed GPA really reaches the target.
        required = required_exact.quantize(Decimal("0.01"), rounding=ROUND_CEILING)
        if required > _dec(MAX_GPA):
            required = _dec(MAX_GPA)

        if required <= Decimal("2.5"):
            difficulty = "comfortable"
        elif required <= Decimal("3.3"):
            difficulty = "moderate"
        elif required <= Decimal("3.7"):
            difficulty = "demanding"
        else:
            difficulty = "very demanding"

        # lowest letter grade whose points reach the required GPA
        eligible = sorted((p, g) for g, p in scale.items() if p >= float(required))
        letter = eligible[0][1] if eligible else None

        already_met = cgpa >= target and completed > 0
        if already_met:
            message = (f"You are already at {_num(cgpa)}, which is at or above your target of {_num(target)}. "
                       f"To stay there, your average GPA for the remaining "
                       f"{_num(remaining)} credit hours must be at least {required:.2f}.")
        else:
            message = (f"Your required average GPA for the remaining {_num(remaining)} credit hours "
                       f"is {required:.2f}.")
        message += f" That is a {difficulty} goal."
        if letter:
            article = "an" if letter[0] in "AF" else "a"
            message += f" Roughly {article} {letter} average."

        base.update({
            "status": "achievable",
            "achievable": True,
            "required_gpa": float(required),
            "difficulty": difficulty,
            "minimum_average_grade": letter,
            "already_met": bool(already_met),
            "steps": [calc_line, f"Rounded up to 2 decimals: {required:.2f}"],
            "message": message,
        })
        return base
    except CalculationError as exc:
        return _error(exc.message, exc.field)
    except Exception:
        return _error("Something went wrong while planning your target. Please check your entries.")
