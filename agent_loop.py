import argparse
import datetime
import logging
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

from config import (
    HEADLESS,
    CYCLE_INTERVAL_SECONDS,
    MAX_JOBS_PER_CYCLE,
    LOGS_DIR,
    contains_wipro
)
from scraper import find_top_target_roles
from tailor import tailor_resume
from pdf_generator import generate_tailored_pdf
from applicant import apply_to_job, capture_viewport
from dashboard import log_applied_job, update_live_dashboard

# Configure Logging
log_file = LOGS_DIR / f"agent_{datetime.datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(str(log_file), encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("JarvisJobAgent.CoreLoop")


def execute_cycle(cycle_num: int, playwright_instance) -> int:
    """Executes a complete 5-step job search, resume tailoring, and application cycle."""
    logger.info(f"============================================================")
    logger.info(f"STARTING 15-MINUTE CYCLE #{cycle_num}")
    logger.info(f"============================================================")

    update_live_dashboard(
        cycle_num=cycle_num,
        state="RUNNING",
        current_action="Step 1: Sourcing target roles via Playwright browser session..."
    )

    # Launch Chromium browser session (non-headless per prompt instructions)
    logger.info(f"Launching Playwright Chromium (headless={HEADLESS})...")
    browser = playwright_instance.chromium.launch(
        headless=HEADLESS,
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

    # Mask automation signature
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """)

    page = context.new_page()
    applications_processed = 0

    try:
        # Step 1 & 2: Sourcing and DOM context extraction
        capture_viewport(page, f"cycle_{cycle_num}_start")
        top_roles = find_top_target_roles(page, limit=MAX_JOBS_PER_CYCLE)

        if not top_roles:
            logger.warning("No new matching roles identified in this cycle.")
            update_live_dashboard(
                cycle_num=cycle_num,
                state="RUNNING",
                current_action="No new jobs found this cycle; waiting for next window."
            )
            return 0

        for idx, job in enumerate(top_roles, start=1):
            company = job.get("company", "Company")
            title = job.get("title", "Job Role")
            desc = job.get("description", "")
            url = job.get("url", "")

            # Safeguard Wipro blacklist
            if contains_wipro(company) or contains_wipro(title) or contains_wipro(desc):
                logger.warning(f"SKIPPING: '{company}' matched Wipro blacklist.")
                continue

            logger.info(f"------------------------------------------------------------")
            logger.info(f"Processing Target [{idx}/{len(top_roles)}]: {title} @ {company}")
            logger.info(f"------------------------------------------------------------")

            update_live_dashboard(
                cycle_num=cycle_num,
                state="RUNNING",
                current_action=f"Step 3: Tailoring resume via OpenRouter free model for '{title}' @ '{company}'..."
            )

            # Step 3: Resume Tailoring & ATS PDF Compilation
            try:
                tailored_data = tailor_resume(title, company, desc)
                pdf_path = generate_tailored_pdf(tailored_data, company, title, browser=browser)
                logger.info(f"Tailored resume ready at: {pdf_path.name}")
            except Exception as e:
                logger.error(f"Failed to tailor resume: {e}", exc_info=True)
                continue

            # Step 4: Auto-Application via visible browser
            update_live_dashboard(
                cycle_num=cycle_num,
                state="RUNNING",
                current_action=f"Step 4: Executing auto-application for '{title}' @ '{company}'..."
            )

            app_result = apply_to_job(page, job, pdf_path)
            applications_processed += 1

            # Step 5: Artifact Generation & Logging
            log_applied_job(app_result)
            update_live_dashboard(
                cycle_num=cycle_num,
                state="RUNNING",
                current_action=f"Completed application for '{company}'. Preparing next opportunity..."
            )

            time.sleep(2.0)

    except Exception as e:
        logger.error(f"Cycle #{cycle_num} encountered an exception: {e}", exc_info=True)
        update_live_dashboard(
            cycle_num=cycle_num,
            state="RUNNING",
            current_action=f"Encountered notice: {str(e)[:100]}",
            last_error=str(e)
        )
    finally:
        try:
            context.close()
            browser.close()
        except Exception:
            pass

    return applications_processed


def run_daemon(single_cycle: bool = False):
    """Main persistent daemon loop executing every 15 minutes indefinitely."""
    cycle_num = 1
    logger.info("==================================================================")
    logger.info("JARVIS PERSISTENT AUTONOMOUS JOB AGENT INITIALIZED")
    logger.info(f"Interval: {CYCLE_INTERVAL_SECONDS} seconds ({CYCLE_INTERVAL_SECONDS // 60} minutes)")
    logger.info(f"Non-headless viewport: {not HEADLESS}")
    logger.info("==================================================================")

    with sync_playwright() as playwright_instance:
        while True:
            try:
                processed = execute_cycle(cycle_num, playwright_instance)
                logger.info(f"Cycle #{cycle_num} finished. Applications processed: {processed}")

                if single_cycle:
                    logger.info("Single-cycle mode completed. Exiting.")
                    break

                # Sleep interval calculation
                next_time = (datetime.datetime.now() + datetime.timedelta(seconds=CYCLE_INTERVAL_SECONDS)).strftime("%H:%M:%S")
                logger.info(f"Cycle #{cycle_num} complete. Entering sleep state for {CYCLE_INTERVAL_SECONDS // 60} minutes.")
                logger.info(f"Next cycle scheduled for: {next_time}")

                update_live_dashboard(
                    cycle_num=cycle_num,
                    state="SLEEPING",
                    current_action="Sleeping until next scheduled 15-minute execution window.",
                    next_run_time=next_time
                )

                # Sleep in increments of 10s
                slept = 0
                while slept < CYCLE_INTERVAL_SECONDS:
                    time.sleep(10)
                    slept += 10

                cycle_num += 1

            except KeyboardInterrupt:
                logger.info("Daemon received interrupt signal. Gracefully exiting.")
                break
            except Exception as e:
                logger.error(f"Daemon loop encountered unexpected error: {e}", exc_info=True)
                time.sleep(30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis Autonomous Job Agent")
    parser.add_argument("--single-cycle", action="store_true", help="Run only one 15-minute cycle and exit.")
    args = parser.parse_args()

    run_daemon(single_cycle=args.single_cycle)
