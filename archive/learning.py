import os
import re
import string
from typing import List


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation/quotes, and collapse whitespace."""
    text = text.lower().strip(" '\"")
    text = text.translate(str.maketrans("", "", string.punctuation))
    return " ".join(text.split())


# Lessons are fed straight back into generation prompts, so a bad one is worse
# than no lesson at all. Cap the length and drop the recurring failure modes:
# rambling self-corrections, "install the library" advice, and rules that
# contradict the canvas API (e.g. "don't use c.sleep").
MAX_LESSON_CHARS = 220

_UNUSABLE_FRAGMENTS = (
    "install",             # tiny_canvas is not a pip package
    "correction after",
    "revised lesson",
    "self-correction",
    "standard library",
    "standard python",
    "site-packages",
    "import error",
    "importerror",
    "modulenotfound",
    "canvas_sleep",        # not a real method
    "does not expose",
    "does not provide a sleep",
    "inside the `while true` loop",   # would reset animation state
    "never initialized",
    "incompatible with the `tiny_canvas`",
)

# Every one of these IS a real method; a lesson claiming otherwise sends the
# next generation away from the API it should use.
_CANVAS_METHODS = (
    "clear", "pixel", "line", "rect", "fill_rect", "circle", "fill_circle",
    "show", "sleep",
)
_NEGATIONS = (
    "does not exist", "doesn't exist", "not a method", "no such method",
    "does not provide", "does not expose", "is not available",
    "isn't available", "not available", "not supported", "is not supported",
)


def _negates_canvas_method(low: str) -> bool:
    """True when the lesson says a real canvas method is missing/off-limits."""
    if not any(neg in low for neg in _NEGATIONS):
        return False
    return any(f"c.{method}" in low for method in _CANVAS_METHODS)



def _tidy_lesson(lesson: str) -> str:
    """Collapse whitespace and cut a rambling lesson down to one sentence."""
    lesson = " ".join((lesson or "").split()).strip(" -")
    for prefix in ("lesson:", "revised lesson:", "technical lesson:"):
        if lesson.lower().startswith(prefix):
            lesson = lesson[len(prefix):].strip()
    if len(lesson) > MAX_LESSON_CHARS:
        cut = lesson.find(". ", 0, MAX_LESSON_CHARS)
        lesson = lesson[:cut + 1] if cut != -1 else lesson[:MAX_LESSON_CHARS]
    return lesson.strip()


def _is_useful_lesson(lesson: str) -> bool:
    """True when a lesson is short, concrete, and safe to put in a prompt."""
    lesson = _tidy_lesson(lesson)
    if not lesson or len(lesson) > MAX_LESSON_CHARS:
        return False
    low = lesson.lower()
    if low in ("none", "n/a", "no lesson"):
        return False
    if _negates_canvas_method(low):
        return False
    return not any(fragment in low for fragment in _UNUSABLE_FRAGMENTS)


def _matches_existing(normalized: str, existing: list) -> bool:
    """True when a lesson duplicates an existing one (normalized equality or
    heavy word overlap)."""
    if not normalized:
        return True
    for prev in existing:
        if not prev:
            continue
        if normalized == prev:
            return True
        a = set(normalized.split())
        b = set(prev.split())
        if not a or not b:
            continue
        overlap = len(a & b) / min(len(a), len(b))
        if overlap >= 0.7:
            return True
    return False

class LearningSystem:
    """
    Manages the 'long-term memory' of the Tiny Programmer.
    Stores lessons learned from successes and failures.
    """
    
    def __init__(self, filepath="lessons.md"):
        self.filepath = filepath
        self._ensure_file()
        
    def _ensure_file(self):
        if not os.path.exists(self.filepath):
            with open(self.filepath, "w") as f:
                f.write("# Developer Journal\n\n")
                
    def add_lesson(self, lesson: str, max_lessons=50):
        """
        Add a new lesson to the journal.
        Keeps file size limited to max_lessons (FIFO), preserving header.
        """
        # Clean up lesson
        lesson = lesson.strip().replace("\n", " ")
        if lesson.startswith("- "):
            lesson = lesson[2:].strip()
        lesson = _tidy_lesson(lesson)
        if not _is_useful_lesson(lesson):
            return False

        # Read existing content
        if os.path.exists(self.filepath):
            with open(self.filepath, "r") as f:
                lines = f.readlines()
        else:
            lines = ["# Developer Journal\n", "\n"]

        # Separate header and lessons
        header = []
        lessons = []
        for line in lines:
            if line.startswith("- "):
                lessons.append(line)
            elif line.strip():
                header.append(line)

        # Skip near-duplicate lessons (normalized exact match or high word
        # overlap), so repeated failures don't fill the journal with the same
        # advice over and over.
        existing = [_normalize(l[2:]) for l in lessons]
        normalized = _normalize(lesson)
        if _matches_existing(normalized, existing):
            return False

        # Add new lesson
        lessons.append(f"- {lesson}\n")

        # Truncate if too many (keep most recent)
        if len(lessons) > max_lessons:
            lessons = lessons[-max_lessons:]

        # Write back
        with open(self.filepath, "w") as f:
            f.writelines(header)
            if header and not header[-1].endswith("\n"):
                f.write("\n")
            f.writelines(lessons)
        return True
            
    def get_recent_lessons(self, limit=3) -> str:
        """Get the newest useful lessons formatted for a prompt.

        Deterministic (newest first) instead of random: a random pull from the
        last 20 kept surfacing stale, contradictory advice and made generation
        quality vary for no reason.
        """
        if not os.path.exists(self.filepath):
            return ""

        with open(self.filepath, "r") as f:
            lines = [line.strip()[2:].strip()
                     for line in f.readlines() if line.startswith("-")]

        lessons = [l for l in lines if _is_useful_lesson(l)]
        return "\n".join(f"- {l}" for l in lessons[-limit:])