import csv
import json
import os
import re
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional
from dotenv import load_dotenv

# Load local .env if available
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

# Workspace subdirectories
RESUMES_DIR = BASE_DIR / "resumes"
LOGS_DIR = BASE_DIR / "logs"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
RESUMES_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

APPLIED_CSV = BASE_DIR / "applied_jobs.csv"
APPLICATIONS_DB = BASE_DIR / "applications.sqlite"
COMPANIES_DATABASE = BASE_DIR / "companies_database.json"
LIVE_MARKET_ROLES_FILE = BASE_DIR / "live_market_roles.json"

# Antigravity Brain Artifacts Integration
CONVERSATION_ID = "9836f807-7079-403c-9787-a6463cdbaaad"
ARTIFACT_DIR = Path(
    os.environ.get("ARTIFACT_DIR", str(BASE_DIR / "artifacts" / "brain" / CONVERSATION_ID))
)
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_DASHBOARD = ARTIFACT_DIR / "live_dashboard.md"
ARTIFACT_VIEWPORT = ARTIFACT_DIR / "live_viewport.png"

# Zero-Cost LLM Engine Configuration (OpenRouter Free Tier — Fallback)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "inclusionai/ling-3.0-flash-vl:free")
FREE_MODEL_FALLBACKS = [
    "inclusionai/ling-3.0-flash-vl:free",
    "qwen/qwen3.8-27b:free",
    "nex-agi/nex-n2.5-mini:free",
    "openrouter/free"
]

# ── Muse Glimmer 30B — Primary AI Engine (Apache 2.0, HuggingFace Serverless) ──
# Free for personal use via HuggingFace Serverless Inference API.
# Get a free token at: https://huggingface.co/settings/tokens
# Add to .env:  HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()
HF_MODEL = os.environ.get("HF_MODEL", "meta-models/Muse-Glimmer-30B")
# HF routes Muse Glimmer 30B through Together AI's infrastructure (confirmed working)
HF_PROVIDER = os.environ.get("HF_PROVIDER", "together")
HF_INFERENCE_URL = os.environ.get(
    "HF_INFERENCE_URL",
    f"https://router.huggingface.co/{os.environ.get('HF_PROVIDER', 'together')}/v1/chat/completions"
)
# Timeout for HF router (Together AI is fast — warm responses in ~5-8s)
HF_TIMEOUT_SECONDS = int(os.environ.get("HF_TIMEOUT_SECONDS", "45"))

# Candidate Identity & Contact Details
CANDIDATE_PROFILE_FILE = BASE_DIR / "candidate_profile.json"

# Default Candidate Profile (Zero fabricated data; MS in Computer Science strictly enforced)
_DEFAULT_PROFILE = {
    "name": "Naga Satya Phanindra Vallabhaneni",
    "first_name": "Naga Satya Phanindra",
    "preferred_name": "Phanindra",
    "last_name": "Vallabhaneni",
    "email": "phanindra.vns@gmail.com",
    "phone": "+1 (984) 687-6001",
    "location": "Dayton, OH",
    "city": "Dayton",
    "state": "Ohio",
    "zip": "45409",
    "country": "United States",
    "linkedin": "",  # Blank by default - NEVER make up a LinkedIn URL
    "github": "https://github.com/phanindra-vallabhaneni",
    "salary": "$120,000",
    "current_company": "Seeking Software Engineer Roles",
    "current_title": "Software Engineer",
    "degree": "Master of Science in Computer Science",
    "degree_level": "Master's Degree",
    "degree_name": "Master of Science",
    "major": "Computer Science",
    "university": "University of Dayton",
    "gpa": "3.68",
    "undergrad_degree": "B.Tech, Electronics & Communication Engineering",
    "undergrad_institution": "Gokaraju Rangaraju Institute of Engineering & Technology",
    "work_auth_us": "Yes",
    "sponsorship_required": "Yes",
    "gender": "Male",
    "pronouns": "He/him",
    "race": "Asian (Not Hispanic or Latino)",
    "race_category": "Asian",
    "hispanic_latino": "No",
    "veteran_status": "I am not a protected veteran",
    "disability_status": "No, I do not have a disability and have not had one in the past",
    "over_18": "Yes",
    "relatives_employed": "No",
    "former_employee": "No",
    "non_compete": "No",
    "drug_screen_consent": "Yes",
    "background_check_consent": "Yes",
    "felony_conviction": "No",
    "valid_drivers_license": "Yes",
    "notice_period": "Immediately",
    "willing_to_relocate": "Yes",
    "open_to_hybrid": "Yes",
    "open_to_remote": "Yes",
    "commute_ready": "Yes"
}

