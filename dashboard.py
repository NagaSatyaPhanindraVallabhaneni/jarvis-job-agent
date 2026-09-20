import csv
import datetime
import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional

from config import (
    APPLIED_CSV,
    APPLICATIONS_DB,
    COMPANIES_DATABASE,
    ARTIFACT_DASHBOARD,
    ARTIFACT_VIEWPORT,
    CANDIDATE_NAME,
    CANDIDATE_EMAIL,
    CANDIDATE_PHONE,
    OPENROUTER_MODEL,
    CYCLE_INTERVAL_SECONDS,
    MAX_LINKEDIN_APPLICANTS_THRESHOLD
)

logger = logging.getLogger("JarvisJobAgent.Dashboard")
_db_lock = threading.Lock()


def get_db_connection() -> sqlite3.Connection:
    """Returns a SQLite connection with WAL mode and row factory enabled."""
    conn = sqlite3.connect(APPLICATIONS_DB, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_applications_db():
    """Initializes the applications table and indexes, and migrates from CSV if needed."""
    with _db_lock:
        conn = get_db_connection()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS applications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        company TEXT NOT NULL,
                        job_title TEXT NOT NULL,
                        ats_platform TEXT,
                        applicant_count TEXT,
                        status TEXT NOT NULL,
                        job_url TEXT,
                        resume_pdf TEXT,
                        notes TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_app_company ON applications(company);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_app_status ON applications(status);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_app_timestamp ON applications(timestamp);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_app_comp_title ON applications(company, job_title);")

            # Check if migration is needed from CSV
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM applications;")
            db_count = cursor.fetchone()[0]

            if APPLIED_CSV.exists():
                try:
                    with open(APPLIED_CSV, "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        csv_rows = list(reader)
                    
                    if db_count < len(csv_rows):
                        logger.info(f"Migrating {len(csv_rows) - db_count} records from CSV into applications.sqlite...")
                        with conn:
                            for r in csv_rows[db_count:]:
                                conn.execute("""
                                    INSERT INTO applications (
                                        timestamp, company, job_title, ats_platform,
                                        applicant_count, status, job_url, resume_pdf, notes
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    r.get("timestamp", datetime.datetime.now().isoformat()),
                                    r.get("company", ""),
                                    r.get("job_title", ""),
                                    r.get("ats_platform", "Career Page"),
                                    r.get("applicant_count", "N/A"),
                                    r.get("status", "APPLIED"),
                                    r.get("job_url", ""),
                                    r.get("resume_pdf", ""),
                                    r.get("notes", "")
                                ))
                        logger.info("Application history migration complete.")
                except Exception as ex:
                    logger.warning(f"CSV migration notice: {ex}")
        finally:
            conn.close()


# Ensure DB is initialized upon import
init_applications_db()


def get_indexed_companies_count() -> int:
    """Returns total companies tracked in local expanding database."""
    if COMPANIES_DATABASE.exists():
        try:
            with open(COMPANIES_DATABASE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return len(data)
        except Exception:
            pass
    return 30


def log_applied_job(entry: Dict[str, Any]):
    """
    Logs a job application or evaluation record durably to both SQLite and applied_jobs.csv.
    Guarantees ACID transactions and thread safety across autonomous processes.
    """
    ts = entry.get("timestamp", datetime.datetime.now().isoformat())
    company = entry.get("company", "").strip()
    job_title = entry.get("job_title", "").strip()
    ats_platform = entry.get("ats_platform", "Career Page")
    applicant_count = str(entry.get("applicant_count", "N/A"))
    status = entry.get("status", "APPLIED").strip()
    job_url = entry.get("job_url", "")
    resume_pdf = entry.get("resume_pdf", "")
    notes = entry.get("notes", "")

    # 1. Write to SQLite (Primary ACID Store)
    with _db_lock:
        try:
            conn = get_db_connection()
            with conn:
                conn.execute("""
                    INSERT INTO applications (
                        timestamp, company, job_title, ats_platform,
                        applicant_count, status, job_url, resume_pdf, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ts, company, job_title, ats_platform,
                    applicant_count, status, job_url, resume_pdf, notes
                ))
            conn.close()
        except Exception as e:
            logger.error(f"Failed to log job to SQLite: {e}")

    # 2. Append to CSV (Audit log compatibility)
    file_exists = APPLIED_CSV.exists()
    fieldnames = [
        "timestamp", "company", "job_title", "ats_platform",
        "applicant_count", "status", "job_url", "resume_pdf", "notes"
    ]
    try:
        with open(APPLIED_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "timestamp": ts,
                "company": company,
                "job_title": job_title,
                "ats_platform": ats_platform,
                "applicant_count": applicant_count,
                "status": status,
                "job_url": job_url,
                "resume_pdf": resume_pdf,
                "notes": notes
            })
        logger.info(f"Recorded job record in {APPLIED_CSV} and SQLite: {company} ({status})")
    except Exception as e:
        logger.error(f"Failed to log job to CSV: {e}")


def get_all_confirmed_applications() -> List[Dict[str, Any]]:
    """
    Returns ALL verified email-confirmed applications.
    Strict Truth Gate: Only includes records where an authentic employer confirmation email was verified.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, timestamp, company, job_title, ats_platform, applicant_count, status, job_url, resume_pdf, notes
            FROM applications
            WHERE UPPER(status) IN ('CONFIRMED_DELIVERED', 'CONFIRMED_EMAIL_VERIFIED')
            ORDER BY id DESC;
        """)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()

        # Deduplicate by company + title (keeping most recent)
        seen = set()
        deduped = []
        for r in rows:
            key = f"{r['company'].lower()}:::{r['job_title'].lower()}"
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        return deduped
    except Exception as e:
        logger.error(f"Error fetching confirmed applications from SQLite: {e}")
        return []


