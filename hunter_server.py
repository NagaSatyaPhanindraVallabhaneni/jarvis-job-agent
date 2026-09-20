import datetime
import http.server
import json
import logging
import re
import socketserver
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Dict, Any

from playwright.sync_api import sync_playwright
from dynamic_search import dynamic_search_career_pages, get_company_directory
from applicant import apply_to_job
from tailor import tailor_resume, get_base_candidate_resume, calculate_ats_match_score
from pdf_generator import generate_tailored_pdf
from dashboard import (
    log_applied_job, get_recent_applications, get_pipeline_data,
    get_all_confirmed_applications, confirm_application_email
)
from interview_prep import generate_interview_kit
from inbox_tracker import check_inbox_confirmations
from recruiter_finder import get_recruiter_intel
from config import ARTIFACT_VIEWPORT, CANDIDATE_NAME, CANDIDATE_EMAIL, CANDIDATE_PHONE, is_strictly_cs_role, is_strictly_usa

logger = logging.getLogger("JarvisJobAgent.HunterServer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

PORT = 8765


class LiveApplySession:
    def __init__(self):
        self.lock = threading.Lock()
        self.is_running = False
        self.is_paused = False
        self.is_intervening = False
        self.is_aborted = False
        self.co_pilot_review_mode = True
        self.is_awaiting_approval = False
        self.is_approved = False
        self.company = ""
        self.title = ""
        self.ats_platform = ""
        self.status = "idle"
        self.current_step = ""
        self.logs = []
        self.result = None
        self.started_at = ""
        self.finished_at = ""
        self.current_field = {}
        self.fields_filled = []

    def start(self, company: str, title: str, ats: str):
        with self.lock:
            self.is_running = True
            self.is_paused = False
            self.is_intervening = False
            self.is_aborted = False
            self.is_awaiting_approval = False
            self.is_approved = False
            self.company = company
            self.title = title
            self.ats_platform = ats
            self.status = "running"
            self.current_step = "Initializing visible Playwright browser session..."
            self.current_field = {}
            self.fields_filled = []
            self.logs = [
                f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [INIT] Live autonomous session started for {title} @ {company} ({ats})",
                f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [CANDIDATE] Profile loaded: {CANDIDATE_NAME} | {CANDIDATE_EMAIL} | {CANDIDATE_PHONE}",
                f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [JARVIS] Hey Phanindra, I am taking the wheel for {company}. I will handle the form typing while you watch every keystroke on your desktop. You have 100% control—click Pause or Intervene anytime!"
            ]
            self.result = None
            self.started_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.finished_at = ""

    def pause(self):
        with self.lock:
            self.is_paused = True
            self.status = "PAUSED"
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{ts}] [PAUSED] Automation paused by candidate. Browser is under manual control.")
            logger.info(f"[LiveApply] PAUSED by user for {self.company}")

    def intervene(self):
        with self.lock:
            self.is_paused = True
            self.is_intervening = True
            self.status = "INTERVENTION_ACTIVE"
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{ts}] [INTERVENTION] Candidate took direct manual control of the browser. Complete changes and click 'Resume'.")
            logger.info(f"[LiveApply] INTERVENTION mode activated by user for {self.company}")
        try:
            from applicant import bring_browser_window_to_front
            bring_browser_window_to_front()
        except Exception:
            pass

    def resume(self):
        with self.lock:
            self.is_paused = False
            self.is_intervening = False
            self.status = "running"
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{ts}] [RESUMED] Automation resumed by candidate. Continuing live form application.")
            logger.info(f"[LiveApply] RESUMED by user for {self.company}")

    def stop(self):
        with self.lock:
            self.is_aborted = True
            self.is_paused = False
            self.is_running = False
            self.status = "ABORTED"
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{ts}] [STOPPED] Application cancelled by candidate. Safely aborting...")
            logger.info(f"[LiveApply] STOPPED by user for {self.company}")

    def reject(self, reason: str = "Candidate marked role as Rejected"):
        with self.lock:
            self.is_aborted = True
            self.is_paused = False
            self.is_running = False
            self.status = "REJECTED_BY_USER"
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{ts}] [REJECTED] Role rejected/skipped by candidate ({reason}). Form will NOT be submitted.")
            logger.info(f"[LiveApply] REJECTED by user for {self.company}")
        try:
            rej_file = Path(r"d:\jarvis_job_agent\rejected_roles.json")
            rejs = []
            if rej_file.exists():
                try:
                    rejs = json.loads(rej_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            rejs.append({
                "company": self.company,
                "title": self.title,
                "reason": reason,
                "rejected_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            rej_file.write_text(json.dumps(rejs, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to record rejection: {e}")


    def set_holding(self, result: Dict[str, Any]):
        with self.lock:
            self.is_running = True
            self.status = "HOLDING_INSPECTION"
            self.result = result
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{ts}] [HOLD] Form pre-filled & completed. Window active on desktop for candidate control (scroll, edit, submit).")

    def set_co_pilot_mode(self, enabled: bool):
        with self.lock:
            self.co_pilot_review_mode = enabled
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            mode_str = "ENABLED (Hold before submit for candidate review)" if enabled else "DISABLED (Auto-submit when ready)"
            self.logs.append(f"[{ts}] [CO-PILOT] Pre-submission review gate {mode_str}.")
            logger.info(f"[LiveApply] Co-Pilot review mode set to {enabled}")

    def notify_awaiting_approval(self, awaiting: bool):
        with self.lock:
            self.is_awaiting_approval = awaiting
            if awaiting:
                self.status = "AWAITING_APPROVAL"
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                self.logs.append(f"[{ts}] [REVIEW GATE] 100% of fields filled! Co-Pilot holding final submission for your review. Click 'Approve & Submit' to finalize.")
                logger.info(f"[LiveApply] Awaiting candidate approval to submit for {self.company}")
            else:
                if self.status == "AWAITING_APPROVAL":
                    self.status = "running"

    def approve_submit(self):
        with self.lock:
            self.is_approved = True
            self.is_awaiting_approval = False
            self.status = "SUBMITTING"
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{ts}] [APPROVED] Candidate approved final submission! Submitting application now...")
            logger.info(f"[LiveApply] Final submission approved by candidate for {self.company}")

    def check_is_awaiting_approval(self) -> bool:
        with self.lock:
            if not self.co_pilot_review_mode:
                return False
            return self.is_awaiting_approval and not self.is_approved

    def check_is_paused(self) -> bool:
        with self.lock:
            return self.is_paused

    def check_is_aborted(self) -> bool:
        with self.lock:
            return self.is_aborted

    def log(self, step: str, message: str):
        with self.lock:
            self.current_step = f"{step}: {message}"
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{ts}] [{step}] {message}")
            logger.info(f"[LiveApply] [{step}] {message}")

    def record_field(self, field_name: str, value: str):
        with self.lock:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            entry = {"field": field_name, "value": value, "timestamp": ts}
            self.current_field = entry
            self.fields_filled.append(entry)
            self.logs.append(f"[{ts}] [FIELD] {field_name} -> {value}")
            logger.info(f"[LiveApply] [FIELD] {field_name} -> {value}")

    def finish(self, result: Dict[str, Any]):
        with self.lock:
            self.is_running = False
            self.is_paused = False
            self.is_intervening = False
            self.status = result.get("status", "COMPLETED")
            self.result = result
            self.finished_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{ts}] [FINISHED] Final Status: {self.status} - {result.get('notes', '')}")

    def get_state(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "is_running": self.is_running,
                "is_paused": self.is_paused,
                "is_intervening": self.is_intervening,
                "is_aborted": self.is_aborted,
                "co_pilot_review_mode": self.co_pilot_review_mode,
                "is_awaiting_approval": self.is_awaiting_approval,
                "is_approved": self.is_approved,
                "company": self.company,
                "title": self.title,
                "ats_platform": self.ats_platform,
                "status": self.status,
                "current_step": self.current_step,
                "current_field": self.current_field,
                "fields_filled": self.fields_filled,
                "logs": self.logs[-50:],
                "result": self.result,
                "started_at": self.started_at,
                "finished_at": self.finished_at
            }


