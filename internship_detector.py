"""
Internship detection + metadata extraction.

Given a job title and description, classify whether it's an internship and
extract internship-specific fields (duration, stipend, deadline, etc).

Used by the scraper push flow and the backfill script.
"""
import re
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

_TITLE_INTERN_KEYWORDS = [
    "intern", "internship", "co-op", "coop", "co op",
    "trainee", "student worker", "practicum",
    "summer analyst", "summer associate",
    "rotational program", "rotational analyst",
    "apprentice",
]

_DESC_INTERN_PHRASES = [
    "currently enrolled", "must be a student", "must be currently enrolled",
    "graduating in 20", "course credit", "school credit", "academic credit",
    "for-credit only", "for credit only",
    "actively pursuing a bachelor", "actively pursuing a master",
    "pursuing a bachelor's", "pursuing a master's", "pursuing a phd",
    "enrolled in an accredited",
]


def _has_any(text: str, phrases: list[str]) -> bool:
    return any(p in text for p in phrases)


def is_internship(title: str, description: str = "") -> bool:
    """True if the job should be tagged as an internship."""
    t_lower = (title or "").lower()
    if _has_any(t_lower, _TITLE_INTERN_KEYWORDS):
        return True

    d_lower = (description or "").lower()
    if _has_any(d_lower, _DESC_INTERN_PHRASES):
        return True

    return False


_BAD_TITLE_ALONE = {
    "intern", "internship", "student", "student worker",
    "trainee", "apprentice", "co-op", "coop",
}


def is_low_quality_title(title: str) -> bool:
    """Quality gate: reject titles that are just 'Intern' or 'Student' alone."""
    stripped = (title or "").strip().lower()
    return stripped in _BAD_TITLE_ALONE


# ---------------------------------------------------------------------------
# Metadata extraction helpers
# ---------------------------------------------------------------------------

def _extract_duration(text: str) -> Optional[str]:
    m = re.search(r'(\d+)\s*(?:-|to|–)\s*(\d+)\s*weeks?', text, re.IGNORECASE)
    if m:
        return f"{m.group(1)}-{m.group(2)} weeks"
    m = re.search(r'(\d+)\s*weeks?', text, re.IGNORECASE)
    if m:
        return f"{m.group(1)} weeks"
    m = re.search(r'(\d+)\s*(?:-|to|–)\s*(\d+)\s*months?', text, re.IGNORECASE)
    if m:
        return f"{m.group(1)}-{m.group(2)} months"
    m = re.search(r'(\d+)\s*months?\s*(?:internship|program|position)', text, re.IGNORECASE)
    if m:
        return f"{m.group(1)} months"
    return None


def _extract_stipend(text: str) -> Optional[str]:
    lower = text.lower()
    if any(p in lower for p in [
        "unpaid position", "unpaid internship", "this is an unpaid",
        "unpaid role", "this internship is unpaid",
    ]):
        return "Unpaid"

    m = re.search(r'\$(\d{1,3}(?:\.\d{1,2})?)\s*(?:/|per\s+)\s*hour', text, re.IGNORECASE)
    if m:
        return f"${m.group(1)}/hr"
    m = re.search(r'\$(\d{1,3})\s*/\s*hr\b', text, re.IGNORECASE)
    if m:
        return f"${m.group(1)}/hr"

    m = re.search(r'\$([\d,]+)\s*(?:/|per\s+)\s*month', text, re.IGNORECASE)
    if m:
        return f"${m.group(1)}/month"

    m = re.search(r'stipend\s*(?:of\s*)?\$([\d,]+)', text, re.IGNORECASE)
    if m:
        return f"${m.group(1)} stipend"

    return None


def _is_paid(title: str, description: str, stipend: Optional[str]) -> Optional[bool]:
    lower = (description or "").lower() + " " + (title or "").lower()
    if stipend == "Unpaid" or "unpaid" in lower:
        return False
    if stipend and stipend != "Unpaid":
        return True
    if any(p in lower for p in [
        "paid internship", "hourly rate", "stipend of ",
        "hourly wage", "compensation:",
    ]):
        return True
    return None