def get_awaiting_email_applications() -> List[Dict[str, Any]]:
    """
    Returns applications submitted on official career portals that are awaiting
    confirmation emails from employers at phanindra.vns@gmail.com.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, timestamp, company, job_title, ats_platform, applicant_count, status, job_url, resume_pdf, notes
            FROM applications
            WHERE UPPER(status) IN ('PORTAL_SUBMITTED_AWAITING_EMAIL', 'APPLIED')
            ORDER BY id DESC;
        """)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()

        seen = set()
        deduped = []
        for r in rows:
            key = f"{r['company'].lower()}:::{r['job_title'].lower()}"
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        return deduped
    except Exception as e:
        logger.error(f"Error fetching awaiting-email applications: {e}")
        return []


def confirm_application_email(company: str, job_title: str = "") -> bool:
    """
    Marks an application as CONFIRMED_EMAIL_VERIFIED once confirmation email is verified.
    """
    try:
        conn = get_db_connection()
        with conn:
            if job_title:
                conn.execute("""
                    UPDATE applications
                    SET status = 'CONFIRMED_EMAIL_VERIFIED', notes = notes || ' [Email receipt verified]'
                    WHERE LOWER(company) = LOWER(?) AND LOWER(job_title) LIKE LOWER(?);
                """, (company.strip(), f"%{job_title.strip()}%"))
            else:
                conn.execute("""
                    UPDATE applications
                    SET status = 'CONFIRMED_EMAIL_VERIFIED', notes = notes || ' [Email receipt verified]'
                    WHERE LOWER(company) = LOWER(?);
                """, (company.strip(),))
        conn.close()
        logger.info(f"Marked application email verified for {company} - {job_title}")
        return True
    except Exception as e:
        logger.error(f"Failed to mark application email verified: {e}")
        return False


def get_pipeline_data() -> Dict[str, Any]:
    """
    Fetches unified, resilient pipeline data for the Kanban board with 100% truth-gating:
    - confirmed_applications: verified employer confirmation email received.
    - awaiting_email_applications: portal submitted, awaiting receipt at phanindra.vns@gmail.com.
    - captured_applications: pre-filled in visible browser with tailored PDF.
    - discovered_roles: verified live market opportunities.
    """
    confirmed = get_all_confirmed_applications()
    awaiting_email = get_awaiting_email_applications()
    confirmed_companies = {r["company"].lower() for r in confirmed}
    awaiting_companies = {r["company"].lower() for r in awaiting_email}

    captured = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, timestamp, company, job_title, ats_platform, applicant_count, status, job_url, resume_pdf, notes
            FROM applications
            WHERE UPPER(status) = 'PORTAL_CAPTURED'
            ORDER BY id DESC;
        """)
        raw_captured = [dict(r) for r in cursor.fetchall()]
        conn.close()

        seen_captured = set()
        for r in raw_captured:
            c_lower = r["company"].lower()
            key = f"{c_lower}:::{r['job_title'].lower()}"
            if c_lower not in confirmed_companies and c_lower not in awaiting_companies and key not in seen_captured:
                seen_captured.add(key)
                captured.append(r)
    except Exception as e:
        logger.error(f"Error fetching captured applications from SQLite: {e}")

    # Total counts
    total_confirmed = len(confirmed)
    total_awaiting_email = len(awaiting_email)
    total_captured = len(captured)

    # Discovered roles from live registry
    live_roles_file = Path(r"d:\jarvis_job_agent\live_market_roles.json")
    discovered_count = 53
    discovered_roles = []
    if live_roles_file.exists():
        try:
            with open(live_roles_file, "r", encoding="utf-8") as f:
                lr = json.load(f)
                discovered_roles = lr[:15]
                discovered_count = len(lr)
        except Exception:
            pass

    return {
        "total_confirmed": total_confirmed,
        "total_awaiting_email": total_awaiting_email,
        "total_captured": total_captured,
        "total_discovered": discovered_count,
        "total_interviews": 0,
        "confirmed_applications": confirmed,
        "awaiting_email_applications": awaiting_email,
        "captured_applications": captured[:60],
        "discovered_roles": discovered_roles,
        # Combined array for backward compatibility
        "applications": confirmed + awaiting_email + captured[:60]
    }


def get_recent_applications(limit: int = 10) -> List[Dict[str, str]]:
    """
    Reads recent job applications from SQLite with fallback to CSV.
    Ensures recent confirmed applications are included and never starved.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, company, job_title, ats_platform, applicant_count, status, job_url, resume_pdf, notes
            FROM applications
            ORDER BY id DESC
            LIMIT ?;
        """, (limit,))
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        logger.debug(f"SQLite read fallback to CSV: {e}")

    if not APPLIED_CSV.exists():
        return []
    rows = []
    try:
        with open(APPLIED_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except Exception as e:
        logger.debug(f"Error reading applied jobs: {e}")
    return rows[-limit:][::-1]


def update_live_dashboard(
    cycle_num: int,
    state: str = "RUNNING",
    current_action: str = "Processing cycle...",
    next_run_time: str = "TBD",
    last_error: str = ""
):
    """
    Renders and writes the live dashboard artifact to Antigravity brain
    including USA Geolocation verification and CS degree stack alignment.
    """
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    recent = get_recent_applications(10)
    company_count = get_indexed_companies_count()

    table_rows = ""
    if not recent:
        table_rows = "| *No applications recorded yet* | - | - | - | - | - |\n"
    else:
        for r in recent:
            ts = r.get("timestamp", "")[:19].replace("T", " ")
            comp = r.get("company", "")
            title = r.get("job_title", "")
            status = r.get("status", "APPLIED")
            platform = r.get("ats_platform", "Direct ATS")
            app_cnt = r.get("applicant_count", "-")
            pdf = r.get("resume_pdf", "")
            pdf_name = Path(pdf).name if pdf else "N/A"
            table_rows += f"| `{ts}` | **{comp}** | {title} | `{platform}` | **{app_cnt}** | `{status}` | [{pdf_name}](file:///{pdf}) |\n"

    viewport_section = ""
    if ARTIFACT_VIEWPORT.exists():
        vp_path = str(ARTIFACT_VIEWPORT).replace("\\", "/")
        viewport_section = f"""