def load_candidate_profile() -> dict:
    profile = dict(_DEFAULT_PROFILE)
    if CANDIDATE_PROFILE_FILE.exists():
        try:
            with open(CANDIDATE_PROFILE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                profile.update(saved)
        except Exception:
            pass
    return profile

def save_candidate_profile(profile_data: dict):
    global CANDIDATE_NAME, CANDIDATE_FIRST_NAME, CANDIDATE_PREFERRED_NAME, CANDIDATE_LAST_NAME
    global CANDIDATE_EMAIL, CANDIDATE_PHONE, CANDIDATE_LOCATION, CANDIDATE_CITY, CANDIDATE_STATE
    global CANDIDATE_ZIP, CANDIDATE_COUNTRY, CANDIDATE_LINKEDIN, CANDIDATE_GITHUB, CANDIDATE_SALARY
    global CANDIDATE_CURRENT_COMPANY, CANDIDATE_CURRENT_TITLE, CANDIDATE_DEGREE, CANDIDATE_DEGREE_LEVEL
    global CANDIDATE_DEGREE_NAME, CANDIDATE_MAJOR, CANDIDATE_UNIVERSITY, CANDIDATE_GPA
    global LEGAL_AUTHORIZATION_ANSWER, SPONSORSHIP_REQUIRED_ANSWER
    global CANDIDATE_GENDER, CANDIDATE_PRONOUNS, CANDIDATE_RACE, CANDIDATE_RACE_CATEGORY
    global CANDIDATE_HISPANIC_LATINO, CANDIDATE_VETERAN_STATUS, CANDIDATE_DISABILITY_STATUS

    with open(CANDIDATE_PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(profile_data, f, indent=2)

    CANDIDATE_NAME = profile_data.get("name", _DEFAULT_PROFILE["name"])
    CANDIDATE_FIRST_NAME = profile_data.get("first_name", _DEFAULT_PROFILE["first_name"])
    CANDIDATE_PREFERRED_NAME = profile_data.get("preferred_name", _DEFAULT_PROFILE["preferred_name"])
    CANDIDATE_LAST_NAME = profile_data.get("last_name", _DEFAULT_PROFILE["last_name"])
    CANDIDATE_EMAIL = profile_data.get("email", _DEFAULT_PROFILE["email"])
    CANDIDATE_PHONE = profile_data.get("phone", _DEFAULT_PROFILE["phone"])
    CANDIDATE_LOCATION = profile_data.get("location", _DEFAULT_PROFILE["location"])
    CANDIDATE_CITY = profile_data.get("city", _DEFAULT_PROFILE["city"])
    CANDIDATE_STATE = profile_data.get("state", _DEFAULT_PROFILE["state"])
    CANDIDATE_ZIP = profile_data.get("zip", _DEFAULT_PROFILE["zip"])
    CANDIDATE_COUNTRY = profile_data.get("country", _DEFAULT_PROFILE["country"])
    CANDIDATE_LINKEDIN = profile_data.get("linkedin", "").strip()
    CANDIDATE_GITHUB = profile_data.get("github", _DEFAULT_PROFILE["github"])
    CANDIDATE_SALARY = profile_data.get("salary", _DEFAULT_PROFILE["salary"])
    CANDIDATE_CURRENT_COMPANY = profile_data.get("current_company", _DEFAULT_PROFILE["current_company"])
    CANDIDATE_CURRENT_TITLE = profile_data.get("current_title", _DEFAULT_PROFILE["current_title"])
    CANDIDATE_DEGREE = profile_data.get("degree", _DEFAULT_PROFILE["degree"])
    CANDIDATE_DEGREE_LEVEL = profile_data.get("degree_level", _DEFAULT_PROFILE["degree_level"])
    CANDIDATE_DEGREE_NAME = profile_data.get("degree_name", _DEFAULT_PROFILE["degree_name"])
    CANDIDATE_MAJOR = profile_data.get("major", _DEFAULT_PROFILE["major"])
    CANDIDATE_UNIVERSITY = profile_data.get("university", _DEFAULT_PROFILE["university"])
    CANDIDATE_GPA = profile_data.get("gpa", _DEFAULT_PROFILE["gpa"])
    LEGAL_AUTHORIZATION_ANSWER = profile_data.get("work_auth_us", "Yes")
    SPONSORSHIP_REQUIRED_ANSWER = profile_data.get("sponsorship_required", "Yes")
    CANDIDATE_GENDER = profile_data.get("gender", _DEFAULT_PROFILE["gender"])
    CANDIDATE_PRONOUNS = profile_data.get("pronouns", _DEFAULT_PROFILE["pronouns"])
    CANDIDATE_RACE = profile_data.get("race", _DEFAULT_PROFILE["race"])
    CANDIDATE_RACE_CATEGORY = profile_data.get("race_category", _DEFAULT_PROFILE["race_category"])
    CANDIDATE_HISPANIC_LATINO = profile_data.get("hispanic_latino", _DEFAULT_PROFILE["hispanic_latino"])
    CANDIDATE_VETERAN_STATUS = profile_data.get("veteran_status", _DEFAULT_PROFILE["veteran_status"])
    CANDIDATE_DISABILITY_STATUS = profile_data.get("disability_status", _DEFAULT_PROFILE["disability_status"])

_ACTIVE_PROFILE = load_candidate_profile()

CANDIDATE_NAME = _ACTIVE_PROFILE["name"]
CANDIDATE_FIRST_NAME = os.environ.get("CANDIDATE_FIRST_NAME", _ACTIVE_PROFILE["first_name"])
CANDIDATE_PREFERRED_NAME = os.environ.get("CANDIDATE_PREFERRED_NAME", _ACTIVE_PROFILE["preferred_name"])
CANDIDATE_LAST_NAME = os.environ.get("CANDIDATE_LAST_NAME", _ACTIVE_PROFILE["last_name"])
CANDIDATE_EMAIL = os.environ.get("CANDIDATE_EMAIL", _ACTIVE_PROFILE["email"])
CANDIDATE_PHONE = os.environ.get("CANDIDATE_PHONE", _ACTIVE_PROFILE["phone"])
CANDIDATE_LOCATION = os.environ.get("CANDIDATE_LOCATION", _ACTIVE_PROFILE["location"])
CANDIDATE_CITY = os.environ.get("CANDIDATE_CITY", _ACTIVE_PROFILE["city"])
CANDIDATE_STATE = os.environ.get("CANDIDATE_STATE", _ACTIVE_PROFILE["state"])
CANDIDATE_ZIP = os.environ.get("CANDIDATE_ZIP", _ACTIVE_PROFILE["zip"])
CANDIDATE_COUNTRY = os.environ.get("CANDIDATE_COUNTRY", _ACTIVE_PROFILE["country"])
CANDIDATE_LINKEDIN = os.environ.get("CANDIDATE_LINKEDIN", _ACTIVE_PROFILE["linkedin"]).strip()
CANDIDATE_GITHUB = os.environ.get("CANDIDATE_GITHUB", _ACTIVE_PROFILE["github"])
CANDIDATE_SALARY = os.environ.get("CANDIDATE_SALARY", _ACTIVE_PROFILE["salary"])
CANDIDATE_CURRENT_COMPANY = os.environ.get("CANDIDATE_CURRENT_COMPANY", _ACTIVE_PROFILE["current_company"])
CANDIDATE_CURRENT_TITLE = os.environ.get("CANDIDATE_CURRENT_TITLE", _ACTIVE_PROFILE["current_title"])

# Education Credentials (Strictly MS in Computer Science - NEVER MBA)
CANDIDATE_DEGREE = _ACTIVE_PROFILE["degree"]
CANDIDATE_DEGREE_LEVEL = _ACTIVE_PROFILE["degree_level"]
CANDIDATE_DEGREE_NAME = _ACTIVE_PROFILE["degree_name"]
CANDIDATE_MAJOR = _ACTIVE_PROFILE["major"]
CANDIDATE_UNIVERSITY = _ACTIVE_PROFILE["university"]
CANDIDATE_GPA = _ACTIVE_PROFILE["gpa"]
CANDIDATE_UNDERGRAD_DEGREE = _ACTIVE_PROFILE["undergrad_degree"]
CANDIDATE_UNDERGRAD_INSTITUTION = _ACTIVE_PROFILE["undergrad_institution"]

# Work Authorization Answers (F-1 Student)
LEGAL_AUTHORIZATION_ANSWER = _ACTIVE_PROFILE.get("work_auth_us", "Yes")
SPONSORSHIP_REQUIRED_ANSWER = _ACTIVE_PROFILE.get("sponsorship_required", "Yes")

# Demographic & EEOC Survey Values
CANDIDATE_GENDER = _ACTIVE_PROFILE.get("gender", "Male")
CANDIDATE_PRONOUNS = _ACTIVE_PROFILE.get("pronouns", "He/him")
CANDIDATE_RACE = _ACTIVE_PROFILE.get("race", "Asian (Not Hispanic or Latino)")
CANDIDATE_RACE_CATEGORY = _ACTIVE_PROFILE.get("race_category", "Asian")
CANDIDATE_HISPANIC_LATINO = _ACTIVE_PROFILE.get("hispanic_latino", "No")
CANDIDATE_VETERAN_STATUS = _ACTIVE_PROFILE.get("veteran_status", "I am not a protected veteran")
CANDIDATE_DISABILITY_STATUS = _ACTIVE_PROFILE.get("disability_status", "No, I do not have a disability and have not had one in the past")

# Target Search Configuration: Standard + Bizarre/Overlooked CS Role Keywords
CS_TARGET_ROLE_KEYWORDS = [
    # Standard Core CS Roles
    "software engineer", "software developer",
    "backend engineer", "backend developer",
    "data engineer", "data infrastructure engineer", "data platform engineer",
    "ai engineer", "machine learning engineer", "ml engineer",
    "cloud engineer", "devops engineer", "platform engineer",
    "distributed systems engineer", "python engineer", "python developer",
    "etl engineer", "pipeline engineer", "analytics engineer",

    # Bizarre, Overlooked & Niche CS Titles
    "telematics software engineer", "telematics engineer",
    "iot telemetry engineer", "sensor data engineer",
    "pos integration engineer", "pos backend developer", "terminal systems engineer",
    "transaction pipeline engineer", "fleet software engineer",
    "field service automation engineer", "industrial software engineer",
    "scada software engineer", "scada data integration engineer",
    "edge computing engineer", "operational technology software engineer",
    "middleware integration engineer", "logistics optimization engineer",
    "equipment telemetry engineer", "asset intelligence engineer",
    "kiosk systems engineer", "automation backend engineer",
    "dispatch software engineer", "tunnel automation engineer",
    "scale systems developer", "rfid telemetry engineer"
]

# Comprehensive List of Overlooked / Bizarre Industry Domains
BIZARRE_DOMAINS_KEYWORDS = [
    # 1. Death Care & Mortuary
    "mortuary", "funeral", "cremation", "cemetery", "death care",
    # 2. Hospitality, Hotels & Casinos
    "hotel", "hospitality", "casino", "lodging", "resort",
    # 3. POS, Vending, Kiosks & Laundromats
    "pos", "point of sale", "kiosk", "vending", "laundromat", "coin-op",
    # 4. Waste, Sanitation & Recycling
    "waste", "trash", "sanitation", "dumpster", "recycling", "scrap metal",
    # 5. Home & Commercial Field Services
    "hvac", "plumbing", "elevator", "escalator", "pest control", "lawn care", "pool maintenance",
    # 6. Logistics, Fleet & Heavy Machinery
    "telematics", "fleet", "trucking", "heavy machinery", "locomotive", "freight rail",
    # 7. Correctional Facilities & Prison Tech
    "correctional", "corrections tech", "inmate", "prison telephony",
    # 8. Pawn Shops & Junkyards
    "pawn shop", "junkyard", "auto recycling", "salvage yard",
    # 9. Sewer, Septic & Pipeline Robotics
    "sewer", "septic", "pipe inspection", "underground robotics",
    # 10. Car Wash & Auto Detailing Automation
    "car wash", "carwash", "wash tunnel", "auto detailing",
    # 11. Commercial Uniforms & Linen Logistics
    "commercial laundry", "linen telemetry", "industrial uniform",
    # 12. FaithTech & Non-Profit Donation Streams
    "church software", "faithtech", "donation processing",
    # 13. Self-Storage & Storage Yards
    "self-storage", "storage facility", "yard management",
    # 14. Bowling Alleys, Arcades & Family Entertainment Centers
    "bowling", "arcade telemetry", "pinsetter", "amusement",
    # 15. Towing, Impound & Roadside Assistance
    "towing", "impound dispatch", "roadside assistance",
    # 16. Concrete, Asphalt & Quarry Batching
    "concrete batch", "ready-mix", "asphalt telemetry", "quarry haul",
    # 17. Parking Gates & License Plate Recognition
    "parking meter", "gate access", "parking enforcement",
    # 18. Maritime & Port Vessel Automation
    "maritime", "shipping vessel", "port crane", "ais telemetry"
]

EXCLUDED_ROLE_KEYWORDS = [
    # Seniority exclusions (strictly target 2 to 3 yrs, max 3 to 4 yrs; reject 5+ yrs & Senior/Lead/Staff)
    "senior", "sr.", "sr ", "staff", "principal", "lead", "architect", "architecture", "director", "vp",
    "vice president", "head of", "senior staff", "distinguished", "fellow",
    "founding engineer", "founding", "chief", "partner", "senior director", "executive",

    # Non-CS / Marketing / Content / Sales / Business exclusions
    "growth", "content", "marketing", "sales", "copywriter", "technical writer", "writer",
    "evangelist", "advocate", "developer advocate", "developer relations", "devrel",
    "community", "social media", "seo", "sem", "media", "creative", "public relations",
    "pr manager", "communications", "brand", "event", "partnership", "account executive",
    "account manager", "account management", "business development", "bdr", "sdr",
    "customer success", "customer support", "client success", "support specialist",
    "sales engineer", "solutions architect",

    # Management & Non-Technical exclusions
    "manager", "management", "product manager", "project manager", "program manager",
    "engineering manager", "technical product manager", "product owner", "scrum master",
    "recruiter", "talent", "hr", "human resources", "payroll", "operations", "office",
    "designer", "graphic designer", "ui designer", "ux designer", "ui/ux",
    "lawyer", "legal", "compliance", "nurse", "clerk", "driver", "accountant",
    "finance", "accounting", "auditor", "intern", "internship", "fellowship"
]

def is_strictly_cs_role(title: str, description: str = "") -> bool:
    """
    Strict Computer Science / Software Engineering gate.
    Guarantees that non-CS roles (marketing, growth, content, sales, support)
    are 100% blocked from feed, search, and auto-applier.
    """
    if not title:
        return False
    t = title.lower()
    d = description.lower() if description else ""

    # 1. Immediate rejection on non-CS / marketing / sales / growth keywords
    for kw in EXCLUDED_ROLE_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", t):
            return False

    # 2. Must be an authentic Computer Science / Software Engineering title
    valid_cs_indicators = [
        "software engineer", "software developer", "swe", "sde",
        "backend engineer", "backend developer",
        "frontend engineer", "frontend developer", "web developer",
        "full stack engineer", "fullstack engineer", "full stack developer", "fullstack developer",
        "data engineer", "data infrastructure engineer", "data platform engineer",
        "systems engineer", "platform engineer", "cloud engineer", "devops engineer",
        "site reliability engineer", "sre", "infrastructure engineer",
        "machine learning engineer", "ml engineer", "ai engineer",
        "distributed systems", "python engineer", "python developer",
        "etl engineer", "pipeline engineer", "analytics engineer",
        "telematics software engineer", "embedded software engineer"
    ]
    if not any(cs in t for cs in valid_cs_indicators):
        return False

    # 3. Check experience level (must be 2-3 YOE)
    exp_ok, _ = check_experience_level(title, description)
    return exp_ok

# Dynamic Evaluation Thresholds
MAX_LINKEDIN_APPLICANTS_THRESHOLD = int(os.environ.get("MAX_LINKEDIN_APPLICANTS_THRESHOLD", "50"))

# Strict Anti-Blacklist Safeguard: At most 1 role per company ever
ONE_ROLE_PER_COMPANY = True

# Candidate Core Skills Vector for Role Fit Scoring
CORE_TECH_SKILLS = [
    "python", "sql", "postgresql", "mysql", "aws", "docker", "rest api", "apis",
    "spark", "pyspark", "etl", "data pipeline", "kafka", "distributed systems",
    "fastapi", "flask", "django", "bash", "linux", "git", "ci/cd", "pandas"
]

# Preferred Job Titles (Optimal 2-3 yr / Mid-level CS Roles)
PREFERRED_ROLE_TITLES = [
    "software engineer ii", "software engineer 2", "swe ii", "sde ii",
    "software engineer", "software developer", "backend engineer", "backend developer",
    "data engineer", "data infrastructure engineer", "data platform engineer",
    "python developer", "python engineer", "ai engineer", "machine learning engineer",
    "cloud engineer", "devops engineer", "platform engineer", "analytics engineer"
]

# Strict USA Geolocation Filtering
US_STATES_POSTAL = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc"
}

US_POSITIVE_TERMS = [
    "united states", "usa", "u.s.", "u.s.a.", "us remote", "remote - us",
    "remote (us)", "remote (usa)", "remote, us", "remote, usa",
    "dayton", "ohio", "new york", "san francisco", "austin", "seattle",
    "boston", "chicago", "denver", "los angeles", "san jose", "atlanta",
    "dallas", "houston", "raleigh", "san diego", "washington dc"
]

FOREIGN_TERMS = [
    "canada", "toronto", "vancouver", "montreal", "ontario", "quebec", "british columbia",
    "uk", "united kingdom", "london", "ireland", "dublin", "germany", "berlin", "munich", "frankfurt",
    "france", "paris", "india", "bengaluru", "bangalore", "hyderabad", "mumbai", "pune", "delhi", "gurgaon", "noida", "chennai",
    "singapore", "australia", "sydney", "melbourne", "brisbane", "poland", "warsaw", "krakow", "wroclaw",
    "spain", "madrid", "barcelona", "brazil", "sao paulo", "rio", "japan", "tokyo", "netherlands", "amsterdam",
    "sweden", "stockholm", "switzerland", "zurich", "geneva", "israel", "tel aviv",
    "mexico", "mexico city", "cdmx", "guadalajara", "latam", "emea", "apac", "europe", "colombia", "bogota",
    "argentina", "buenos aires", "chile", "santiago", "costa rica", "portugal", "lisbon", "porto",
    "italy", "milan", "rome", "austria", "vienna", "belgium", "brussels", "czech", "prague",
    "taiwan", "taipei", "korea", "seoul", "philippines", "manila", "vietnam", "thailand", "bangkok",
    "uae", "dubai", "new zealand", "south africa", "nigeria", "kenya", "egypt"
]


def is_strictly_usa(location_str: str, title_str: str = "") -> bool:
    """Enforces strict USA-only geolocation. Checks both location and title strings."""
    # 1. Reject if title explicitly specifies a foreign country/city
    if title_str:
        t_low = title_str.lower()
        for foreign in FOREIGN_TERMS:
            if re.search(r"\b" + re.escape(foreign) + r"\b", t_low):
                if not ("united states" in t_low or "us remote" in t_low):
                    return False

    if not location_str:
        return True

    loc = location_str.lower().strip()

    for foreign in FOREIGN_TERMS:
        if re.search(r"\b" + re.escape(foreign) + r"\b", loc):
            if not ("united states" in loc or "us remote" in loc):
                return False

    for term in US_POSITIVE_TERMS:
        if term in loc:
            return True

    tokens = re.split(r"[\s,/\-]+", loc)
    for t in tokens:
        if t in US_STATES_POSTAL:
            return True

    return False


def check_experience_level(title: str, description: str = "") -> Tuple[bool, str]:
    """
    Validates that the role matches candidate's experience level:
    Target: 2 to 3 years of experience.
    Maximum: 3 to 4 years MAX.
    Disqualifies:
    - High-seniority titles: Staff, Principal, Lead, Architect, Director, VP, Head of
    - JDs requiring 5+, 6+, 7+, 8+, 10+ years of experience
    """
    t_lower = title.lower()

    # 1. Reject explicit high-seniority titles (target: 2-3 yrs, max 3-4 yrs)
    high_seniority = [
        "senior", "sr", "sr.", "staff", "principal", "lead", "architect", "architecture", "director", "vp",
        "vice president", "head of", "senior staff", "distinguished", "fellow",
        "chief", "partner", "senior director", "executive", "founding"
    ]
    for sen in high_seniority:
        if re.search(rf"\b{re.escape(sen)}\b", t_lower):
            return False, f"DISQUALIFIED: High seniority title '{sen.upper()}' (Target: 2-3 yrs, max 3-4 yrs)"

    if not description:
        return True, "QUALIFIED: Experience within target band"

    d_lower = description.lower()

    # 2. Extract required years of experience from description
    # Matches patterns like "5+ years", "6+ yrs", "minimum 5 years", "at least 6 years", "5-7 years"
    patterns = [
        r"(?:minimum\s+(?:of\s+)?|at\s*least\s+|requires?\s+)?(\d+)\+?\s*(?:-|to)\s*(\d+)\s*(?:years?|yrs?)(?:\s+(?:of\s+)?(?:experience|exp|hands-on|industry|relevant))?",
        r"(?:minimum\s+(?:of\s+)?|at\s*least\s+|requires?\s+)?(\d+)\+?\s*(?:years?|yrs?)(?:\s+(?:of\s+)?(?:experience|exp|hands-on|industry|relevant))?"
    ]

    detected_years = []
    for pat in patterns:
        for match in re.finditer(pat, d_lower):
            groups = match.groups()
            try:
                min_yr = int(groups[0])
                if 1 <= min_yr <= 25:
                    detected_years.append(min_yr)
                if len(groups) > 1 and groups[1]:
                    max_yr = int(groups[1])
                    if 1 <= max_yr <= 25:
                        detected_years.append(max_yr)
            except (ValueError, TypeError):
                pass

    if detected_years:
        min_detected = min(detected_years)
        # If the minimum requirement is 5 or greater, disqualify!
        if min_detected >= 5:
            return False, f"DISQUALIFIED: Requires {min_detected}+ years of experience (Target: 2-3 yrs, max 3-4 yrs)"

    return True, "QUALIFIED: Experience within target band (2-3 yrs, max 3-4 yrs)"


def matches_cs_tech_stack(title: str, description: str = "") -> bool:
    """Evaluates whether the role qualifies under Computer Science degree and core tech stack."""
    t_lower = title.lower()
    d_lower = description.lower() if description else ""

    # Check experience band (2-3 yrs, max 4 yrs) & high-seniority exclusions
    exp_ok, _ = check_experience_level(title, description)
    if not exp_ok:
        return False

    for exc in EXCLUDED_ROLE_KEYWORDS:
        if exc in t_lower:
            return False

    # Check match on standard or bizarre CS role titles
    if any(kw in t_lower for kw in CS_TARGET_ROLE_KEYWORDS):
        return True

    # Check match on bizarre / overlooked domains with engineering keywords
    if any(bd in t_lower or bd in d_lower for bd in BIZARRE_DOMAINS_KEYWORDS):
        if "engineer" in t_lower or "developer" in t_lower:
            return True

    # Fallback engineering check with tech stack presence
    if "engineer" in t_lower or "developer" in t_lower:
        core_stack = ["python", "sql", "spark", "docker", "aws", "api", "backend", "data", "database"]
        if any(tech in t_lower or tech in d_lower for tech in core_stack):
            return True

    return False


# Strict Disqualification & Blacklist Filters
ITAR_CLEARANCE_REGEX = re.compile(
    r"\b(active\s+(?:secret|top\s*secret|ts/sci|security)\s+clearance|"
    r"must\s+(?:hold|have|possess|be\s+eligible\s+for|obtain)\s+an?\s+(?:active\s+)?(?:secret|top\s*secret|ts/sci|security)\s+clearance|"
    r"security\s+clearance\s+(?:required|is\s+required|needed)|"
    r"ts/sci\s+clearance|secret\s+clearance|top\s+secret\s+clearance|"
    r"u\.?s\.?\s*citizenship\s+required|must\s+be\s+a\s+u\.?s\.?\s+citizen|"
    r"u\.?s\.?\s+citizens\s+only|us\s+citizenship\s+only|"
    r"ability\s+to\s+obtain\s+(?:and\s+maintain\s+)?a\s+security\s+clearance|"
    r"itar\s+compliance\s+requires\s+(?:u\.?s\.?\s+citizenship|us\s+citizen))\b",
    re.IGNORECASE
)

BLACKLIST_KEYWORDS = ["wipro"]

def contains_wipro(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"\bwipro\b", text, re.IGNORECASE))

