import ctypes
import datetime
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Configure Supervisor Logger
log_file = LOGS_DIR / f"supervisor_{datetime.datetime.now().strftime('%Y%m')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SUPERVISOR] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(str(log_file), encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("JarvisSupervisor")


def prevent_system_sleep():
    """
    Prevents Windows from entering sleep or standby mode while the agent is running.
    Uses Win32 SetThreadExecutionState with ES_CONTINUOUS | ES_SYSTEM_REQUIRED.
    """
    try:
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ES_AWAYMODE_REQUIRED = 0x00000040

        res = ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
        )
        if res:
            logger.info("Windows 24/7 Sleep Prevention active: System sleep disabled during agent operation.")
        else:
            logger.warning("Could not set Windows execution state.")
    except Exception as e:
        logger.debug(f"Sleep prevention notice: {e}")


def run_agent_forever():
    """Supervises and auto-heals the autonomous agent process 24/7."""
    prevent_system_sleep()

    restart_count = 0
    max_fast_restarts = 5
    last_restart_time = time.time()

    logger.info("==================================================================")
    logger.info("JARVIS 24/7 AUTONOMOUS PROCESS GUARDIAN STARTED")
    logger.info(f"Target Script: {BASE_DIR / 'agent_loop.py'}")
    logger.info("Self-healing watchdog active: auto-restarts on any unexpected exit.")
    logger.info("==================================================================")

    while True:
        try:
            start_time = time.time()
            logger.info(f"Starting agent process (Run #{restart_count + 1})...")

            # Launch agent_loop.py
            process = subprocess.Popen(
                [sys.executable, str(BASE_DIR / "agent_loop.py")],
                cwd=str(BASE_DIR)
            )

            # Wait for process to exit
            retcode = process.wait()
            duration = time.time() - start_time

            logger.warning(f"Agent process exited with code {retcode} after {int(duration)}s.")

            # Calculate restart throttling if crashing too rapidly
            if duration < 10:
                restart_count += 1
                if restart_count >= max_fast_restarts:
                    logger.warning("Agent exited rapidly multiple times. Pausing 30s before retry...")
                    time.sleep(30)
                    restart_count = 0
                else:
                    time.sleep(5)
            else:
                restart_count = 0
                time.sleep(3)

            logger.info("Watchdog triggering immediate restart...")

        except KeyboardInterrupt:
            logger.info("Supervisor received interrupt signal (Ctrl+C). Terminating agent gracefully.")
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                pass
            break
        except Exception as e:
            logger.error(f"Supervisor encountered error: {e}", exc_info=True)
            time.sleep(5)


if __name__ == "__main__":
    run_agent_forever()