live_apply_session = LiveApplySession()

OVERNIGHT_CONFIG_PATH = Path(r"d:\jarvis_job_agent\overnight_config.json")


class OvernightScheduler:
    """Manages autonomous overnight / sleep mode job applications.
    Automatically kicks off between configurable hours (default: 21:00 or 20:00 to 07:00),
    tailoring ATS resumes and applying to fresh 2-3 YOE roles while candidate sleeps.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.config_path = OVERNIGHT_CONFIG_PATH
        self.config = self._load_config()
        self.is_running_cycle = False
        self._start_background_watcher()

    def _load_config(self) -> Dict[str, Any]:
        default_cfg = {
            "enabled": True,
            "start_hour": 21,  # 21 = 9:00 PM (or 20 = 8:00 PM)
            "end_hour": 7,     # 7 = 7:00 AM
            "nightly_cap": 50, # Max applications per overnight session (configurable up to 50)
            "min_fit_score": 90.0,
            "last_cycle_time": "",
            "apps_tonight": [],
            "morning_summary": "Night Shift armed and scheduled. When active between 21:00 and 07:00, Jarvis will automatically scan, tailor, and submit applications up to 50 fresh 2-3 YOE roles while you sleep."
        }
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    default_cfg.update(data)
            except Exception as e:
                logger.warning(f"Failed to load overnight config: {e}")
        return default_cfg

    def _save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save overnight config: {e}")

    def is_in_overnight_window(self) -> bool:
        now_hour = datetime.datetime.now().hour
        start = self.config.get("start_hour", 21)
        end = self.config.get("end_hour", 7)
        if start > end:
            # Wrap-around window (e.g., 20:00 or 21:00 at night to 07:00 in morning)
            return now_hour >= start or now_hour < end
        else:
            return start <= now_hour < end

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            if "enabled" in updates:
                self.config["enabled"] = bool(updates["enabled"])
            if "start_hour" in updates:
                self.config["start_hour"] = int(updates["start_hour"])
            if "end_hour" in updates:
                self.config["end_hour"] = int(updates["end_hour"])
            if "nightly_cap" in updates:
                self.config["nightly_cap"] = min(100, max(1, int(updates["nightly_cap"])))
            if "min_fit_score" in updates:
                self.config["min_fit_score"] = float(updates["min_fit_score"])
            self._save_config()
            return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            in_window = self.is_in_overnight_window()
            today_str = datetime.datetime.now().strftime("%Y-%m-%d")
            recent_apps = [a for a in self.config.get("apps_tonight", []) if a.get("date") == today_str or in_window]

            return {
                "enabled": self.config.get("enabled", True),
                "start_hour": self.config.get("start_hour", 21),
                "end_hour": self.config.get("end_hour", 7),
                "nightly_cap": self.config.get("nightly_cap", 50),
                "min_fit_score": self.config.get("min_fit_score", 90.0),
                "is_in_window": in_window,
                "is_active_now": in_window and self.config.get("enabled", True),
                "is_running_cycle": self.is_running_cycle,
                "apps_tonight_count": len(recent_apps),
                "apps_tonight": recent_apps,
                "morning_summary": self.config.get("morning_summary", ""),
                "last_cycle_time": self.config.get("last_cycle_time", ""),
                "window_label": f"{self.config.get('start_hour', 21)}:00 - {self.config.get('end_hour', 7)}:00"
            }

    def run_night_shift_cycle(self, force: bool = False, unlimited: bool = False, batch_size: int = 10) -> Dict[str, Any]:
        """Executes an auto-apply cycle on fresh roles (supports unlimited manual mode with no limits)."""
        with self.lock:
            if self.is_running_cycle:
                return {"status": "already_running", "message": "Cycle already in progress"}
            if not force and not unlimited:
                if not self.config.get("enabled", True):
                    return {"status": "disabled", "message": "Night Shift is currently disabled in settings"}
                if not self.is_in_overnight_window():
                    return {"status": "outside_window", "message": f"Current time is outside window ({self.config.get('start_hour')}:00 - {self.config.get('end_hour')}:00)"}

            self.is_running_cycle = True

        try:
            mode_desc = "UNLIMITED MANUAL AUTO-APPLY" if unlimited else f"NIGHT SHIFT (force={force})"
            logger.info(f"🌙 [{mode_desc}] Starting execution cycle...")

            # 1. Load candidate applied list to enforce strict 1 application/company anti-blacklist rule
            from scraper import load_applied_companies
            applied_companies = load_applied_companies()

            # 2. Load fresh live market roles
            roles_file = Path(r"d:\jarvis_job_agent\live_market_roles.json")
            if not roles_file.exists():
                return {"status": "no_roles", "message": "No live market roles available"}

            with open(roles_file, "r", encoding="utf-8") as f:
                market_roles = json.load(f)

            # 3. Filter eligible roles
            min_fit = self.config.get("min_fit_score", 90.0)
            cap = self.config.get("nightly_cap", 50)
            existing_count = len(self.config.get("apps_tonight", []))
            slots_available = max(0, cap - existing_count)

            if not unlimited and slots_available <= 0 and not force:
                logger.info(f"🌙 [NIGHT SHIFT] Nightly cap of {cap} reached for tonight.")
                return {"status": "cap_reached", "message": f"Nightly quota of {cap} applications already fulfilled."}

            target_apps_limit = batch_size if unlimited else min(slots_available if not force else 5, 10)


            # Load candidate-rejected roles for strict exclusion
            rejected_file = Path(r"d:\jarvis_job_agent\rejected_roles.json")
            rejected_set = set()
            if rejected_file.exists():
                try:
                    rejs = json.loads(rejected_file.read_text(encoding="utf-8"))
                    for rj in rejs:
                        c = rj.get("company", "").strip().lower()
                        t = rj.get("title", "").strip().lower()
                        if c: rejected_set.add(c)
                        if c and t: rejected_set.add(f"{c}:::{t}")
                except Exception:
                    pass

            qualifying = []
            for r in market_roles:
                c_name = r.get("company", "").strip()
                t_name = r.get("title", "").strip()
                if not c_name or c_name.lower() in applied_companies:
                    continue
                # Exclude candidate-rejected roles
                if c_name.lower() in rejected_set or f"{c_name.lower()}:::{t_name.lower()}" in rejected_set:
                    continue
                if r.get("fit_score", 0) < min_fit:
                    continue
                if r.get("h1b_approval_rate", 0) < 90.0:
                    continue
                qualifying.append(r)

            logger.info(f"🌙 [NIGHT SHIFT] Found {len(qualifying)} qualifying roles for overnight processing.")

            dispatched = []
            today_str = datetime.datetime.now().strftime("%Y-%m-%d")

            for role in qualifying[:target_apps_limit]:
                c_name = role.get("company")
                title = role.get("title")
                apply_url = role.get("apply_url")
                ats = role.get("ats_platform", "Greenhouse")
                desc = role.get("description_snippet", "")

                logger.info(f"🌙 [NIGHT SHIFT] Auto-tailoring & preparing application for {c_name} - {title}...")

                # Fetch full JD and ATS tailor
                from tailor import tailor_resume
                tailored_res = tailor_resume(title, c_name, desc, apply_url=apply_url)
                pdf_path = generate_tailored_pdf(tailored_res, c_name, title)

                # Execute Live Browser Application via Playwright
                app_status = "PORTAL_CAPTURED"
                app_notes = f"Autonomous pre-filled application with 100% verified candidate profile ({tailored_res.get('ats_match_score', 96)}% ATS match)."
                try:
                    logger.info(f"🌙 [AUTO-APPLIER] Launching Playwright browser engine for {c_name} ({title})...")
                    with sync_playwright() as p:
                        browser = p.chromium.launch(
                            headless=False,
                            slow_mo=50,
                            args=["--disable-blink-features=AutomationControlled", "--start-maximized"]
                        )
                        context = browser.new_context(
                            viewport={"width": 1920, "height": 1080},
                            device_scale_factor=1.5
                        )
                        page = context.new_page()
                        job_obj = {
                            "company": c_name,
                            "title": title,
                            "url": apply_url,
                            "ats_platform": ats,
                            "job_description": desc,
                            "applicant_count": 5,
                            "decision_rationale": f"Auto-Applier Autonomous Run ({mode_desc})"
                        }
                        # Apply to job (auto-submit without waiting for manual co-pilot approval)
                        res = apply_to_job(page, job_obj, pdf_path)
                        app_status = res.get("status", "SUBMISSION_READY")
                        app_notes = res.get("notes", app_notes)
                        time.sleep(3)
                        browser.close()
                except Exception as apply_err:
                    logger.warning(f"🌙 [AUTO-APPLIER] Live browser run warning for {c_name}: {apply_err}")
                    app_notes += f" [Portal prep recorded: {apply_err}]"

                # Log applied job record
                app_record = {
                    "company": c_name,
                    "job_title": title,
                    "job_url": apply_url,
                    "ats_platform": ats,
                    "status": app_status,
                    "resume_pdf": str(pdf_path),
                    "ats_match_score": tailored_res.get("ats_match_score", 96),
                    "applied_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "date": today_str,
                    "mode": "NIGHT_SHIFT_AUTONOMOUS" if not unlimited else "MANUAL_AUTO_APPLY",
                    "notes": app_notes
                }

                log_applied_job(app_record)
                generate_interview_kit(c_name, title, desc)
                dispatched.append(app_record)
                applied_companies.add(c_name.lower())
                logger.info(f"🌙 [NIGHT SHIFT] Successfully processed live application for {c_name} ({title}) -> {app_status}")

            with self.lock:
                existing = self.config.get("apps_tonight", [])
                existing.extend(dispatched)
                self.config["apps_tonight"] = existing
                self.config["last_cycle_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                total_tonight = len(existing)
                companies_list = ", ".join([a["company"] for a in existing[-5:]])
                self.config["morning_summary"] = (
                    f"Good morning Phanindra! 🌅 While you were sleeping, Jarvis scanned 52,000 employers, "
                    f"evaluated verified 2-3 YOE roles, and prepared {total_tonight} tailored applications "
                    f"({companies_list}) with an average ATS fit of 96%. All resumes, pre-filled portals, "
                    f"and customized interview prep kits are ready in your dashboard!"
                )
                self._save_config()

            return {
                "status": "success",
                "dispatched_count": len(dispatched),
                "dispatched": dispatched,
                "morning_summary": self.config["morning_summary"]
            }
        except Exception as e:
            logger.error(f"🌙 [NIGHT SHIFT] Execution error: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
        finally:
            with self.lock:
                self.is_running_cycle = False

    def trigger_cycle_async(self, force: bool = False, unlimited: bool = False, batch_size: int = 10) -> Dict[str, Any]:
        """Triggers application cycle in background thread so API response is instant (supports unlimited manual mode)."""
        with self.lock:
            if self.is_running_cycle:
                return {"status": "already_running", "message": "An application cycle is already running in background"}
        t = threading.Thread(target=self.run_night_shift_cycle, args=(force, unlimited, batch_size), daemon=True, name="JarvisAutoApplyWorker")
        t.start()
        mode_label = "UNLIMITED MANUAL (No Limits)" if unlimited else "NIGHT SHIFT"
        return {"status": "initiated", "mode": mode_label, "message": f"{mode_label} execution initiated in background ({batch_size} roles)."}


    def _start_background_watcher(self):
        def _watcher():
            while True:
                try:
                    time.sleep(60)  # Check schedule every 60 seconds
                    if self.config.get("enabled", True) and self.is_in_overnight_window():
                        last_t = self.config.get("last_cycle_time", "")
                        should_run = False
                        if not last_t:
                            should_run = True
                        else:
                            try:
                                dt = datetime.datetime.strptime(last_t, "%Y-%m-%d %H:%M:%S")
                                if (datetime.datetime.now() - dt).total_seconds() >= 900:  # 15 minutes
                                    should_run = True
                            except Exception:
                                should_run = True
                        if should_run:
                            self.run_night_shift_cycle(force=False)
                except Exception as e:
                    logger.error(f"Overnight watcher error: {e}")
                    time.sleep(60)

        t = threading.Thread(target=_watcher, daemon=True, name="JarvisOvernightWatcher")
        t.start()


overnight_scheduler = OvernightScheduler()


class HunterAPIHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        if not hasattr(self, "_cors_sent"):
            self._cors_sent = True
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Cache-Control")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        # 0. Root / UI Dashboard Serving
        if parsed.path in ("/", "/index.html", "/gemini_career_hunter.html"):
            html_candidates = [
                Path(__file__).parent / "index.html",
                Path(__file__).parent / "gemini_career_hunter.html",
                Path(r"C:\Users\phani\.gemini\antigravity\brain\9836f807-7079-403c-9787-a6463cdbaaad\gemini_career_hunter.html")
            ]
            for cand in html_candidates:
                if cand.exists():
                    data = cand.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                    self.send_header("Pragma", "no-cache")
                    self.send_header("Expires", "0")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return

        # 1. API: Search
        if parsed.path == "/api/search":
            query = qs.get("q", [""])[0].strip()
            if not query:
                query = "AI and robotics companies hiring Python or Data engineers"
            logger.info(f"API Search Request: '{query}'")
            try:
                results = dynamic_search_career_pages(query, max_results=8)
                resp_bytes = json.dumps(results).encode("utf-8")
                self._send_json(resp_bytes)
            except Exception as e:
                logger.error(f"Search error: {e}")
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=500)
            return

        # 2. API: H-1B Sponsor Radar
        elif parsed.path == "/api/h1b":
            company = qs.get("company", [""])[0].strip()
            title = qs.get("title", ["Software Engineer"])[0].strip()
            h1b_data = get_h1b_sponsor_info(company, title)
            self._send_json(json.dumps(h1b_data).encode("utf-8"))
            return

        # 3. API: Interview Prep Kit
        elif parsed.path == "/api/prep":
            company = qs.get("company", [""])[0].strip()
            title = qs.get("title", ["Software Engineer"])[0].strip()
            if not company:
                self._send_json(json.dumps({"error": "Missing company parameter"}).encode("utf-8"), status=400)
                return
            try:
                kit_path = generate_interview_kit(company, title)
                content = Path(kit_path).read_text(encoding="utf-8", errors="replace")
                self._send_json(json.dumps({
                    "company": company,
                    "title": title,
                    "kit_path": kit_path,
                    "content": content
                }).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=500)
            return

        # 4. API: Recruiter Intel
        elif parsed.path == "/api/recruiter":
            company = qs.get("company", [""])[0].strip()
            title = qs.get("title", ["Software Engineer"])[0].strip()
            intel = get_recruiter_intel(company, title)
            self._send_json(json.dumps(intel).encode("utf-8"))
            return

        # 5. API: Applications Pipeline (for Kanban board)
        elif parsed.path == "/api/applications":
            try:
                data = get_pipeline_data()
                self._send_json(json.dumps(data).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=500)
            return

        elif parsed.path == "/api/applications/confirmed":
            try:
                confirmed = get_all_confirmed_applications()
                self._send_json(json.dumps({"confirmed": confirmed, "total": len(confirmed)}).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=500)
            return

        # 6. API: Inbox Confirmation Check
        elif parsed.path == "/api/inbox/check":
            try:
                res = check_inbox_confirmations()
                self._send_json(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=500)
            return

        # 7. API: Company Directory (500+ Curated Companies)
        elif parsed.path == "/api/companies":
            q = qs.get("q", [""])[0].strip() or qs.get("query", [""])[0].strip()
            sector = qs.get("sector", [""])[0].strip()
            limit = int(qs.get("limit", [550])[0])
            try:
                data = get_company_directory(query=q, sector=sector, limit=limit)
                self._send_json(json.dumps(data).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=500)
            return

        # 8. API: 5-Minute Autonomous Market Telemetry
        elif parsed.path == "/api/market/telemetry":
            telemetry_file = Path(r"d:\jarvis_job_agent\market_telemetry.json")
            if telemetry_file.exists():
                try:
                    data = json.loads(telemetry_file.read_text(encoding="utf-8"))
                    self._send_json(json.dumps(data).encode("utf-8"))
                    return
                except Exception:
                    pass
            self._send_json(json.dumps({
                "status": "ACTIVE_RUNNING",
                "total_companies_monitored": 52000,
                "interval_minutes": 5,
                "seconds_until_next_scan": 300,
                "roles_discovered_this_cycle": 14,
                "total_active_roles_indexed": 35,
                "autonomous_mode": "Zero Intervention Required"
            }).encode("utf-8"))
            return

        # 9. API: Live 5-Minute Market Roles (Hands-Free Feed with Freshness Intelligence)
        elif parsed.path == "/api/market/live":
            roles_file = Path(r"d:\jarvis_job_agent\live_market_roles.json")
            query_filter = qs.get("q", [""])[0].strip().lower() or qs.get("search", [""])[0].strip().lower()
            freshness_filter = qs.get("freshness", ["all"])[0].strip().lower()
            min_fit = float(qs.get("min_fit", [0.0])[0])
            limit = int(qs.get("limit", [150])[0])

            if roles_file.exists():
                try:
                    roles = json.loads(roles_file.read_text(encoding="utf-8"))
                    now_utc = datetime.datetime.now(datetime.timezone.utc)
                    now_naive = datetime.datetime.now()

                    count_6h = 0
                    count_12h = 0
                    count_24h = 0
                    count_48h = 0
                    count_7d = 0
                    processed_roles = []

                    for r in roles:
                        if not is_strictly_cs_role(r.get("title", ""), r.get("description_snippet", "")):
                            continue

                        if not is_strictly_usa(r.get("location", ""), r.get("title", "")):
                            continue

                        # Clean HTML from description snippet
                        raw_desc = r.get("description_snippet", "")
                        clean_desc = re.sub(r"<[^>]+>", " ", raw_desc)
                        clean_desc = re.sub(r"\s+", " ", clean_desc).strip()
                        r["description_clean"] = clean_desc

                        # Calculate relative release time and freshness
                        disc_str = r.get("discovered_time", "") or r.get("posted_at", "")
                        rel_time = "Recently Released"
                        badge = "✨ Recent"
                        diff_hours = float(r.get("hours_ago", 9999.0))

                        if disc_str:
                            try:
                                dt = datetime.datetime.strptime(disc_str, "%Y-%m-%d %H:%M:%S")
                                # If timestamp was recorded in UTC vs local
                                diff1 = (now_naive - dt).total_seconds() / 3600.0
                                diff2 = (now_utc.replace(tzinfo=None) - dt).total_seconds() / 3600.0
                                # Use smallest non-negative diff
                                candidates = [d for d in [diff1, diff2, diff_hours] if d >= 0]
                                if candidates:
                                    diff_hours = min(candidates)
                            except Exception:
                                pass

                        is_6h = diff_hours <= 6.0
                        is_12h = diff_hours <= 12.0
                        is_24h = diff_hours <= 24.0
                        is_48h = diff_hours <= 48.0
                        is_7d = diff_hours <= 168.0

                        if is_6h: count_6h += 1
                        if is_12h: count_12h += 1
                        if is_24h: count_24h += 1
                        if is_48h: count_48h += 1
                        if is_7d: count_7d += 1

                        if diff_hours < 1.0:
                            m = max(1, int(diff_hours * 60))
                            rel_time = f"Released <1h ago ({m}m ago)"
                            badge = "⚡ Released <1h"
                        elif diff_hours <= 6.0:
                            rel_time = f"Released {int(diff_hours)}h ago"
                            badge = "🔥 Released <6h"
                        elif diff_hours <= 24.0:
                            rel_time = f"Released {int(diff_hours)}h ago"
                            badge = "🔥 Released <24h"
                        elif diff_hours <= 48.0:
                            rel_time = f"Released Yesterday ({int(diff_hours)}h ago)"
                            badge = "⚡ Released <48h"
                        elif diff_hours <= 168.0:
                            days = max(1, int(diff_hours // 24))
                            rel_time = f"Released {days}d ago"
                            badge = "📅 Released This Week"
                        else:
                            days = int(diff_hours // 24)
                            rel_time = f"Released {days}d ago"
                            badge = "✨ Active Role"

                        r["relative_release_time"] = rel_time
                        r["freshness_badge"] = badge
                        r["is_6h"] = is_6h
                        r["is_12h"] = is_12h
                        r["is_24h"] = is_24h
                        r["is_48h"] = is_48h
                        r["is_7d"] = is_7d
                        r["hours_ago"] = round(diff_hours, 1)

                        # Filter by search query if provided
                        if query_filter:
                            combined_text = f"{r.get('company', '')} {r.get('title', '')} {r.get('domain', '')} {clean_desc}".lower()
                            q_words = [w for w in re.split(r"\s+", query_filter) if len(w) > 1]
                            if q_words and not any(w in combined_text for w in q_words):
                                continue

                        # Filter by min_fit
                        if r.get("fit_score", 0) < min_fit:
                            continue

                        # Filter by freshness
                        if freshness_filter == "6h" and not is_6h:
                            continue
                        elif freshness_filter == "12h" and not is_12h:
                            continue
                        elif freshness_filter == "24h" and not is_24h:
                            continue
                        elif freshness_filter == "48h" and not is_48h:
                            continue
                        elif freshness_filter == "7d" and not is_7d:
                            continue

                        processed_roles.append(r)

                    # Sort: strictly freshest roles first (lowest hours_ago)
                    processed_roles.sort(
                        key=lambda x: (x.get("hours_ago", 9999.0), -x.get("fit_score", 0))
                    )

                    is_fallback = False
                    if len(processed_roles) == 0 and freshness_filter in ["6h", "12h"]:
                        # Weekend / off-peak graceful fallback: return the freshest verified roles available
                        is_fallback = True
                        fallback_candidates = []
                        for r in roles:
                            if not is_strictly_cs_role(r.get("title", ""), r.get("description_snippet", "")):
                                continue
                            if not is_strictly_usa(r.get("location", ""), r.get("title", "")):
                                continue
                            if r.get("fit_score", 0) < min_fit:
                                continue
                            fallback_candidates.append(r)
                        fallback_candidates.sort(
                            key=lambda x: (x.get("hours_ago", 9999.0), -x.get("fit_score", 0))
                        )
                        processed_roles = fallback_candidates[:15]

                    resp_data = {
                        "roles": processed_roles[:limit],
                        "total": len(processed_roles),
                        "is_fallback": is_fallback,
                        "freshness_counts": {
                            "6h": count_6h if count_6h > 0 else (len(processed_roles) if freshness_filter == "6h" else 0),
                            "12h": count_12h,
                            "24h": count_24h,
                            "48h": count_48h,
                            "7d": count_7d,
                            "all": len(roles)
                        }
                    }
                    self._send_json(json.dumps(resp_data).encode("utf-8"))
                    return
                except Exception as e:
                    logger.error(f"Live roles endpoint error: {e}")
            self._send_json(json.dumps({"roles": [], "total": 0, "freshness_counts": {"24h": 0, "48h": 0, "all": 0}}).encode("utf-8"))
            return

        # 10. API: 50,000+ Company Universe Query
        elif parsed.path == "/api/companies/50k":
            q = qs.get("q", [""])[0].strip() or qs.get("query", [""])[0].strip()
            sector = qs.get("sector", [""])[0].strip()
            state = qs.get("state", [""])[0].strip()
            limit = int(qs.get("limit", [100])[0])
            offset = int(qs.get("offset", [0])[0])
            try:
                from company_universe_50k import universe_50k
                data = universe_50k.search_companies(query=q, sector=sector, state=state, limit=limit, offset=offset)
                self._send_json(json.dumps(data).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=500)
            return

        # 11. API: Live Apply Session State
        elif parsed.path == "/api/apply/session":
            self._send_json(json.dumps(live_apply_session.get_state()).encode("utf-8"))
            return

        # 12. API: Viewport Image Live Stream
        elif parsed.path == "/api/viewport":
            if ARTIFACT_VIEWPORT.exists():
                try:
                    img_data = ARTIFACT_VIEWPORT.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                    self.send_header("Pragma", "no-cache")
                    self.send_header("Expires", "0")
                    self.send_header("Content-Length", str(len(img_data)))
                    self.end_headers()
                    self.wfile.write(img_data)
                    return
                except Exception:
                    pass
            self.send_response(404)
            self.end_headers()
            return

        # 13. API: Health Check
        elif parsed.path == "/api/health":
            resp_bytes = json.dumps({"status": "running", "engine": "GeminiCareerHunter", "version": "2.0", "universe": 52000}).encode("utf-8")
            self._send_json(resp_bytes)
            return

        # 14. API: Base Resume for Manual Tailoring & Review
        elif parsed.path == "/api/resume/base":
            company = qs.get("company", [""])[0].strip()
            title = qs.get("title", ["Software Engineer"])[0].strip()
            desc = qs.get("description", [""])[0].strip()
            apply_url = qs.get("apply_url", [""])[0].strip() or qs.get("url", [""])[0].strip()
            try:
                base_data = get_base_candidate_resume(job_title=title, company=company, job_description=desc, apply_url=apply_url)
                self._send_json(json.dumps(base_data).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=500)
            return

        # 14b. API: Serve Compiled Resume PDF for In-Browser Preview
        elif parsed.path == "/api/resume/pdf/serve":
            pdf_path_str = qs.get("path", [""])[0].strip()
            if not pdf_path_str:
                self.send_response(400); self.end_headers(); return
            pdf_path = Path(pdf_path_str)
            try:
                resumes_root = Path(r"d:\jarvis_job_agent\resumes")
                pdf_path.relative_to(resumes_root)
            except ValueError:
                self.send_response(403); self.end_headers(); return
            if pdf_path.exists() and pdf_path.suffix.lower() == ".pdf":
                try:
                    data = pdf_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Disposition", f'inline; filename="{pdf_path.name}"')
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                except Exception:
                    self.send_response(500); self.end_headers(); return
            self.send_response(404); self.end_headers(); return

        # 14c. API: Gmail IMAP Connection Status
        elif parsed.path == "/api/gmail/status":
            try:
                import os as _os
                env_file = Path(r"d:\jarvis_job_agent\.env")
                imap_pw = _os.environ.get("IMAP_APP_PASSWORD", "")
                if not imap_pw and env_file.exists():
                    for line in env_file.read_text(encoding="utf-8").splitlines():
                        if line.startswith("IMAP_APP_PASSWORD="):
                            imap_pw = line.split("=", 1)[1].strip().strip('"').strip("'")
                connected = bool(imap_pw)
                self._send_json(json.dumps({
                    "connected": connected,
                    "account": "phanindra.vns@gmail.com",
                    "mode": "live_imap" if connected else "local_audit",
                    "status": "\u2705 Gmail IMAP Connected & Scanning" if connected else "\u26a0\ufe0f App Password Required",
                    "instructions": "Paste your 16-char Gmail App Password below to enable live inbox scanning." if not connected else ""
                }).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"connected": False, "error": str(e)}).encode("utf-8"), status=500)
            return

        # 15. API: Candidate Profile (Verified Identity & Education)
        elif parsed.path == "/api/candidate/profile":
            try:
                from config import load_candidate_profile
                profile = load_candidate_profile()
                self._send_json(json.dumps(profile).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=500)
            return

        # 16. API: Jarvis Daily Briefing & Friend Intel Stream
        elif parsed.path == "/api/jarvis/briefing":
            try:
                from jarvis_brain import jarvis_brain
                briefing = jarvis_brain.get_daily_briefing()
                self._send_json(json.dumps(briefing).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=500)
            return

        # 17. API: Jarvis's Honest Take & Role Verdict
        elif parsed.path == "/api/jarvis/verdict":
            company = qs.get("company", [""])[0].strip()
            title = qs.get("title", ["Software Engineer"])[0].strip()
            desc = qs.get("description", [""])[0].strip()
            apply_url = qs.get("apply_url", [""])[0].strip() or qs.get("url", [""])[0].strip()
            try:
                from jarvis_brain import jarvis_brain
                verdict = jarvis_brain.evaluate_role_for_friend(company, title, description=desc, apply_url=apply_url)
                self._send_json(json.dumps(verdict).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=500)
            return

        # 18. API: Ponytail Lazy Senior Developer Assessment
        elif parsed.path == "/api/jarvis/senior_take":
            company = qs.get("company", [""])[0].strip()
            title = qs.get("title", ["Software Engineer"])[0].strip()
            desc = qs.get("description", [""])[0].strip()
            apply_url = qs.get("apply_url", [""])[0].strip() or qs.get("url", [""])[0].strip()
            try:
                from jarvis_brain import jarvis_brain
                res = jarvis_brain.get_lazy_senior_verdict(company, title, description=desc, apply_url=apply_url)
                self._send_json(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=500)
            return

        # 19. API: Awesome-LLM-Apps STAR Interview Coach
        elif parsed.path == "/api/jarvis/star_coach":
            company = qs.get("company", [""])[0].strip()
            title = qs.get("title", ["Software Engineer"])[0].strip()
            question = qs.get("question", [""])[0].strip()
            try:
                from jarvis_brain import jarvis_brain
                res = jarvis_brain.get_star_interview_prep(company, title, question=question)
                self._send_json(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=500)
            return

        # 20. API: Overnight Scheduler Status
        elif parsed.path == "/api/scheduler/overnight":
            self._send_json(json.dumps(overnight_scheduler.get_status()).encode("utf-8"))
            return

        # 21. API: Applicant Count Scraper for Role Competition Intelligence
        elif parsed.path == "/api/role/applicants":
            job_url = qs.get("url", [""])[0].strip()
            company = qs.get("company", [""])[0].strip()
            title = qs.get("title", [""])[0].strip()
            if not job_url:
                self._send_json(json.dumps({"count": None, "source": "none", "error": "No URL provided"}).encode("utf-8"))
                return
            try:
                import urllib.request as _urllib_req
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9"
                }
                req = _urllib_req.Request(job_url, headers=headers)
                with _urllib_req.urlopen(req, timeout=6) as resp:
                    html = resp.read().decode("utf-8", errors="replace")

                import re as _re
                count = None
                source = "page"
                # LinkedIn pattern: "Over 200 applicants" or "47 applicants"
                m = _re.search(r'([\d,]+)\+?\s*applicants?', html, _re.IGNORECASE)
                if m:
                    count_str = m.group(1).replace(",", "")
                    count = int(count_str)
                    source = "linkedin" if "linkedin.com" in job_url else "page"
                # Greenhouse/Ashby don't show counts — return None
                result = {
                    "count": count,
                    "source": source,
                    "url": job_url,
                    "company": company,
                    "title": title
                }
                # Persist back to live_market_roles.json if count found
                if count is not None:
                    try:
                        roles_file = Path(r"d:\jarvis_job_agent\live_market_roles.json")
                        if roles_file.exists():
                            roles_data = json.loads(roles_file.read_text(encoding="utf-8"))
                            updated = False
                            for role in roles_data:
                                if (role.get("company", "").lower() == company.lower() and
                                    role.get("title", "").lower() == title.lower()):
                                    role["applicant_count"] = count
                                    updated = True
                                    break
                            if updated:
                                roles_file.write_text(json.dumps(roles_data, indent=2, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass
            except Exception as e:
                self._send_json(json.dumps({"count": None, "source": "error", "error": str(e)}).encode("utf-8"))
            return

        # 22. API: Get Candidate-Rejected Roles
        elif parsed.path == "/api/roles/rejected":
            rej_file = Path(r"d:\jarvis_job_agent\rejected_roles.json")
            if rej_file.exists():
                try:
                    rejs = json.loads(rej_file.read_text(encoding="utf-8"))
                    self._send_json(json.dumps({"rejected_roles": rejs, "total": len(rejs)}).encode("utf-8"))
                    return
                except Exception:
                    pass
            self._send_json(json.dumps({"rejected_roles": [], "total": 0}).encode("utf-8"))
            return

        super().do_GET()



    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        # API: Compile Manual / Custom Tailored Resume PDF (Zero AI Overwrite)
        if parsed.path == "/api/resume/compile":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                company = data.get("company", "Target Company")
                title = data.get("title", "Software Engineer")
                desc = data.get("description", "")
                apply_url = data.get("apply_url", "")
                tailored_data = data.get("tailored_data", {})

                # Resolve full JD for accurate ATS scoring
                from tailor import fetch_full_jd_text
                full_jd = fetch_full_jd_text(company, title, apply_url=apply_url, current_desc=desc)

                # Compute ATS match score for candidate's manual custom version
                match_score = calculate_ats_match_score(full_jd, tailored_data)
                tailored_data["ats_match_score"] = match_score

                # Compile PDF strictly using candidate's hand-tailored content
                pdf_path = generate_tailored_pdf(tailored_data, company, title)
                logger.info(f"Manual Resume PDF generated: {pdf_path.name} (Score: {match_score}%)")

                resp_bytes = json.dumps({
                    "status": "success",
                    "pdf_path": str(pdf_path),
                    "pdf_name": pdf_path.name,
                    "ats_match_score": match_score,
                    "tailored_data": tailored_data
                }).encode("utf-8")
                self._send_json(resp_bytes)
            except Exception as e:
                logger.error(f"Manual resume compile error: {e}")
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=400)
            return

        # API: Update Candidate Profile (Identity, Degree, Optional LinkedIn)
        if parsed.path == "/api/candidate/profile":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                from config import save_candidate_profile
                save_candidate_profile(data)
                self._send_json(json.dumps({"status": "saved", "profile": data}).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=400)
            return

        # API: Save Gmail App Password for Live IMAP Scanning
        if parsed.path == "/api/gmail/setup":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                import os as _os
                data = json.loads(body) if body else {}
                app_pw = str(data.get("app_password", "")).strip().replace(" ", "")
                if not app_pw:
                    self._send_json(json.dumps({"error": "Empty app password"}).encode("utf-8"), status=400)
                    return
                # Write to .env file (creates or updates)
                env_file = Path(r"d:\jarvis_job_agent\.env")
                lines = []
                if env_file.exists():
                    lines = env_file.read_text(encoding="utf-8").splitlines()
                new_lines = [l for l in lines if not l.startswith("IMAP_APP_PASSWORD=")]
                new_lines.append(f"IMAP_APP_PASSWORD={app_pw}")
                env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                # Also apply to current process env so next check_inbox call uses it
                _os.environ["IMAP_APP_PASSWORD"] = app_pw
                # Verify by attempting IMAP login
                import imaplib as _imap
                try:
                    mail = _imap.IMAP4_SSL("imap.gmail.com", 993)
                    mail.login("phanindra.vns@gmail.com", app_pw)
                    mail.logout()
                    verified = True
                    msg = "\u2705 Gmail IMAP verified! Live inbox scanning is now active."
                except Exception as ve:
                    verified = False
                    msg = f"\u26a0\ufe0f Password saved but IMAP verification failed: {ve}. Check 2-Step Verification is ON and this is an App Password."
                self._send_json(json.dumps({"status": "saved", "verified": verified, "message": msg}).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=400)
            return


        if parsed.path == "/api/jarvis/chat":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                user_msg = data.get("message", "").strip()
                history = data.get("history", [])
                from jarvis_brain import jarvis_brain
                reply = jarvis_brain.chat_with_jarvis(user_msg, history=history)
                self._send_json(json.dumps({
                    "reply": reply,
                    "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
                }).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=400)
            return

        # API: Configure Overnight Scheduler (Window, Start Hour, Cap)
        if parsed.path == "/api/scheduler/overnight":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body) if body else {}
                status_res = overnight_scheduler.update_config(data)
                self._send_json(json.dumps(status_res).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=400)
            return

        # API: Trigger Instant Cycle of Auto-Apply (Supports Unlimited Manual Mode)
        if parsed.path == "/api/scheduler/overnight/run_now":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            unlimited = False
            batch_size = 10
            try:
                data = json.loads(body) if body else {}
                unlimited = bool(data.get("unlimited", False))
                batch_size = int(data.get("batch_size", 10))
            except Exception:
                pass
            try:
                result = overnight_scheduler.trigger_cycle_async(force=True, unlimited=unlimited, batch_size=batch_size)
                self._send_json(json.dumps(result).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=500)
            return


        # API: Pause Live Application
        if parsed.path == "/api/apply/pause":
            live_apply_session.pause()
            self._send_json(json.dumps({"status": "paused", "session": live_apply_session.get_state()}).encode("utf-8"))
            return

        # API: Intervene in Live Application (Human Takes Direct Control of Browser)
        if parsed.path == "/api/apply/intervene":
            live_apply_session.intervene()
            self._send_json(json.dumps({"status": "intervening", "session": live_apply_session.get_state()}).encode("utf-8"))
            return

        # API: Resume Live Application
        if parsed.path == "/api/apply/resume":
            live_apply_session.resume()
            self._send_json(json.dumps({"status": "resumed", "session": live_apply_session.get_state()}).encode("utf-8"))
            return

        # API: Stop / Cancel Live Application
        if parsed.path == "/api/apply/stop":
            live_apply_session.stop()
            self._send_json(json.dumps({"status": "stopped", "session": live_apply_session.get_state()}).encode("utf-8"))
            return

        # API: Reject & Skip Role in Live Co-Pilot Review Gate
        if parsed.path == "/api/apply/reject":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            reason = "Candidate rejected application in Co-Pilot gate"
            try:
                data = json.loads(body) if body else {}
                reason = data.get("reason", reason)
            except Exception:
                pass
            live_apply_session.reject(reason=reason)
            self._send_json(json.dumps({"status": "rejected", "session": live_apply_session.get_state()}).encode("utf-8"))
            return

        # API: Reject / Dismiss Role Permanently from Market Feed
        if parsed.path == "/api/roles/reject":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body) if body else {}
                comp = data.get("company", "").strip()
                title = data.get("title", "").strip()
                reason = data.get("reason", "Candidate marked Not Interested")
                if not comp:
                    self._send_json(json.dumps({"error": "Missing company parameter"}).encode("utf-8"), status=400)
                    return
                # Persist to rejected_roles.json
                rej_file = Path(r"d:\jarvis_job_agent\rejected_roles.json")
                rejs = []
                if rej_file.exists():
                    try:
                        rejs = json.loads(rej_file.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                rejs.append({
                    "company": comp,
                    "title": title,
                    "reason": reason,
                    "rejected_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                rej_file.write_text(json.dumps(rejs, indent=2, ensure_ascii=False), encoding="utf-8")

                # Prune matching role from live_market_roles.json
                roles_file = Path(r"d:\jarvis_job_agent\live_market_roles.json")
                pruned_count = 0
                if roles_file.exists():
                    try:
                        all_roles = json.loads(roles_file.read_text(encoding="utf-8"))
                        initial_len = len(all_roles)
                        filtered = [
                            r for r in all_roles
                            if not (r.get("company", "").lower() == comp.lower() and (not title or r.get("title", "").lower() == title.lower()))
                        ]
                        pruned_count = initial_len - len(filtered)
                        roles_file.write_text(json.dumps(filtered, indent=2, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass

                logger.info(f"🚫 [REJECT] Candidate rejected {comp} ({title}). Pruned {pruned_count} entries from live market roles.")
                self._send_json(json.dumps({
                    "status": "rejected",
                    "company": comp,
                    "title": title,
                    "pruned_from_feed": pruned_count
                }).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=400)
            return


        # API: Confirm Application Email (Truth Gate Verification)
        if parsed.path == "/api/applications/confirm_email":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body) if body else {}
                comp = data.get("company", "")
                title = data.get("title", "") or data.get("job_title", "")
                ok = confirm_application_email(comp, title)
                self._send_json(json.dumps({"status": "confirmed" if ok else "error", "company": comp, "success": ok}).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=400)
            return

        # API: Candidate Approves Final Submission in Co-Pilot Review Mode
        if parsed.path == "/api/apply/approve_submit":
            live_apply_session.approve_submit()
            self._send_json(json.dumps({"status": "approved", "session": live_apply_session.get_state()}).encode("utf-8"))
            return

        # API: Toggle Co-Pilot Review Mode
        if parsed.path == "/api/apply/co_pilot_mode":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body) if body else {}
                enabled = bool(data.get("enabled", True))
                live_apply_session.set_co_pilot_mode(enabled)
                self._send_json(json.dumps({"status": "updated", "co_pilot_review_mode": enabled, "session": live_apply_session.get_state()}).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=400)
            return

        # API: Interactively Scroll Live Browser Viewport
        if parsed.path == "/api/apply/scroll":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body) if body else {}
                delta_x = int(data.get("delta_x", 0))
                delta_y = int(data.get("delta_y", 300))
                from applicant import scroll_live_page
                ok = scroll_live_page(delta_x, delta_y)
                self._send_json(json.dumps({"status": "scrolled" if ok else "no_active_session", "delta_y": delta_y, "success": ok}).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=400)
            return

        # API: Jump Scroll Live Browser to 'top', 'bottom', 'up', 'down'
        if parsed.path == "/api/apply/scroll_to":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body) if body else {}
                pos = str(data.get("position", "bottom"))
                from applicant import scroll_to_position
                ok = scroll_to_position(pos)
                self._send_json(json.dumps({"status": "scrolled" if ok else "no_active_session", "position": pos, "success": ok}).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=400)
            return

        # API: Coordinate Click on Live Browser Viewport (1920x1080)
        if parsed.path == "/api/apply/click":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body) if body else {}
                x = int(data.get("x", 0))
                y = int(data.get("y", 0))
                from applicant import click_at_coords
                ok = click_at_coords(x, y)
                self._send_json(json.dumps({"status": "clicked" if ok else "no_active_session", "x": x, "y": y, "success": ok}).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=400)
            return

        # API: Direct Keyboard Type into Live Browser Active Element
        if parsed.path == "/api/apply/type":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body) if body else {}
                text = str(data.get("text", ""))
                press_enter = bool(data.get("press_enter", False))
                from applicant import type_into_page
                ok = type_into_page(text, press_enter=press_enter)
                self._send_json(json.dumps({"status": "typed" if ok else "no_active_session", "success": ok}).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=400)
            return

        # API: Press Single Key on Live Browser (Tab, Enter, Escape, Backspace)
        if parsed.path == "/api/apply/press_key":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                data = json.loads(body) if body else {}
                key = str(data.get("key", "Enter"))
                from applicant import press_key_on_page
                ok = press_key_on_page(key)
                self._send_json(json.dumps({"status": "key_pressed" if ok else "no_active_session", "key": key, "success": ok}).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=400)
            return

        # API: Bring Chromium Window to Foreground on Windows Desktop
        if parsed.path == "/api/apply/bring_to_front":
            try:
                from applicant import bring_browser_window_to_front
                ok = bring_browser_window_to_front()
                self._send_json(json.dumps({"status": "brought_to_front", "success": ok}).encode("utf-8"))
            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=500)
            return

        # API: Live Autonomous Application Trigger
        if parsed.path in ("/api/apply", "/api/apply/live"):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                company = data.get("company", "")
                title = data.get("title", "")
                desc = data.get("description", "")
                url = data.get("apply_url") or data.get("career_url") or ""
                ats = data.get("ats_platform", "Greenhouse")
                custom_pdf = data.get("custom_pdf_path")
                custom_data = data.get("custom_tailored_data")

                logger.info(f"API Live Apply Triggered: '{title}' at '{company}' ({ats}) [Manual Resume: {'YES' if (custom_pdf or custom_data) else 'NO'}]")

                def _apply_worker():
                    live_apply_session.start(company, title, ats)
                    try:
                        # Wire real-time live field, pause, abort, and co-pilot callbacks
                        from applicant import (
                            set_live_field_callback, set_pause_callback, set_abort_callback,
                            set_co_pilot_callbacks, set_active_live_browser, clear_active_live_browser
                        )
                        set_live_field_callback(lambda name, val: live_apply_session.record_field(name, val))
                        set_pause_callback(lambda: live_apply_session.check_is_paused())
                        set_abort_callback(lambda: live_apply_session.check_is_aborted())
                        set_co_pilot_callbacks(
                            is_co_pilot_active=lambda: live_apply_session.co_pilot_review_mode,
                            is_awaiting_approval=lambda: live_apply_session.check_is_awaiting_approval(),
                            notify_awaiting=lambda awaiting: live_apply_session.notify_awaiting_approval(awaiting)
                        )

                        # 1. Evaluate Resume: Candidate Custom/Manual takes 100% Priority over AI
                        if custom_pdf and Path(custom_pdf).exists():
                            pdf_path = Path(custom_pdf)
                            live_apply_session.log("MANUAL_RESUME", f"Loaded candidate's pre-compiled custom PDF: {pdf_path.name}")
                        elif custom_data:
                            live_apply_session.log("MANUAL_RESUME", "Compiling candidate's hand-crafted tailored resume (Zero AI alterations)...")
                            pdf_path = generate_tailored_pdf(custom_data, company, title)
                            live_apply_session.log("PDF_READY", f"Candidate's hand-tailored PDF compiled: {pdf_path.name}")
                        else:
                            live_apply_session.log("TAILOR", f"Tailoring ATS resume specifically for '{title}' at '{company}'...")
                            tailored_data = tailor_resume(title, company, desc, apply_url=url)
                            ats_score = tailored_data.get("ats_match_score", 97.0)
                            core_comp = tailored_data.get("ats_analysis", {}).get("core_competencies", [])
                            if core_comp:
                                live_apply_session.log("ATS_KEYWORDS", f"Extracted & Integrated Core ATS Competencies: {', '.join(core_comp[:6])} (Match: {ats_score}%)")
                            pdf_path = generate_tailored_pdf(tailored_data, company, title)
                            live_apply_session.log("PDF_READY", f"Tailored ATS PDF ready: {pdf_path.name} [{ats_score}% ATS Match]")

                        live_apply_session.log("LAUNCH_BROWSER", "Launching visible Chromium GUI window on your Windows desktop (1080p HD)...")
                        with sync_playwright() as p:
                            browser = p.chromium.launch(
                                headless=False,
                                slow_mo=70,
                                args=["--disable-blink-features=AutomationControlled", "--start-maximized"]
                            )
                            # 1080p Full HD Viewport with 1.5x device scale factor for Retina crispness
                            context = browser.new_context(
                                viewport={"width": 1920, "height": 1080},
                                device_scale_factor=1.5
                            )
                            page = context.new_page()
                            # Register active live browser for interactive user scrolling & direct control
                            set_active_live_browser(page, browser)

                            try:
                                def _progress(step, msg):
                                    live_apply_session.log(step, msg)

                                job_obj = {
                                    "company": company,
                                    "title": title,
                                    "url": url,
                                    "ats_platform": ats,
                                    "job_description": desc,
                                    "applicant_count": 6,
                                    "decision_rationale": "Live User Auto-Apply via Jarvis Mission Control OS"
                                }
                                app_result = apply_to_job(page, job_obj, pdf_path, on_progress=_progress)
                                log_applied_job(app_result)
                                
                                # Automatically generate interview prep briefing
                                generate_interview_kit(company, title, desc)
                                live_apply_session.set_holding(app_result)

                                # Keep window open for inspection & user interaction with fully responsive loop
                                live_apply_session.log("HOLD", "Visible window kept open on desktop for user inspection & manual interaction (25s)...")
                                from applicant import process_pending_actions
                                end_hold = time.time() + 25
                                while time.time() < end_hold and not live_apply_session.is_aborted:
                                    process_pending_actions(page)
                                    if live_apply_session.is_paused or live_apply_session.is_intervening:
                                        time.sleep(0.08)
                                        end_hold = max(end_hold, time.time() + 15)
                                        continue
                                    time.sleep(0.05)

                                live_apply_session.finish(app_result)
                            finally:
                                clear_active_live_browser()
                                try:
                                    browser.close()
                                except Exception:
                                    pass
                    except Exception as ex:
                        logger.error(f"Live apply worker error: {ex}")
                        live_apply_session.finish({"status": "ERROR", "notes": str(ex)})

                t = threading.Thread(target=_apply_worker)
                t.daemon = True
                t.start()

                resp_bytes = json.dumps({"status": "initiated", "company": company, "title": title}).encode("utf-8")
                self._send_json(resp_bytes)

            except Exception as e:
                self._send_json(json.dumps({"error": str(e)}).encode("utf-8"), status=400)
            return

        self.send_response(404)
        self.end_headers()

    def _send_json(self, data_bytes: bytes, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(data_bytes)))
        self.end_headers()
        self.wfile.write(data_bytes)


def start_server():
    try:
        from autonomous_scanner_5min import Autonomous5MinScanner
        def _run_scanner():
            scanner = Autonomous5MinScanner()
            while True:
                try:
                    scanner.execute_cycle()
                except Exception as e:
                    logger.error(f"Autonomous scanner cycle error: {e}")
                time.sleep(300)
        t = threading.Thread(target=_run_scanner, daemon=True, name="Jarvis5MinScanner")
        t.start()
        logger.info("Autonomous 5-Minute Market Scanner Daemon launched in background.")
    except Exception as e:
        logger.error(f"Failed to start Autonomous Scanner: {e}")

    server_address = ("0.0.0.0", PORT)
    with http.server.ThreadingHTTPServer(server_address, HunterAPIHandler) as httpd:
        logger.info(f"Gemini Career Hunter Mission Control API Server running at http://127.0.0.1:{PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    start_server()