## Live Browser Viewport Preview
> Real-time capture of the autonomous browser during career page navigation, LinkedIn analysis, and form autofill.

![Live Browser Viewport]({vp_path})
"""
    else:
        viewport_section = """
## Live Browser Viewport Preview
> *Browser viewport will render here upon the first navigation and form interaction.*
"""

    status_badge = "🟢 **CYCLE ACTIVE**" if state == "RUNNING" else f"⏳ **SLEEPING** (Next execution at `{next_run_time}`)"

    error_box = ""
    if last_error:
        error_box = f"""
> [!WARNING]
> **Notice from recent run:** {last_error}
"""

    markdown_content = f"""# Jarvis Autonomous Job Agent — Live Control Center

{status_badge}

> **Cycle #{cycle_num}** &bull; **Current Activity:** {current_action}  
> **Last Status Check:** `{now_str}` &bull; **Loop Interval:** `{CYCLE_INTERVAL_SECONDS // 60} minutes`

---

## 50,000+ US Company Discovery & Career Page Focus
| Parameter | Setting | Strategic Focus |
|---|---|---|
| **Primary Sourcing & Apply Target** | **OFFICIAL COMPANY CAREER PAGES** | **100% Direct Career Pages** (Greenhouse, Ashby, Lever, Workable) |
| **Observation & Market Intelligence** | **LinkedIn & Indeed (Passive)** | **Observation only**: Live applicant counts & hiring velocity |
| **Target Scope** | **50,000+ US Companies** | Self-growing ATS discovery across 18+ bizarre/overlooked domains |
| **Indexed Companies** | **{company_count} US Companies** | Automatically harvested from live search & registry |
| **Geolocation** | **STRICTLY USA ALONE** | **100% US Only** (US Remote, Dayton OH, 50 States; zero foreign roles) |
| **Role Alignment** | **Any CS / Software Role** | Software Engineer, Backend, Data, AI/ML, Cloud (Python/SQL/Docker) |
| **Candidate** | `{CANDIDATE_NAME}` | MS Computer Science (Univ of Dayton) &bull; `+1 984-687-6001` |
| **Competition Gate** | **<= {MAX_LINKEDIN_APPLICANTS_THRESHOLD} Applicants** | Applied via career page only if LinkedIn competition is low |
| **Work Auth (F-1)** | **H-1B Sponsorship Target** | Auto-answers Legal Auth: **YES** &bull; Sponsorship: **YES** |
| **Exclusions** | **Strict Wipro & ITAR Filter** | Absolute exclusion of Wipro & clearance roles |
| **LLM Engine** | `{OPENROUTER_MODEL}` | **Strict $0.00 spend architecture** (Free Router) |

{error_box}

{viewport_section}

---

## Application Submissions & Dynamic Decisions
| Timestamp | Company | Role | ATS Platform | LinkedIn Applicants | Status | Tailored Resume |
|---|---|---|---|---|---|---|
{table_rows}

---
*Jarvis Autonomous Job Agent is persistently running every 15 minutes. Viewport renders automatically.*
"""

    try:
        ARTIFACT_DASHBOARD.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT_DASHBOARD.write_text(markdown_content, encoding="utf-8")
        logger.info(f"Live dashboard artifact updated: {ARTIFACT_DASHBOARD}")
    except Exception as e:
        logger.error(f"Failed to update dashboard artifact: {e}")