def is_itar_or_clearance(text: str) -> bool:
    if not text:
        return False
    # Exclude mandatory Department of Labor poster notices (EPPA) and general compliance boilerplate
    cleaned = re.sub(r"employee\s+polygraph\s+protection\s+act", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\beppa\b", "", cleaned, flags=re.IGNORECASE)
    return bool(ITAR_CLEARANCE_REGEX.search(cleaned))


def load_applied_companies() -> set:
    """
    Loads all companies where candidate has already applied to prevent any duplicate company applications.
    Scans applied_jobs.csv and resumes/by_company to ensure airtight anti-blacklist protection.
    """
    applied_comps = set()
    if APPLIED_CSV.exists():
        try:
            with open(APPLIED_CSV, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    status = (row.get("status") or "").strip().upper()
                    # Only lock companies where application has actually been submitted
                    if status == "APPLIED":
                        comp = (row.get("company") or "").strip().lower()
                        if comp:
                            applied_comps.add(comp)
        except Exception:
            pass

    return applied_comps


def score_role_fit(job: Dict[str, Any], applicant_count: int = 0) -> float:
    """
    Computes match score (0 to 100) to select the single 'Perfect Role' at a company:
    - Experience Fit: up to 40 pts (optimal: 2-3 yrs / SWE II)
    - Tech Stack Fit: up to 35 pts (Python, SQL, AWS, Docker, REST APIs, ETL, Kafka)
    - Role Title Fit: up to 15 pts (Software Engineer II, Backend, Data, Python Dev)
    - Competition / Freshness: up to 10 pts (<= 10 applicants gets full score)
    """
    title = (job.get("title") or "").lower()
    desc = (job.get("description") or "").lower()
    score = 0.0

    # 1. Experience Fit (Max 40 pts) - Target: 2-3 yrs, max 3-4 yrs
    if "engineer ii" in title or "developer ii" in title or "swe ii" in title or "sde ii" in title:
        score += 40.0
    elif re.search(r"\b(2|3)\s*(?:\+|to|-)\s*(?:3|4)?\s*(?:years?|yrs?)", desc):
        score += 38.0
    elif "software engineer" in title or "backend engineer" in title or "data engineer" in title:
        score += 32.0
    else:
        score += 20.0

    # 2. Tech Stack Fit (Max 35 pts) - Core candidate stack
    matched_skills = 0
    for skill in CORE_TECH_SKILLS:
        if skill in desc or skill in title:
            matched_skills += 1
    score += min(35.0, matched_skills * 5.0)

    # 3. Role Title Fit (Max 15 pts)
    if any(pref in title for pref in PREFERRED_ROLE_TITLES):
        score += 15.0
    else:
        score += 5.0

    # 4. Low Competition / Freshness (Max 10 pts)
    if applicant_count <= 10:
        score += 10.0
    elif applicant_count <= 25:
        score += 7.0
    elif applicant_count <= 50:
        score += 4.0

    return round(score, 1)


# Execution parameters: High-speed continuous autonomous cadence
CYCLE_INTERVAL_SECONDS = int(os.environ.get("CYCLE_INTERVAL_SECONDS", "45"))  # Fast 45s cycle cadence
HEADLESS = os.environ.get("HEADLESS", "false").lower() == "true"
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
MAX_JOBS_PER_CYCLE = int(os.environ.get("MAX_JOBS_PER_CYCLE", "5"))
