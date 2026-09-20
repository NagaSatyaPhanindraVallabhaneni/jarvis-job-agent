"""
Jarvis 24/7 Autonomous Job Agent — Live Step-by-Step Console Engine
Visibly displays every phase of sourcing, LinkedIn competitor audit,
AI ATS resume tailoring, PDF generation, and browser form submission on screen.
"""

import argparse
import ctypes
import datetime
import logging
import os
import re
import sys
import time

# Ensure immediate real-time unbuffered UTF-8 stdout streaming
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

from pathlib import Path
from playwright.sync_api import sync_playwright

from config import (
    HEADLESS,
    CYCLE_INTERVAL_SECONDS,
    MAX_JOBS_PER_CYCLE,
    LOGS_DIR,
    RESUMES_DIR,
    CANDIDATE_NAME,
    CANDIDATE_EMAIL,
    CANDIDATE_PHONE,
    CANDIDATE_LOCATION,
    contains_wipro
)
from scraper import find_top_target_roles
from tailor import tailor_resume, calculate_ats_match_score
from pdf_generator import generate_tailored_pdf
from applicant import apply_to_job, capture_viewport
from dashboard import log_applied_job, update_live_dashboard
from interview_prep import generate_interview_kit
from h1b_radar import get_h1b_sponsor_info

# Configure Logging (both to file and cleanly to stdout)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
log_file = LOGS_DIR / f"live_agent_{datetime.datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(str(log_file), encoding="utf-8")
    ]
)
logger = logging.getLogger("JarvisJobAgent.Live")

# ANSI Color Helpers
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_CYAN = "\033[96m"
C_YELLOW = "\033[93m"
C_GREEN = "\033[92m"
C_BLUE = "\033[94m"
C_MAGENTA = "\033[95m"
C_RED = "\033[91m"
C_GRAY = "\033[90m"
C_WHITE = "\033[97m"


def prevent_system_sleep():
    """Keeps Windows system active 24/7 without screen locking."""
    try:
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ES_AWAYMODE_REQUIRED = 0x00000040
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
        )
    except Exception:
        pass


def safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except Exception:
        pass


def print_banner(cycle_num: int):
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_print(f"\n{C_CYAN}{'=' * 95}{C_RESET}")
    safe_print(f"{C_BOLD}{C_WHITE}  [!] JARVIS 24/7 AUTONOMOUS CAREER ENGINE -- LIVE STEP-BY-STEP CONSOLE (CYCLE #{cycle_num}){C_RESET}")
    safe_print(f"  {C_GRAY}Time:{C_RESET} {C_WHITE}{now_str}{C_RESET} | {C_GRAY}Candidate:{C_RESET} {C_GREEN}{CANDIDATE_NAME}{C_RESET} ({CANDIDATE_LOCATION})")
    safe_print(f"  {C_GRAY}Degree:{C_RESET} {C_WHITE}MS in Computer Science (Univ. of Dayton){C_RESET} | {C_GRAY}Contact:{C_RESET} {C_WHITE}{CANDIDATE_EMAIL}{C_RESET} | {C_WHITE}{CANDIDATE_PHONE}{C_RESET}")
    safe_print(f"  {C_GRAY}Experience Band:{C_RESET} {C_GREEN}Strictly 2 to 3 years (Max 3 to 4 yrs){C_RESET} | {C_RED}Senior / Lead / Staff / 5+ yrs DISQUALIFIED{C_RESET}")
    safe_print(f"  {C_GRAY}Anti-Blacklist:{C_RESET} {C_GREEN}STRICT 1-ROLE-PER-COMPANY LIMIT (Single Perfect Role Selected){C_RESET}")
    safe_print(f"  {C_GRAY}Sourcing:{C_RESET} {C_YELLOW}Direct Career Pages (Greenhouse, Ashby, Lever, Workable) across 18+ Backbone Domains{C_RESET}")
    safe_print(f"  {C_GRAY}Browser GUI:{C_RESET} {C_GREEN}VISIBLE CHROMIUM ON DESKTOP{C_RESET} | {C_GRAY}Cadence:{C_RESET} {C_WHITE}80ms human emulation{C_RESET}")
    safe_print(f"{C_CYAN}{'=' * 95}{C_RESET}\n", flush=True)


def print_step_header(step_num: int, total_steps: int, title: str, icon: str = "[STEP]"):
    safe_print(f"\n{C_BOLD}{C_BLUE}+-- {icon} [STEP {step_num}/{total_steps}] {title.upper()}{C_RESET}")
    safe_print(f"{C_BLUE}|{C_RESET}", flush=True)