def _requires_us_work_auth(text: str) -> Optional[bool]:
    lower = text.lower()
    if any(p in lower for p in [
        "authorized to work in the u", "must be authorized to work",
        "no sponsorship", "cannot sponsor", "will not sponsor",
        "does not sponsor", "citizen or permanent resident",
        "us citizen or green card",
    ]):
        return True
    return None


def _extract_gpa(text: str) -> Optional[float]:
    m = re.search(
        r'(?:gpa|grade\s+point\s+average)\s*(?:of\s+)?(?:at\s+least\s+)?(\d\.\d{1,2})',
        text, re.IGNORECASE,
    )
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    m = re.search(r'(\d\.\d{1,2})\s*gpa\b', text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


_DATE_FORMATS = ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%m/%d/%Y", "%m-%d-%Y")


def _extract_deadline(text: str) -> Optional[str]:
    patterns = [
        r'(?:apply\s+by|application\s+deadline|applications?\s+close|deadline\s+to\s+apply)[:\s]+([A-Za-z]+\s+\d{1,2},?\s*\d{4})',
        r'(?:apply\s+by|application\s+deadline)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{4})',
        r'deadline[:\s]+([A-Za-z]+\s+\d{1,2},?\s*\d{4})',
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw = m.group(1).strip().rstrip(".,;")
            for fmt in _DATE_FORMATS:
                try:
                    return datetime.strptime(raw, fmt).date().isoformat()
                except ValueError:
                    continue
    return None


def _extract_academic_year(text: str) -> Optional[str]:
    lower = text.lower()
    years = []
    if "freshman" in lower or "first-year student" in lower:
        years.append("Freshman")
    if "sophomore" in lower:
        years.append("Sophomore")
    if "junior" in lower and "junior developer" not in lower and "junior engineer" not in lower:
        years.append("Junior")
    if ("senior" in lower and "senior developer" not in lower
            and "senior engineer" not in lower and "senior year" in lower):
        years.append("Senior")
    if "graduate student" in lower or "master's student" in lower or "phd student" in lower:
        years.append("Graduate")
    if not years:
        return None
    return "/".join(years)


def _extract_season(title: str, description: str) -> Optional[str]:
    combined = f"{title} {description}"
    m = re.search(r'\b(summer|spring|fall|autumn|winter)\s+(20\d\d)\b', combined, re.IGNORECASE)
    if m:
        season = m.group(1).lower()
        if season == "autumn":
            season = "fall"
        return f"{season}_{m.group(2)}"
    return None


def _is_remote(text: str) -> Optional[bool]:
    lower = text.lower()
    if "fully remote" in lower or "100% remote" in lower or "work from home" in lower:
        return True
    if "on-site only" in lower or "onsite only" in lower or "in-office only" in lower:
        return False
    if " remote" in lower or "remote position" in lower or "remote role" in lower:
        return True
    return None


def extract_metadata(title: str, description: str = "") -> dict:
    combined = f"{title or ''} {description or ''}"
    stipend = _extract_stipend(combined)
    return {
        "duration": _extract_duration(combined),
        "stipend": stipend,
        "is_paid": _is_paid(title, description, stipend),
        "requires_us_work_auth": _requires_us_work_auth(combined),
        "academic_year": _extract_academic_year(combined),
        "gpa_required": _extract_gpa(combined),
        "application_deadline": _extract_deadline(combined),
        "is_remote": _is_remote(combined),
        "season": _extract_season(title or "", description or ""),
    }


def classify(title: str, description: str = "") -> tuple[bool, dict]:
    """Convenience wrapper: (is_internship, metadata_dict).
    metadata is empty {} when not an internship."""
    if not is_internship(title, description):
        return False, {}
    return True, extract_metadata(title, description)


# ---------------------------------------------------------------------------
# Quality gate for is_published
# ---------------------------------------------------------------------------

def passes_quality_gate(title: str, external_apply_link: str, metadata: dict) -> bool:
    """Return True if internship meets publishing criteria."""
    if is_low_quality_title(title):
        return False
    if not external_apply_link:
        return False
    deadline = metadata.get("application_deadline")
    if deadline:
        try:
            if datetime.fromisoformat(deadline).date() < datetime.utcnow().date():
                return False
        except (ValueError, TypeError):
            pass
    return True