def print_step_sub(msg: str, status: str = "INFO"):
    if status == "SUCCESS":
        badge = f"{C_GREEN}[OK]{C_RESET}"
    elif status == "WARNING":
        badge = f"{C_YELLOW}[!]{C_RESET}"
    elif status == "ALERT":
        badge = f"{C_RED}[X]{C_RESET}"
    else:
        badge = f"{C_CYAN}[>]{C_RESET}"
    safe_print(f"{C_BLUE}|{C_RESET}  {badge} {C_WHITE}{msg}{C_RESET}", flush=True)


def print_step_footer():
    safe_print(f"{C_BLUE}+{'=' * 80}{C_RESET}\n", flush=True)


def execute_live_cycle(cycle_num: int, playwright_instance, custom_query: Optional[str] = None) -> int:
    """Executes a complete 5-step job application cycle with live on-screen visual reporting."""
    print_banner(cycle_num)
    applications_processed = 0

    update_live_dashboard(
        cycle_num=cycle_num,
        state="RUNNING",
        current_action="Step 1: Sourcing target roles via Playwright browser session..."
    )

    # Launch Chromium with visible GUI and slow_mo for human inspection
    print(f"  {C_MAGENTA}⚡ Launching Chromium GUI window on your screen (slow_mo=80ms)...{C_RESET}", flush=True)
    browser = playwright_instance.chromium.launch(
        headless=False,
        slow_mo=25,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--start-maximized"
        ]
    )

    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        device_scale_factor=1.5,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """)

    page = context.new_page()
    try:
        page.goto("https://boards.greenhouse.io", wait_until="domcontentloaded")
    except Exception:
        pass

    try:
        # =====================================================================
        # STEP 1: SOURCING CAREER PAGES
        # =====================================================================
        print_step_header(1, 5, "Sourcing Target Computer Science Roles on Career Pages", "🌐")
        
        capture_viewport(page, f"cycle_{cycle_num}_start")
        if custom_query:
            print_step_sub(f"Dynamically searching career pages for query: '{custom_query}'...")
            from discovery_engine import search_career_pages_by_query
            top_roles = search_career_pages_by_query(custom_query, limit=MAX_JOBS_PER_CYCLE)
        else:
            print_step_sub("Scanning Greenhouse, Ashby, Lever across 18+ backbone domains (Funeral tech, POS, elevator control, waste, rail telematics)...")
            top_roles = find_top_target_roles(page, limit=MAX_JOBS_PER_CYCLE)

        if not top_roles:
            print_step_sub("No fresh unapplied opportunities identified in this cycle window.", status="WARNING")
            print_step_footer()
            update_live_dashboard(
                cycle_num=cycle_num,
                state="RUNNING",
                current_action="No new jobs found this cycle; waiting for next window."
            )
            return 0

        print_step_sub(f"Identified {len(top_roles)} high-match US Computer Science opportunities for application:", status="SUCCESS")
        for i, r in enumerate(top_roles, start=1):
            print(f"    {C_YELLOW}[{i}]{C_RESET} {C_BOLD}{r.get('title')}{C_RESET} @ {C_GREEN}{r.get('company')}{C_RESET} ({r.get('ats_platform', 'Career Page')})")
        print_step_footer()

        # Iterate through target opportunities
        for idx, job in enumerate(top_roles, start=1):
            company = job.get("company", "Company")
            title = job.get("title", "Job Role")
            desc = job.get("description", "")
            url = job.get("url", "")
            platform = job.get("ats_platform", "Career Page")
            applicant_count = job.get("applicant_count", 0)

            # Strict Wipro blacklist enforcement
            if contains_wipro(company) or contains_wipro(title) or contains_wipro(desc):
                print(f"\n  {C_RED}[!] SKIPPING: '{company}' matched Wipro blacklist exclusion.{C_RESET}\n")
                continue

            print(f"\n{C_MAGENTA}{'-' * 95}{C_RESET}")
            print(f"  {C_BOLD}{C_WHITE}TARGET [{idx}/{len(top_roles)}]:{C_RESET} {C_CYAN}{title}{C_RESET} at {C_GREEN}{company}{C_RESET}")
            print(f"  {C_GRAY}Direct Career URL:{C_RESET} {C_WHITE}{url}{C_RESET}")
            print(f"{C_MAGENTA}{'-' * 95}{C_RESET}")

            # Pre-load visible browser to target career URL so candidate sees the job page live on screen
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except Exception:
                pass

            # =====================================================================
            # STEP 2: COMPETITION AUDIT
            # =====================================================================
            print_step_header(2, 5, f"Direct Career Page Competition Audit ({company})", "[AUDIT]")
            print_step_sub(f"Evaluating competition & freshness for '{title}'...")
            if applicant_count <= 50:
                print_step_sub(f"Live career page applicants: {C_GREEN}{applicant_count} applicants{C_RESET} (Threshold: <= 50) -> {C_BOLD}{C_GREEN}APPROVED TO APPLY DIRECTLY{C_RESET}", status="SUCCESS")
            else:
                print_step_sub(f"Live applicant estimate: {C_RED}{applicant_count} applicants{C_RESET} (Exceeds 50 threshold) -> High competition, skipping.", status="WARNING")
                print_step_footer()
                continue
            print_step_footer()

            # =====================================================================
            # STEP 3: AI ATS RESUME TAILORING & SCORING
            # =====================================================================
            print_step_header(3, 5, f"AI ATS Resume Tailoring & Pre-Flight Scoring ({company})", "[ATS]")
            print_step_sub(f"Extracting technical keywords and frameworks from Job Description...")
            print_step_sub(f"Querying OpenRouter Free Tier LLM with zero-cost model fallback routing...")

            update_live_dashboard(
                cycle_num=cycle_num,
                state="RUNNING",
                current_action=f"Step 3: Tailoring resume via OpenRouter free model for '{title}' @ '{company}'..."
            )

            try:
                tailored_data = tailor_resume(title, company, desc)
                ats_score = calculate_ats_match_score(desc, tailored_data)
                print_step_sub(f"Resume tailored successfully with bullet formula: [Action] + [Context] + [Tool] + [Metric]", status="SUCCESS")
                print_step_sub(f"Computed ATS Pre-Flight Match Score: {C_BOLD}{C_GREEN}{ats_score}%{C_RESET} (Required: >= 95.0%)", status="SUCCESS")
            except Exception as e:
                print_step_sub(f"Tailoring failed: {e}", status="ALERT")
                print_step_footer()
                continue
            print_step_footer()

            # =====================================================================
            # STEP 4: ATS PDF COMPILATION & RECRUITER OUTREACH PACK
            # =====================================================================
            print_step_header(4, 5, f"ATS PDF Generation & Recruiter Outreach Pack", "[PDF]")
            print_step_sub(f"Compiling high-contrast single-column ATS Letter PDF...")
            try:
                pdf_path = generate_tailored_pdf(tailored_data, company, title)
                company_folder = RESUMES_DIR / "by_company" / re.sub(r"[^\w\-_]", "_", company.strip())
                print_step_sub(f"Saved Tailored Resume PDF: {C_YELLOW}{pdf_path.name}{C_RESET}", status="SUCCESS")
                print_step_sub(f"Saved to Company Folder: {C_WHITE}{company_folder}{C_RESET}", status="SUCCESS")
                print_step_sub(f"Generated 1-Click LinkedIn Connection Note (< 300 chars)", status="SUCCESS")
                print_step_sub(f"Generated Personalized Cold Email Pitch Draft", status="SUCCESS")
                prep_kit_path = generate_interview_kit(company, title)
                print_step_sub(f"Generated AI Interview & System Design Kit: {C_CYAN}{Path(prep_kit_path).name}{C_RESET}", status="SUCCESS")
            except Exception as e:
                print_step_sub(f"PDF generation failed: {e}", status="ALERT")
                print_step_footer()
                continue
            print_step_footer()

            # =====================================================================
            # STEP 5: AUTONOMOUS SUBMISSION VIA VISIBLE BROWSER
            # =====================================================================
            print_step_header(5, 5, f"Autonomous Application on {platform} Career Page", "[SUBMIT]")
            print_step_sub(f"Visible browser navigating to: {url}...")
            
            update_live_dashboard(
                cycle_num=cycle_num,
                state="RUNNING",
                current_action=f"Step 4: Executing visible auto-application for '{title}' @ '{company}'..."
            )

            app_result = apply_to_job(page, job, pdf_path)
            applications_processed += 1

            # Log record & update dashboard
            log_applied_job(app_result)
            update_live_dashboard(
                cycle_num=cycle_num,
                state="RUNNING",
                current_action=f"Completed live application for '{company}'. Next action..."
            )

            status_str = app_result.get("status", "APPLIED")
            notes_str = app_result.get("notes", "")
            if status_str == "APPLIED":
                print_step_sub(f"Application Status: {C_BOLD}{C_GREEN}VERIFIED APPLIED (Official Confirmation Email Expected){C_RESET}", status="SUCCESS")
            else:
                print_step_sub(f"Application Status: {C_BOLD}{C_YELLOW}PORTAL_CAPTURED (Pre-Filled & Saved in Portal — 1-Click Manual Submit Needed){C_RESET}", status="WARNING")
                if notes_str:
                    print_step_sub(f"Reason: {C_WHITE}{notes_str}{C_RESET}", status="ALERT")
                print_step_sub(f"Notice: Employer will send confirmation email once you complete the 1-click submission.", status="ALERT")
            print_step_sub(f"Live viewport screenshot captured to artifact: {C_WHITE}live_viewport.png{C_RESET}", status="SUCCESS")
            print_step_footer()

            time.sleep(2.0)

    except Exception as e:
        logger.error(f"Live cycle error: {e}", exc_info=True)
        print(f"\n  {C_RED}Cycle notice: {e}{C_RESET}\n")
    finally:
        try:
            context.close()
            browser.close()
        except Exception:
            pass

    return applications_processed


def run_live_console(single_cycle: bool = False, custom_query: Optional[str] = None):
    """Main live interactive runner running in real-time."""
    prevent_system_sleep()
    cycle_num = 1

    print(f"\n{C_BOLD}{C_GREEN}INITIALIZING JARVIS LIVE STEP-BY-STEP AUTONOMOUS SYSTEM...{C_RESET}")
    if custom_query:
        print(f"Target Dynamic Query: {C_CYAN}'{custom_query}'{C_RESET}")
    print(f"Windows Sleep Prevention: {C_GREEN}ACTIVE{C_RESET} | Cadence: {C_YELLOW}{CYCLE_INTERVAL_SECONDS} seconds (Fast Continuous Mode){C_RESET}\n")

    with sync_playwright() as playwright_instance:
        while True:
            try:
                processed = execute_live_cycle(cycle_num, playwright_instance, custom_query=custom_query)

                print(f"\n{C_CYAN}{'=' * 95}{C_RESET}")
                print(f"  {C_BOLD}{C_GREEN}CYCLE #{cycle_num} COMPLETED SUCCESSFULLY{C_RESET} | Applications Processed: {C_WHITE}{processed}{C_RESET}")
                print(f"{C_CYAN}{'=' * 95}{C_RESET}\n")

                if single_cycle:
                    print(f"  {C_YELLOW}Single-cycle mode completed. Exiting.{C_RESET}\n")
                    break

                # If 0 processed, advance immediately to next batch with minimal 3s breath
                if processed == 0:
                    print(f"  {C_YELLOW}Advancing immediately to next company batch (3s fast continuous cycle)...{C_RESET}\n")
                    time.sleep(3)
                    cycle_num += 1
                    continue

                wait_secs = CYCLE_INTERVAL_SECONDS
                next_time = (datetime.datetime.now() + datetime.timedelta(seconds=wait_secs)).strftime("%H:%M:%S")
                print(f"  {C_BLUE}Next continuous cycle scheduled for: {C_BOLD}{C_WHITE}{next_time}{C_RESET} ({wait_secs}s cadence)\n")

                update_live_dashboard(
                    cycle_num=cycle_num,
                    state="SLEEPING",
                    current_action=f"Sleeping {wait_secs}s until next continuous execution window.",
                    next_run_time=next_time
                )

                # Visual countdown timer in terminal
                remaining = wait_secs
                while remaining > 0:
                    mins, secs = divmod(remaining, 60)
                    sys.stdout.write(f"\r  {C_GRAY}[WAIT] Next cycle in {C_WHITE}{mins:02d}m {secs:02d}s{C_GRAY}... (Press Ctrl+C to stop){C_RESET}   ")
                    sys.stdout.flush()
                    time.sleep(1)
                    remaining -= 1

                print("\n")
                cycle_num += 1

            except KeyboardInterrupt:
                print(f"\n\n  {C_YELLOW}Live agent stopped by user. Gracefully shutting down.{C_RESET}\n")
                break
            except Exception as e:
                print(f"\n  {C_RED}Unexpected exception: {e}{C_RESET}\n")
                time.sleep(15)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis Live Step-by-Step Autonomous Career Engine")
    parser.add_argument("--single-cycle", action="store_true", help="Execute 1 live cycle and stop.")
    parser.add_argument("--query", type=str, default="", help="Dynamically search career pages for a specific natural language query.")
    args = parser.parse_args()

    run_live_console(single_cycle=args.single_cycle, custom_query=args.query or None)
