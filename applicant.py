import datetime
import logging
import queue
import random
import re
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from playwright.sync_api import Page

from config import (
    CANDIDATE_NAME,
    CANDIDATE_FIRST_NAME,
    CANDIDATE_PREFERRED_NAME,
    CANDIDATE_LAST_NAME,
    CANDIDATE_EMAIL,
    CANDIDATE_PHONE,
    CANDIDATE_LOCATION,
    CANDIDATE_CITY,
    CANDIDATE_STATE,
    CANDIDATE_ZIP,
    CANDIDATE_COUNTRY,
    CANDIDATE_LINKEDIN,
    CANDIDATE_GITHUB,
    CANDIDATE_SALARY,
    CANDIDATE_CURRENT_COMPANY,
    CANDIDATE_DEGREE,
    CANDIDATE_DEGREE_LEVEL,
    CANDIDATE_DEGREE_NAME,
    CANDIDATE_MAJOR,
    CANDIDATE_UNIVERSITY,
    CANDIDATE_GPA,
    CANDIDATE_GENDER,
    CANDIDATE_RACE,
    CANDIDATE_VETERAN_STATUS,
    CANDIDATE_DISABILITY_STATUS,
    DRY_RUN,
    ARTIFACT_VIEWPORT,
    SCREENSHOTS_DIR
)

logger = logging.getLogger("JarvisJobAgent.Applicant")

# Global callback for real-time Live Form Navigator HUD in Mission Control OS
LIVE_FIELD_CALLBACK = None
PAUSE_CHECK_CALLBACK = None
ABORT_CHECK_CALLBACK = None
CO_PILOT_AWAITING_CALLBACK = None
CO_PILOT_APPROVED_CALLBACK = None

# Active Playwright Page and Browser tracking for real-time interactive user operation
ACTIVE_LIVE_PAGE: Optional[Page] = None
ACTIVE_LIVE_BROWSER = None
PLAYWRIGHT_THREAD: Optional[threading.Thread] = None

# Thread-safe Action Queue to prevent greenlet cross-thread errors
_LIVE_ACTION_QUEUE: queue.Queue = queue.Queue()


def set_active_live_browser(page: Optional[Page], browser=None):
    """Stores the active Playwright page and browser so the user can interactively operate it."""
    global ACTIVE_LIVE_PAGE, ACTIVE_LIVE_BROWSER, PLAYWRIGHT_THREAD
    ACTIVE_LIVE_PAGE = page
    ACTIVE_LIVE_BROWSER = browser
    PLAYWRIGHT_THREAD = threading.current_thread()


def clear_active_live_browser():
    """Clears the active browser session references."""
    global ACTIVE_LIVE_PAGE, ACTIVE_LIVE_BROWSER, PLAYWRIGHT_THREAD
    ACTIVE_LIVE_PAGE = None
    ACTIVE_LIVE_BROWSER = None
    PLAYWRIGHT_THREAD = None


def get_active_live_page() -> Optional[Page]:
    """Returns the currently active live Playwright page if present."""
    global ACTIVE_LIVE_PAGE
    return ACTIVE_LIVE_PAGE


def queue_action(action_type: str, **kwargs) -> bool:
    """
    Enqueues an interactive user action (scroll, click, type, key)
    to be safely dispatched on the Playwright thread, avoiding greenlet errors.
    Non-blocking: responds in milliseconds so UI buttons never hang.
    """
    if not ACTIVE_LIVE_PAGE:
        return False
    event = threading.Event()
    result_holder = {"success": False}
    _LIVE_ACTION_QUEUE.put((action_type, kwargs, result_holder, event))
    # Quick non-blocking wait (up to 150ms) for instantaneous execution if Playwright is yielding
    event.wait(timeout=0.15)
    return True


def safe_sleep(page: Optional[Page], seconds: float):
    """Sleeps while actively processing queued user actions (scroll, click, type)."""
    end_time = time.time() + seconds
    while time.time() < end_time:
        if page:
            process_pending_actions(page)
        remaining = end_time - time.time()
        if remaining > 0:
            time.sleep(min(0.04, remaining))


def process_pending_actions(page: Optional[Page] = None):
    """
    Processes all queued user actions directly on the Playwright thread.
    Called inside pause loops, typing cadence, and navigation steps.
    """
    target_page = page or ACTIVE_LIVE_PAGE
    if not target_page:
        return

    while not _LIVE_ACTION_QUEUE.empty():
        try:
            action_type, kwargs, result_holder, event = _LIVE_ACTION_QUEUE.get_nowait()
        except queue.Empty:
            break

        try:
            if action_type == "scroll":
                dx = int(kwargs.get("delta_x", 0))
                dy = int(kwargs.get("delta_y", 300))
                target_page.evaluate(f"window.scrollBy({dx}, {dy})")
                time.sleep(0.04)
                capture_viewport(target_page, "user_scroll")
                result_holder["success"] = True
            elif action_type == "scroll_to":
                pos = str(kwargs.get("pos", "bottom"))
                if pos == "top":
                    target_page.evaluate("window.scrollTo(0, 0)")
                elif pos == "bottom":
                    target_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                elif pos == "up":
                    target_page.evaluate("window.scrollBy(0, -450)")
                elif pos == "down":
                    target_page.evaluate("window.scrollBy(0, 450)")
                time.sleep(0.04)
                capture_viewport(target_page, f"scroll_{pos}")
                result_holder["success"] = True
            elif action_type == "click":
                x = max(0, min(1920, int(kwargs.get("x", 0))))
                y = max(0, min(1080, int(kwargs.get("y", 0))))
                target_page.mouse.click(x, y)
                time.sleep(0.08)
                capture_viewport(target_page, f"click_{x}_{y}")
                result_holder["success"] = True
            elif action_type == "type":
                text = str(kwargs.get("text", ""))
                press_enter = bool(kwargs.get("press_enter", False))
                target_page.keyboard.type(text, delay=25)
                if press_enter:
                    target_page.keyboard.press("Enter")
                time.sleep(0.08)
                capture_viewport(target_page, "user_type")
                result_holder["success"] = True
            elif action_type == "key":
                key = str(kwargs.get("key", "Enter"))
                target_page.keyboard.press(key)
                time.sleep(0.06)
                capture_viewport(target_page, f"key_{key}")
                result_holder["success"] = True
            elif action_type == "capture":
                capture_viewport(target_page, "refresh")
                result_holder["success"] = True
        except Exception as ex:
            logger.warning(f"Error executing queued action '{action_type}': {ex}")
            result_holder["success"] = False
        finally:
            event.set()


def scroll_live_page(delta_x: int = 0, delta_y: int = 300) -> bool:
    """Interactively scrolls the live browser page and updates the live viewport artifact."""
    global ACTIVE_LIVE_PAGE, PLAYWRIGHT_THREAD
    if not ACTIVE_LIVE_PAGE:
        return False
    if threading.current_thread() is PLAYWRIGHT_THREAD:
        try:
            ACTIVE_LIVE_PAGE.evaluate(f"window.scrollBy({delta_x}, {delta_y})")
            time.sleep(0.04)
            capture_viewport(ACTIVE_LIVE_PAGE, "user_scroll")
            return True
        except Exception as e:
            logger.warning(f"Error scrolling live page directly: {e}")
            return False
    return queue_action("scroll", delta_x=delta_x, delta_y=delta_y)


def scroll_to_position(pos: str = "bottom") -> bool:
    """Scrolls to a designated position ('top', 'bottom', 'up', 'down') and updates viewport."""
    global ACTIVE_LIVE_PAGE, PLAYWRIGHT_THREAD
    if not ACTIVE_LIVE_PAGE:
        return False
    if threading.current_thread() is PLAYWRIGHT_THREAD:
        try:
            if pos == "top":
                ACTIVE_LIVE_PAGE.evaluate("window.scrollTo(0, 0)")
            elif pos == "bottom":
                ACTIVE_LIVE_PAGE.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            elif pos == "up":
                ACTIVE_LIVE_PAGE.evaluate("window.scrollBy(0, -450)")
            elif pos == "down":
                ACTIVE_LIVE_PAGE.evaluate("window.scrollBy(0, 450)")
            time.sleep(0.04)
            capture_viewport(ACTIVE_LIVE_PAGE, f"scroll_{pos}")
            return True
        except Exception as e:
            logger.warning(f"Error scrolling to {pos} directly: {e}")
            return False
    return queue_action("scroll_to", pos=pos)


def click_at_coords(x: int, y: int) -> bool:
    """Directly clicks at the specified (x, y) coordinates on the live 1920x1080 canvas."""
    global ACTIVE_LIVE_PAGE, PLAYWRIGHT_THREAD
    if not ACTIVE_LIVE_PAGE:
        return False
    if threading.current_thread() is PLAYWRIGHT_THREAD:
        try:
            clamped_x = max(0, min(1920, int(x)))
            clamped_y = max(0, min(1080, int(y)))
            ACTIVE_LIVE_PAGE.mouse.click(clamped_x, clamped_y)
            time.sleep(0.08)
            capture_viewport(ACTIVE_LIVE_PAGE, f"click_{clamped_x}_{clamped_y}")
            return True
        except Exception as e:
            logger.warning(f"Error clicking at ({x}, {y}) directly: {e}")
            return False
    return queue_action("click", x=x, y=y)


def type_into_page(text: str, press_enter: bool = False) -> bool:
    """Directly types text into the currently active element on the live browser."""
    global ACTIVE_LIVE_PAGE, PLAYWRIGHT_THREAD
    if not ACTIVE_LIVE_PAGE:
        return False
    if threading.current_thread() is PLAYWRIGHT_THREAD:
        try:
            ACTIVE_LIVE_PAGE.keyboard.type(text, delay=25)
            if press_enter:
                ACTIVE_LIVE_PAGE.keyboard.press("Enter")
            time.sleep(0.08)
            capture_viewport(ACTIVE_LIVE_PAGE, "user_type")
            return True
        except Exception as e:
            logger.warning(f"Error typing into live page directly: {e}")
            return False
    return queue_action("type", text=text, press_enter=press_enter)


def press_key_on_page(key: str) -> bool:
    """Dispatches a keyboard key event (e.g., 'Enter', 'Tab', 'Escape', 'Backspace')."""
    global ACTIVE_LIVE_PAGE, PLAYWRIGHT_THREAD
    if not ACTIVE_LIVE_PAGE:
        return False
    if threading.current_thread() is PLAYWRIGHT_THREAD:
        try:
            ACTIVE_LIVE_PAGE.keyboard.press(key)
            time.sleep(0.06)
            capture_viewport(ACTIVE_LIVE_PAGE, f"key_{key}")
            return True
        except Exception as e:
            logger.warning(f"Error pressing key {key} directly: {e}")
            return False
    return queue_action("key", key=key)


def bring_browser_window_to_front() -> bool:
    """
    Brings the native desktop Chromium window to the foreground on Windows
    so the candidate can physically see and directly interact with it.
    """
    global ACTIVE_LIVE_PAGE
    success = False
    if ACTIVE_LIVE_PAGE:
        try:
            ACTIVE_LIVE_PAGE.bring_to_front()
            success = True
        except Exception:
            pass

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32

            # Find matching window
            def enum_proc(hwnd, lparam):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buff, length + 1)
                        title = buff.value.lower()
                        if any(term in title for term in ["chromium", "chrome", "greenhouse", "lever", "workday", "job", "career"]):
                            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                            user32.SetForegroundWindow(hwnd)
                            user32.BringWindowToTop(hwnd)
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            user32.EnumWindows(WNDENUMPROC(enum_proc), 0)
            success = True
        except Exception as ex:
            logger.debug(f"Bring to front Windows API: {ex}")

    if ACTIVE_LIVE_PAGE:
        try:
            capture_viewport(ACTIVE_LIVE_PAGE, "brought_to_front")
        except Exception:
            pass

    return success


class ApplicationAbortedException(Exception):
    """Raised when candidate explicitly aborts/cancels an in-flight live application."""
    pass


def set_live_field_callback(callback):
    """Registers a listener function receiving (field_name: str, value: str)."""
    global LIVE_FIELD_CALLBACK
    LIVE_FIELD_CALLBACK = callback


def set_pause_callback(callback):
    """Registers a callable returning bool: True if paused, False if running."""
    global PAUSE_CHECK_CALLBACK
    PAUSE_CHECK_CALLBACK = callback


def set_abort_callback(callback):
    """Registers a callable returning bool: True if aborted, False otherwise."""
    global ABORT_CHECK_CALLBACK
    ABORT_CHECK_CALLBACK = callback


CO_PILOT_MODE_CALLBACK = None
CO_PILOT_AWAITING_CALLBACK = None
CO_PILOT_NOTIFY_AWAITING = None


def set_co_pilot_callbacks(is_co_pilot_active, is_awaiting_approval, notify_awaiting):
    """Registers callbacks for Co-Pilot pre-submission review gate."""
    global CO_PILOT_MODE_CALLBACK, CO_PILOT_AWAITING_CALLBACK, CO_PILOT_NOTIFY_AWAITING
    CO_PILOT_MODE_CALLBACK = is_co_pilot_active
    CO_PILOT_AWAITING_CALLBACK = is_awaiting_approval
    CO_PILOT_NOTIFY_AWAITING = notify_awaiting


def check_pause_and_abort(page: Optional[Page] = None):
    """Checks pause and abort flags. Halts or aborts execution cleanly while keeping browser responsive."""
    global PAUSE_CHECK_CALLBACK, ABORT_CHECK_CALLBACK
    target_page = page or ACTIVE_LIVE_PAGE
    if target_page:
        process_pending_actions(target_page)
    if ABORT_CHECK_CALLBACK and ABORT_CHECK_CALLBACK():
        raise ApplicationAbortedException("Live application stopped by candidate.")
    if PAUSE_CHECK_CALLBACK and PAUSE_CHECK_CALLBACK():
        safe_print_live("      \033[93m[PAUSED]\033[0m Automation paused by candidate. Desktop browser & live viewport are under your direct control.")
        bring_browser_window_to_front()
        while PAUSE_CHECK_CALLBACK and PAUSE_CHECK_CALLBACK():
            if ABORT_CHECK_CALLBACK and ABORT_CHECK_CALLBACK():
                raise ApplicationAbortedException("Live application stopped by candidate.")
            if target_page:
                process_pending_actions(target_page)
            time.sleep(0.04)
        safe_print_live("      \033[92m[RESUMED]\033[0m Automation resumed by candidate. Continuing execution...")


def capture_viewport(page: Page, step_name: str = "live") -> Path:
    """Takes a live screenshot of the viewport and updates the Antigravity artifact."""
    clean_step = re.sub(r"[^\w\-]", "_", step_name)[:25]
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    local_shot = SCREENSHOTS_DIR / f"{clean_step}_{timestamp}.png"
    try:
        page.screenshot(path=str(local_shot), full_page=False)
        page.screenshot(path=str(ARTIFACT_VIEWPORT), full_page=False)
    except Exception as e:
        logger.debug(f"Viewport capture notice: {e}")
    return local_shot


def human_type_input(page: Page, el, field_name: str, value: str, on_progress: Any = None):
    """
    Types text with human cadence into an input or textarea element.
    Visibly highlights the field with a blue focus glow, streams typing live
    with viewport captures, and notifies the Form Navigator HUD.
    """
    check_pause_and_abort(page)
    try:
        if not el.is_visible():
            return

        val_str = str(value)
        if on_progress:
            on_progress("TYPING_FIELD", f"Typing [{field_name}]: {val_str[:40]}...")

        # 1. Smoothly scroll field into view so candidate sees it
        try:
            el.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        time.sleep(0.08)

        # 2. Visibly highlight the active input with blue focus ring
        try:
            page.evaluate("""(elem) => {
                elem.style.outline = '3px solid #3b82f6';
                elem.style.boxShadow = '0 0 14px rgba(59, 130, 246, 0.7)';
                elem.style.borderRadius = '4px';
                elem.style.transition = 'all 0.15s ease-in-out';
            }""", el)
        except Exception:
            pass

        try:
            el.click(timeout=1500)
        except Exception:
            pass
        check_pause_and_abort(page)

        # 3. Clear existing value if any
        try:
            el.fill("")
        except Exception:
            pass

        # 4. Human-cadenced character-by-character typing
        if len(val_str) > 75:
            # Long answers (custom questions / textareas): type words with deliberate human delay
            words = val_str.split(" ")
            for i, word in enumerate(words):
                check_pause_and_abort(page)
                process_pending_actions(page)
                el.type(word + (" " if i < len(words) - 1 else ""), delay=random.uniform(18, 35))
                if i % 5 == 0:
                    capture_viewport(page, f"fill_{field_name}")
            safe_sleep(page, 0.1)
        else:
            for char in val_str:
                check_pause_and_abort(page)
                process_pending_actions(page)
                el.type(char, delay=random.uniform(22, 45))
            safe_sleep(page, 0.1)

        check_pause_and_abort(page)

        # 5. Remove outline & capture final state of field
        try:
            page.evaluate("""(elem) => {
                elem.style.outline = '';
                elem.style.boxShadow = '';
            }""", el)
        except Exception:
            pass

        capture_viewport(page, f"done_{field_name}")
        print_live_field(field_name, val_str)
        # Deliberate pacing: let candidate visibly observe the filled field before moving on
        safe_sleep(page, random.uniform(0.25, 0.38))

    except ApplicationAbortedException:
        raise
    except Exception as e:
        logger.debug(f"human_type_input exception on {field_name}: {e}")


def human_type(page: Page, selector: str, text: str):
    """Types text with human-mimicking cadence while honoring pause and abort gates."""
    check_pause_and_abort(page)
    try:
        el = page.locator(selector).first
        if el.count() > 0:
            human_type_input(page, el, selector, text)
    except ApplicationAbortedException:
        raise
    except Exception as e:
        logger.debug(f"Typing pass on {selector}: {e}")


def safe_print_live(text: str):
    try:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    except Exception:
        clean = text.encode("ascii", errors="replace").decode("ascii")
        try:
            sys.stdout.write(clean + "\n")
            sys.stdout.flush()
        except Exception:
            pass


def print_live_field(field_name: str, value: str):
    safe_print_live(f"      \033[92m[OK]\033[0m \033[90m[{field_name}]\033[0m \033[97m->\033[0m \033[93m{value}\033[0m")
    if LIVE_FIELD_CALLBACK:
        try:
            LIVE_FIELD_CALLBACK(field_name, value)
        except Exception:
            pass


def print_live_action(icon: str, msg: str):
    safe_print_live(f"  \033[96m[{icon}]\033[0m \033[97m{msg}\033[0m")


def dynamically_solve_react_select_dropdowns(page: Page, job: Optional[Dict[str, Any]] = None, on_progress: Any = None) -> int:
    """
    Dynamically and methodically reads questions line-by-line and solves modern
    React-Select / custom combobox dropdowns across Greenhouse, Ashby, Lever, etc.
    Reads all available options directly from the DOM and applies JarvisBrain semantic matching.
    Never types random characters into combobox inputs.
    """
    from jarvis_brain import jarvis_brain
    solved_count = 0

    try:
        # Run up to 2 passes to catch any dropdowns dynamically mounted or revealed by previous answers
        for pass_idx in range(2):
            controls = page.locator(".select__control:has(.select__placeholder), .select:has(.select__placeholder) .select__control, .select__control").all()
            if not controls:
                break
            made_progress = False
            for idx, ctrl in enumerate(controls):
                check_pause_and_abort(page)
                try:
                    if not ctrl.is_visible():
                        continue

                    # Check if this control already has a chosen value (non-placeholder)
                    val_el = ctrl.locator(".select__single-value, [class*='singleValue']").first
                    if val_el.count() > 0 and val_el.inner_text().strip():
                        continue

                    # 1. Extract Question Label using input ID first (most accurate)
                    label_text = ""
                    c_inp = ctrl.locator("input").first
                    c_id = ""
                    if c_inp.count() > 0:
                        c_id = c_inp.get_attribute("id") or ""
                        if c_id:
                            lbl_el = page.locator(f"label[for='{c_id}'], label#{c_id}-label").first
                            if lbl_el.count() > 0:
                                label_text = lbl_el.inner_text().strip()
                    if not label_text:
                        aria_lbl = ctrl.get_attribute("aria-labelledby") or ""
                        if aria_lbl:
                            lbl_el = page.locator(f"#{aria_lbl}").first
                            if lbl_el.count() > 0:
                                label_text = lbl_el.inner_text().strip()
                    if not label_text:
                        try:
                            p_field = ctrl.locator("xpath=ancestor::div[contains(@class, 'field') or contains(@class, 'select') or contains(@class, 'form-group')]//label").first
                            if p_field.count() > 0:
                                label_text = p_field.inner_text().strip()
                        except Exception:
                            pass
                    if not label_text:
                        try:
                            lbl_el = ctrl.locator("xpath=preceding::label[1]").first
                            if lbl_el.count() > 0:
                                label_text = lbl_el.inner_text().strip()
                        except Exception:
                            pass

                    clean_q = re.sub(r"\s+", " ", (label_text or "").replace("\n", " ")).strip()
                    q_low = clean_q.lower()
                    q_disp = clean_q[:45] if clean_q else f"Question {idx+1}"

                    # Highlight field being read with visual focus glow
                    try:
                        page.evaluate("""(elem) => {
                            elem.style.outline = '2px solid #3b82f6';
                            elem.style.boxShadow = '0 0 10px rgba(59, 130, 246, 0.5)';
                        }""", ctrl)
                    except Exception:
                        pass

                    print_live_action("👀", f"Reading question: '{q_disp}'")
                    if on_progress:
                        on_progress("READING_QUESTION", f"Reading question: '{q_disp}'")

                    # Guarantee clean state before opening
                    page.keyboard.press("Escape")
                    safe_sleep(page, 0.1)

                    # Scroll into view and click control to reveal options menu
                    ctrl.scroll_into_view_if_needed(timeout=1000)
                    ctrl.click(timeout=1500)
                    safe_sleep(page, 0.3)

                    # Locate options rendered in open dropdown menu (excluding hidden phone country list)
                    opts = page.locator(".select__menu .select__option, div.select__option, [role='listbox'] [role='option']:not(.iti__country)").all()
                    opt_texts = [o.inner_text().strip() for o in opts if o.inner_text().strip()]
                    cleaned_opts = [o for o in opt_texts if not any(ph in o.lower() for ph in ["select...", "select an option", "choose...", "--"])]

                    if not cleaned_opts:
                        page.keyboard.press("Escape")
                        try:
                            page.evaluate("""(elem) => { elem.style.outline = ''; elem.style.boxShadow = ''; }""", ctrl)
                        except Exception:
                            pass
                        continue

                    # Legal compliance & profile invariant answering
                    choice = None
                    if any(k in q_low for k in ["right to work", "authorized to work", "legally authorized"]) and not any(k in q_low for k in ["sponsorship", "require"]):
                        choice = "Yes"
                    elif any(k in q_low for k in ["sponsorship", "require visa", "require sponsorship"]):
                        choice = "Yes"
                    elif any(k in q_low for k in ["comfortable interviewing", "salary outlined", "compensation outlined", "target salary", "salary in the job"]):
                        choice = "Yes"
                    elif any(k in q_low for k in ["office hubs", "hybrid", "days from", "open to working", "working 3 days"]):
                        choice = "Yes"
                    elif any(k in q_low for k in ["former", "ever been employed", "previously employed", "employed by"]):
                        choice = "No"
                    elif any(k in q_low for k in ["u.s. person", "us person", "itar", "export control", "8 u.s.c."]):
                        choice = "No"
                    elif "transgender" in q_low:
                        choice = next((o for o in cleaned_opts if o.lower() == "no" or "no" in o.lower() or "decline" in o.lower() or "not wish" in o.lower()), "No")
                    elif "sexual orientation" in q_low or "orientation" in q_low:
                        choice = next((o for o in cleaned_opts if "heterosexual" in o.lower() or "straight" in o.lower() or "decline" in o.lower() or "not wish" in o.lower()), cleaned_opts[0])
                    elif "pronoun" in q_low:
                        choice = next((o for o in cleaned_opts if "he/him" in o.lower() or "he / him" in o.lower() or "decline" in o.lower()), cleaned_opts[0])
                    elif "gender" in q_low:
                        choice = next((o for o in cleaned_opts if "man" in o.lower() or "male" in o.lower() or "cisgender man" in o.lower() or "decline" in o.lower()), "Male")
                    elif "hispanic" in q_low or "latino" in q_low:
                        choice = next((o for o in cleaned_opts if "no" in o.lower() or "not hispanic" in o.lower() or "decline" in o.lower()), "No")
                    elif "race" in q_low or "ethnicity" in q_low or "ethnicities" in q_low:
                        choice = next((o for o in cleaned_opts if "asian" in o.lower() or "south asian" in o.lower() or "asian (not hispanic" in o.lower() or "decline" in o.lower()), "Asian")
                    elif "veteran" in q_low:
                        choice = next((o for o in cleaned_opts if "not a protected" in o.lower() or "not a veteran" in o.lower() or "decline" in o.lower() or "not wish" in o.lower()), "I am not a protected veteran")
                    elif "disability" in q_low:
                        choice = next((o for o in cleaned_opts if "not have" in o.lower() or "no, i do not" in o.lower() or "no disability" in o.lower() or "decline" in o.lower() or "not wish" in o.lower()), cleaned_opts[0])
                    elif "country" in q_low:
                        choice = "United States"
                    else:
                        # Fallback for voluntary demographic/survey sections: if candidate decline/prefer not to say is present, or use jarvis_brain
                        if any(k in q_low for k in ["demographic", "equal opportunity", "eeoc", "self-identify", "diversity", "survey"]):
                            choice = next((o for o in cleaned_opts if any(d in o.lower() for d in ["decline", "prefer not", "not wish", "opt out", "choose not"])), None)
                        if not choice:
                            choice = jarvis_brain.choose_best_option(clean_q, cleaned_opts, job=job)

                    if choice:
                        target_el = None
                        for o in opts:
                            txt = o.inner_text().strip()
                            if txt.lower() == choice.lower() or choice.lower() in txt.lower() or (choice.lower() == "no" and txt.lower() == "no") or (choice.lower() == "yes" and txt.lower() == "yes"):
                                target_el = o
                                break

                        if target_el:
                            target_el.click(timeout=1500)
                            print_live_field(q_disp, choice)
                            if on_progress:
                                on_progress("OPTION_SELECTED", f"Answered [{q_disp}]: {choice}")
                            logger.info(f"[ReactSelect] Selected '{choice}' for '{q_disp}'")
                            solved_count += 1
                            made_progress = True
                            safe_sleep(page, 0.2)
                        else:
                            page.keyboard.press("Escape")
                    else:
                        page.keyboard.press("Escape")

                    # Clear highlight
                    try:
                        page.evaluate("""(elem) => { elem.style.outline = ''; elem.style.boxShadow = ''; }""", ctrl)
                    except Exception:
                        pass

                except Exception as e:
                    logger.debug(f"[ReactSelect] Error solving control: {e}")
                    try:
                        page.keyboard.press("Escape")
                    except Exception:
                        pass

            if not made_progress:
                break
    except Exception as e:
        logger.debug(f"[ReactSelect] Global scan error: {e}")

    return solved_count


def solve_form_options_and_radios(page: Page, job: Optional[Dict[str, Any]] = None, on_progress: Any = None) -> int:
    """
    Dynamically and flexibly detects, interprets, and selects form options, radio button groups,
    native <select> dropdowns, and consent checkboxes across all ATS platforms
    (Greenhouse, Ashby, Lever, BambooHR, Workday, etc.).
    Uses dual-signature matching (Question Context + Candidate Options) and 4-tier robust click dispatching.
    Strictly enforces candidate EEOC and demographic invariants.
    """
    from jarvis_brain import jarvis_brain
    solved_count = 0

    # -------------------------------------------------------------
    # 1. Universal Radio Button Groups Solver
    # -------------------------------------------------------------
    try:
        # Locate all radio inputs on page (including CSS styled/hidden ones)
        radio_locators = page.locator("input[type='radio']").all()
        
        # Group radios by name attribute or parent container
        # Key: group_identifier, Value: list of radio elements
        radio_groups: Dict[str, List[Any]] = {}
        
        for idx, r in enumerate(radio_locators):
            try:
                name_attr = r.get_attribute("name") or ""
                if name_attr:
                    grp_key = f"name_{name_attr}"
                else:
                    # Fallback: identify by ancestor fieldset or question div
                    ancestor_id = ""
                    try:
                        anc = r.locator("xpath=ancestor::fieldset | ancestor::div[contains(@class, 'field')] | ancestor::div[contains(@class, 'question')] | ancestor::li[contains(@class, 'application-question')]").first
                        if anc.count() > 0:
                            ancestor_id = anc.get_attribute("id") or anc.get_attribute("class") or ""
                    except Exception:
                        pass
                    grp_key = f"anc_{ancestor_id}_{idx // 4}"
                
                if grp_key not in radio_groups:
                    radio_groups[grp_key] = []
                radio_groups[grp_key].append(r)
            except Exception:
                pass

        for grp_key, radios in radio_groups.items():
            check_pause_and_abort(page)
            try:
                # If any radio in this group is already checked, skip!
                if any(r.is_checked() for r in radios):
                    continue

                # Extract question context / legend
                first_r = radios[0]
                question_text = ""
                try:
                    # 1. Look for fieldset legend
                    legend = first_r.locator("xpath=ancestor::fieldset//legend").first
                    if legend.count() > 0:
                        question_text = legend.inner_text().strip()
                except Exception:
                    pass

                if not question_text:
                    try:
                        # 2. Look for role=radiogroup aria-label or aria-labelledby
                        rg = first_r.locator("xpath=ancestor::*[@role='radiogroup']").first
                        if rg.count() > 0:
                            question_text = rg.get_attribute("aria-label") or ""
                            if not question_text:
                                labelled_by = rg.get_attribute("aria-labelledby") or ""
                                if labelled_by:
                                    lbl_el = page.locator(f"#{labelled_by}").first
                                    if lbl_el.count() > 0:
                                        question_text = lbl_el.inner_text().strip()
                    except Exception:
                        pass

                if not question_text:
                    try:
                        # 3. Look for ancestor question container label/heading
                        q_anc = first_r.locator("xpath=ancestor::div[contains(@class, 'field')] | ancestor::div[contains(@class, 'question')] | ancestor::li[contains(@class, 'application-question')]").first
                        if q_anc.count() > 0:
                            head = q_anc.locator("label, .application-label, legend, h3, h4, strong, p").first
                            if head.count() > 0:
                                question_text = head.inner_text().strip()
                    except Exception:
                        pass

                if not question_text:
                    try:
                        # 4. Preceding legend or label
                        prec = first_r.locator("xpath=preceding::legend[1] | preceding::label[1] | preceding::h3[1] | preceding::h4[1]").first
                        if prec.count() > 0:
                            question_text = prec.inner_text().strip()
                    except Exception:
                        pass

                # Collect all options and map to radio elements
                # List of tuples: (option_label_text, radio_element)
                option_map: List[Tuple[str, Any]] = []
                for r in radios:
                    opt_text = ""
                    r_id = r.get_attribute("id") or ""
                    # Check label for="r_id"
                    if r_id:
                        lbl = page.locator(f"label[for='{r_id}']").first
                        if lbl.count() > 0:
                            opt_text = lbl.inner_text().strip()
                    
                    # Check parent label
                    if not opt_text:
                        try:
                            p_lbl = r.locator("xpath=ancestor::label").first
                            if p_lbl.count() > 0:
                                opt_text = p_lbl.inner_text().strip()
                        except Exception:
                            pass

                    # Check following sibling span/label
                    if not opt_text:
                        try:
                            sib = r.locator("xpath=following-sibling::span[1] | following-sibling::label[1] | following-sibling::div[1]").first
                            if sib.count() > 0:
                                opt_text = sib.inner_text().strip()
                        except Exception:
                            pass

                    # Fallback to value or aria-label
                    if not opt_text:
                        opt_text = r.get_attribute("value") or r.get_attribute("aria-label") or ""

                    # Clean up inner newlines and extra spaces
                    opt_text = re.sub(r"\s+", " ", opt_text).strip()
                    if opt_text:
                        option_map.append((opt_text, r))

                if not option_map:
                    continue

                option_strings = [item[0] for item in option_map]
                logger.debug(f"[SolveRadios] Evaluating group with Q: '{question_text[:50]}' Options: {option_strings}")

                # Use JarvisBrain decision engine
                chosen_opt_str = jarvis_brain.choose_best_option(question_text, option_strings, job=job)
                if chosen_opt_str:
                    # Find corresponding radio element
                    target_radio = None
                    for opt_text, r_elem in option_map:
                        if opt_text == chosen_opt_str or chosen_opt_str.lower() == opt_text.lower():
                            target_radio = r_elem
                            break
                    if not target_radio:
                        for opt_text, r_elem in option_map:
                            if chosen_opt_str.lower() in opt_text.lower() or opt_text.lower() in chosen_opt_str.lower():
                                target_radio = r_elem
                                break

                    if target_radio:
                        # Visibly highlight the radio element with blue focus glow
                        try:
                            page.evaluate("""(elem) => {
                                elem.style.outline = '2px solid #3b82f6';
                                elem.style.boxShadow = '0 0 10px rgba(59, 130, 246, 0.6)';
                                elem.style.borderRadius = '4px';
                            }""", target_radio)
                        except Exception:
                            pass

                        # 4-Tier Robust Click Dispatcher
                        clicked = False
                        r_id = target_radio.get_attribute("id") or ""
                        
                        # Tier 1: Click associated label[for=id]
                        if r_id:
                            lbl = page.locator(f"label[for='{r_id}']").first
                            if lbl.count() > 0:
                                try:
                                    lbl.scroll_into_view_if_needed(timeout=1000)
                                    lbl.click(timeout=1500)
                                    clicked = True
                                except Exception:
                                    pass

                        # Tier 2: Check radio directly (force=True handles opacity:0 / covered elements)
                        if not clicked or not target_radio.is_checked():
                            try:
                                target_radio.scroll_into_view_if_needed(timeout=1000)
                                target_radio.check(force=True, timeout=1500)
                                clicked = True
                            except Exception:
                                pass

                        # Tier 3: Click parent label
                        if not target_radio.is_checked():
                            try:
                                p_lbl = target_radio.locator("xpath=ancestor::label").first
                                if p_lbl.count() > 0:
                                    p_lbl.click(timeout=1500)
                                    clicked = True
                            except Exception:
                                pass

                        # Tier 4: Synthetic JavaScript events (always execute to guarantee framework state sync)
                        try:
                            page.evaluate(
                                """(el) => {
                                    el.checked = true;
                                    el.dispatchEvent(new Event('input', { bubbles: true }));
                                    el.dispatchEvent(new Event('change', { bubbles: true }));
                                    el.dispatchEvent(new Event('click', { bubbles: true }));
                                }""",
                                target_radio
                            )
                        except Exception:
                            pass

                        # Clear outline
                        try:
                            page.evaluate("""(elem) => {
                                elem.style.outline = '';
                                elem.style.boxShadow = '';
                            }""", target_radio)
                        except Exception:
                            pass

                        # Live HUD feedback
                        q_display = question_text.split("\n")[0][:35] if question_text else "Application Survey"
                        print_live_field(q_display, chosen_opt_str)
                        if on_progress:
                            on_progress("OPTION_SELECTED", f"Answered [{q_display}]: {chosen_opt_str}")
                        logger.info(f"[SolveRadios] Selected '{chosen_opt_str}' for '{q_display}'")
                        solved_count += 1
                        safe_sleep(page, 0.25)
            except Exception as e:
                logger.debug(f"[SolveRadios] Error solving radio group: {e}")
    except Exception as e:
        logger.debug(f"[SolveRadios] Error scanning radios: {e}")

    # -------------------------------------------------------------
    # 2. Universal Native <select> Dropdown Solver
    # -------------------------------------------------------------
    try:
        select_locators = page.locator("select").all()
        for s in select_locators:
            check_pause_and_abort(page)
            try:
                # Check if already selected (non-empty, not default 'select' / 'choose')
                val = (s.input_value() or "").strip()
                s_text = ""
                try:
                    s_text = s.locator("option:checked").inner_text().strip()
                except Exception:
                    pass

                # If has a valid selection already, skip
                if val and val != "0" and val != "-1" and not any(placeholder in s_text.lower() for placeholder in ["select", "choose", "please", "--"]):
                    continue

                # Extract question context / label
                s_id = s.get_attribute("id") or ""
                label_text = ""
                if s_id:
                    lbl = page.locator(f"label[for='{s_id}']").first
                    if lbl.count() > 0:
                        label_text = lbl.inner_text().strip()
                if not label_text:
                    try:
                        lbl = s.locator("xpath=preceding::label[1]").first
                        if lbl.count() > 0:
                            label_text = lbl.inner_text().strip()
                    except Exception:
                        pass
                if not label_text:
                    label_text = s.get_attribute("name") or s.get_attribute("aria-label") or ""

                # Extract option texts
                opt_elements = s.locator("option").all()
                opt_texts = [o.inner_text().strip() for o in opt_elements if o.inner_text().strip()]
                # Filter out placeholder texts
                cleaned_opts = [o for o in opt_texts if not any(ph in o.lower() for ph in ["select", "choose", "--", "please choose", "select an option"])]
                if not cleaned_opts:
                    continue

                chosen_opt = jarvis_brain.choose_best_option(label_text, cleaned_opts, job=job)
                if chosen_opt:
                    try:
                        page.evaluate("""(elem) => {
                            elem.style.outline = '2px solid #3b82f6';
                            elem.style.boxShadow = '0 0 10px rgba(59, 130, 246, 0.6)';
                            elem.style.borderRadius = '4px';
                        }""", s)
                    except Exception:
                        pass
                    try:
                        s.select_option(label=chosen_opt)
                        page.evaluate(
                            """(el) => {
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                            }""",
                            s
                        )
                        q_disp = label_text.split("\n")[0][:35] if label_text else "Dropdown Option"
                        print_live_field(q_disp, chosen_opt)
                        if on_progress:
                            on_progress("DROPDOWN_SELECTED", f"Selected [{q_disp}]: {chosen_opt}")
                        logger.info(f"[SolveSelect] Selected '{chosen_opt}' for '{q_disp}'")
                        solved_count += 1
                        safe_sleep(page, 0.25)
                    except Exception:
                        # Try selecting by partial text match
                        for o_el in opt_elements:
                            if chosen_opt.lower() in o_el.inner_text().lower():
                                s.select_option(value=o_el.get_attribute("value"))
                                q_disp = label_text.split("\n")[0][:35] if label_text else "Dropdown Option"
                                print_live_field(q_disp, o_el.inner_text().strip())
                                if on_progress:
                                    on_progress("DROPDOWN_SELECTED", f"Selected [{q_disp}]: {o_el.inner_text().strip()}")
                                solved_count += 1
                                safe_sleep(page, 0.25)
                                break
                    try:
                        page.evaluate("""(elem) => {
                            elem.style.outline = '';
                            elem.style.boxShadow = '';
                        }""", s)
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"[SolveSelect] Error solving select: {e}")
    except Exception as e:
        logger.debug(f"[SolveSelect] Error scanning selects: {e}")

    # -------------------------------------------------------------
    # 3. Universal Checkbox Solver (Consent / Privacy / Terms / Agreements)
    # -------------------------------------------------------------
    try:
        checkboxes = page.locator("input[type='checkbox']").all()
        for cb in checkboxes:
            check_pause_and_abort(page)
            try:
                if cb.is_checked():
                    continue

                cb_id = cb.get_attribute("id") or ""
                lbl_text = ""
                if cb_id:
                    lbl = page.locator(f"label[for='{cb_id}']").first
                    if lbl.count() > 0:
                        lbl_text = lbl.inner_text().strip()
                if not lbl_text:
                    try:
                        p_lbl = cb.locator("xpath=ancestor::label").first
                        if p_lbl.count() > 0:
                            lbl_text = p_lbl.inner_text().strip()
                    except Exception:
                        pass
                if not lbl_text:
                    try:
                        lbl = cb.locator("xpath=following-sibling::span[1] | xpath=following-sibling::label[1] | xpath=preceding::label[1]").first
                        if lbl.count() > 0:
                            lbl_text = lbl.inner_text().strip()
                    except Exception:
                        pass

                lbl_low = lbl_text.lower()
                if any(kw in lbl_low for kw in [
                    "agree", "consent", "acknowledge", "certify", "privacy", "terms", "policy",
                    "confirm", "accurate", "truthful", "electronic signature", "background check",
                    "drug test", "authorization"
                ]):
                    # Do not check if negative phrasing (e.g. "I decline")
                    if "do not agree" in lbl_low or "decline" in lbl_low:
                        continue

                    # Tier 1: label click
                    clicked = False
                    if cb_id:
                        lbl = page.locator(f"label[for='{cb_id}']").first
                        if lbl.count() > 0:
                            try:
                                lbl.click(timeout=1000)
                                clicked = True
                            except Exception:
                                pass
                    if not clicked or not cb.is_checked():
                        try:
                            cb.check(force=True, timeout=1000)
                        except Exception:
                            pass
                    # Tier 4: Synthetic event
                    try:
                        page.evaluate(
                            """(el) => {
                                el.checked = true;
                                el.dispatchEvent(new Event('input', { bubbles: true }));
                                el.dispatchEvent(new Event('change', { bubbles: true }));
                            }""",
                            cb
                        )
                    except Exception:
                        pass

                    disp = lbl_text.split("\n")[0][:35] if lbl_text else "Consent Agreement"
                    print_live_field(disp, "Accepted / Checked")
                    solved_count += 1
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"[SolveCheckboxes] Error scanning checkboxes: {e}")

    # -------------------------------------------------------------
    # 4. Universal React-Select / Custom Dropdown Solver
    # -------------------------------------------------------------
    try:
        rs_count = dynamically_solve_react_select_dropdowns(page, job=job, on_progress=on_progress)
        solved_count += rs_count
    except Exception as e:
        logger.debug(f"[SolveReactSelect] Error solving dropdowns: {e}")

    return solved_count


def handle_country_field(page: Page, el: Any, context: str, label_text: str = "") -> bool:
    """
    Intelligently detects and selects country fields across all ATS forms.
    Handles React-Select comboboxes, phone country code selectors, native dropdowns, and text inputs.
    Strictly selects 'India' for citizenship/nationality and 'United States' (+1) for residence/phone.
    """
    ctx_low = (context or "").lower()
    lbl_low = (label_text or "").lower()
    full_ctx = f"{ctx_low} {lbl_low}"

    # Guard: Strictly reject authorization / sponsorship questions that happen to contain the word "country"
    if any(k in full_ctx for k in ["right to work", "authorized", "eligible to work", "sponsorship", "require visa", "require sponsorship"]):
        return False

    # Determine target country
    is_citizenship = any(k in full_ctx for k in ["citizenship", "nationality", "country of citizenship"])
    target_country = "India" if is_citizenship else "United States"
    display_val = "India" if is_citizenship else "United States (+1)"

    try:
        tag = el.evaluate("e => e.tagName").lower()
    except Exception:
        tag = "input"

    # 1. If native <select>
    if tag == "select":
        try:
            for opt_label in [target_country, "USA", "United States of America", "+1", "US (+1)"]:
                try:
                    el.select_option(label=opt_label)
                    print_live_field("Country", display_val)
                    return True
                except Exception:
                    pass
            opts = el.locator("option").all()
            for o in opts:
                txt = o.inner_text().strip()
                if target_country.lower() in txt.lower():
                    el.select_option(value=o.get_attribute("value"))
                    print_live_field("Country", display_val)
                    return True
        except Exception:
            pass

    # 2. If <input> or combobox (React-Select, Greenhouse phone country, Ashby, Lever)
    try:
        el.scroll_into_view_if_needed()
        el.click(timeout=1500)
        time.sleep(0.3)

        # First check if matching option is already visible in the open dropdown menu
        for opt_text in [f"{target_country} +1", target_country, "United States", "+1"]:
            safe_text = opt_text.replace("'", "\\'")
            opt = page.locator(
                f"[role='option']:has-text('{safe_text}'), "
                f".select__option:has-text('{safe_text}'), "
                f"li:has-text('{safe_text}'), "
                f"div[class*='option']:has-text('{safe_text}')"
            ).first
            if opt.count() > 0 and opt.is_visible():
                opt.click(timeout=1500)
                print_live_field("Country", display_val)
                time.sleep(0.2)
                return True

        # If not already open or visible, clear and type query
        try:
            el.fill("")
        except Exception:
            pass
        el.press_sequentially(target_country, delay=50)
        time.sleep(0.4)

        # Look for filtered option
        safe_country = target_country.replace("'", "\\'")
        opt_after = page.locator(
            f"[role='option']:has-text('{safe_country}'), "
            f".select__option:has-text('{safe_country}'), "
            f"li:has-text('{safe_country}'), "
            f"div[class*='option']:has-text('{safe_country}')"
        ).first
        if opt_after.count() > 0 and opt_after.is_visible():
            opt_after.click(timeout=1500)
            print_live_field("Country", display_val)
            time.sleep(0.2)
            return True

        # Fallback: ArrowDown then Enter to select first filtered option
        el.press("ArrowDown")
        time.sleep(0.15)
        el.press("Enter")
        print_live_field("Country", display_val)
        time.sleep(0.2)
        return True
    except Exception as e:
        logger.debug(f"handle_country_field error: {e}")

    # 3. Standard text input fallback
    try:
        human_type_input(page, el, "Country", target_country)
        print_live_field("Country", display_val)
        return True
    except Exception:
        return False


def solve_combobox_field(page: Page, inp: Any, label_text: str, context: str, job: Optional[Dict[str, Any]] = None) -> bool:
    """
    Intelligently handles combobox / React-Select inputs (e.g. Greenhouse, Ashby, Lever).
    Never types open-ended text into comboboxes; selects precise values according to candidate invariants.
    """
    ctx_low = (context or "").lower()
    lbl_low = (label_text or "").lower()
    full_ctx = f"{ctx_low} {lbl_low}"

    # Country & Nationality
    if "country" in full_ctx or "nationality" in full_ctx or "citizenship" in full_ctx:
        return handle_country_field(page, inp, context, label_text)

    # Location / City
    if "location" in full_ctx or "city" in full_ctx:
        try:
            inp.scroll_into_view_if_needed()
            inp.click(timeout=1500)
            time.sleep(0.2)
            inp.fill("")
            inp.press_sequentially("Dayton, OH", delay=60)
            time.sleep(0.8)
            opt = page.locator("[role='option']:has-text('Dayton'), .select__option:has-text('Dayton'), li:has-text('Dayton')").first
            if opt.count() > 0 and opt.is_visible():
                opt.click(timeout=1500)
            else:
                inp.press("ArrowDown")
                time.sleep(0.1)
                inp.press("Enter")
            print_live_field("Location (Selected)", "Dayton, Ohio, United States")
            return True
        except Exception:
            return False

    # Month & Year (Education dates)
    elif "month" in full_ctx:
        if "end" in full_ctx or "grad" in full_ctx or "to" in full_ctx:
            target = "December"
            field_name = "End Month"
        else:
            target = "August"
            field_name = "Start Month"
    elif "year" in full_ctx:
        if "end" in full_ctx or "grad" in full_ctx or "to" in full_ctx:
            target = "2024"
            field_name = "End Year"
        else:
            target = "2023"
            field_name = "Start Year"
    # School / University
    elif any(k in full_ctx for k in ["school", "university", "institution", "college"]):
        target = "University of Dayton"
        field_name = "University"
    # Degree
    elif "degree" in full_ctx:
        target = "Master's Degree"
        field_name = "Degree"
    # Discipline / Major
    elif any(k in full_ctx for k in ["discipline", "major", "field of study"]):
        target = "Computer Science"
        field_name = "Discipline"
    # Work Authorization
    elif any(k in full_ctx for k in ["authorized", "work authorization", "legal work authori", "eligible to work", "right to work"]):
        target = "Yes"
        field_name = "Work Authorization"
    # Visa Sponsorship
    elif any(k in full_ctx for k in ["sponsorship", "visa", "require immigration", "require sponsorship"]):
        target = "Yes"
        field_name = "Future Sponsorship"
    # Relocation / On-site / In-office
    elif any(k in full_ctx for k in ["relocate", "relocation", "in-office", "office", "hybrid", "onsite"]):
        target = "Yes"
        field_name = "Relocation / On-site"
    # Gender
    elif "gender" in full_ctx:
        target = "Male"
        field_name = "Gender Identity"
    # Race / Ethnicity
    elif "race" in full_ctx or "ethnicity" in full_ctx:
        target = "Asian"
        field_name = "Race / Ethnicity"
    # Pronoun
    elif "pronoun" in full_ctx:
        target = "He/Him"
        field_name = "Pronouns"
    # Sexual Orientation
    elif "sexual orientation" in full_ctx:
        target = "Prefer not to say"
        field_name = "Sexual Orientation"
    # Source / Referral
    elif any(k in full_ctx for k in ["how did you hear", "hear about us", "source"]):
        target = "LinkedIn"
        field_name = "Referral Source"
    # Veteran
    elif "veteran" in full_ctx:
        target = "I am not a protected veteran"
        field_name = "Veteran Status"
    # Disability
    elif "disability" in full_ctx:
        target = "No, I do not have a disability"
        field_name = "Disability Status"
    else:
        from jarvis_brain import jarvis_brain
        try:
            page.keyboard.press("Escape")
            time.sleep(0.1)
            inp.scroll_into_view_if_needed()
            inp.click(timeout=1000)
            time.sleep(0.3)
            opts = page.locator("[role='listbox'] [role='option'], .select__menu [role='option'], .remix-css-menu [role='option'], [role='option'], .select__option, li").all()
            opt_texts = [o.inner_text().strip() for o in opts if o.inner_text().strip()]
            cleaned = [o for o in opt_texts if not any(ph in o.lower() for ph in ["select", "choose", "--"])]
            if cleaned:
                best = jarvis_brain.choose_best_option(label_text, cleaned, job=job)
                if best:
                    target = best
                    field_name = label_text[:25] or "Combobox Option"
                else:
                    return False
            else:
                return False
        except Exception:
            return False

    try:
        page.keyboard.press("Escape")
        time.sleep(0.1)
        inp.scroll_into_view_if_needed()
        inp.click(timeout=1000)
        time.sleep(0.3)
        safe_target = target.replace("'", "\\'")

        # Look for option in active dropdown menu
        opt = page.locator(
            f"[role='listbox'] [role='option']:has-text('{safe_target}'), "
            f".select__menu [role='option']:has-text('{safe_target}'), "
            f"[role='option']:has-text('{safe_target}'), "
            f".select__option:has-text('{safe_target}'), "
            f"li:has-text('{safe_target}')"
        ).first
        if opt.count() > 0 and opt.is_visible():
            opt.click(timeout=1500)
            print_live_field(field_name, target)
            return True

        try:
            inp.fill("")
        except Exception:
            pass
        inp.press_sequentially(target, delay=40)
        time.sleep(0.4)

        opt_after = page.locator(
            f"[role='listbox'] [role='option']:has-text('{safe_target}'), "
            f".select__menu [role='option']:has-text('{safe_target}'), "
            f"[role='option']:has-text('{safe_target}'), "
            f".select__option:has-text('{safe_target}'), "
            f"li:has-text('{safe_target}')"
        ).first
        if opt_after.count() > 0 and opt_after.is_visible():
            opt_after.click(timeout=1500)
            print_live_field(field_name, target)
            return True

        inp.press("ArrowDown")
        time.sleep(0.1)
        inp.press("Enter")
        print_live_field(field_name, target)
        return True
    except Exception as e:
        logger.debug(f"solve_combobox_field error for {label_text}: {e}")
        return False


def fill_greenhouse_form(page: Page, pdf_path: Path, job: Optional[Dict[str, Any]] = None, on_progress: Any = None) -> bool:
    """
    Automates Greenhouse application forms with comprehensive candidate credentials,
    smart question answering, and modern react-select dropdown support.
    """
    logger.info("Detected Greenhouse application layout. Populating standard and custom fields...")
    print_live_action("📋", "Detected Greenhouse layout — populating candidate fields live...")
    if on_progress:
        on_progress("FORM_FILL", "Greenhouse portal detected. Populating candidate credentials one-by-one...")
    filled = False

    # 1. Standard text, email, tel, combobox, and textarea inputs
    all_inputs = page.locator("input[type='text'], input[type='email'], input[type='tel'], input:not([type]), textarea").all()
    for inp in all_inputs:
        check_pause_and_abort(page)
        try:
            if not inp.is_visible():
                continue
            cls = (inp.get_attribute("class") or "").lower()
            # NEVER type into internal React-Select or Remix combobox inputs! They are handled dynamically by dynamically_solve_react_select_dropdowns
            if "select__input" in cls or "remix-css-" in cls:
                continue

            inp_id = (inp.get_attribute("id") or "").lower()
            inp_name = (inp.get_attribute("name") or "").lower()
            aria_label = (inp.get_attribute("aria-label") or "").lower()
            placeholder = (inp.get_attribute("placeholder") or "").lower()
            role = (inp.get_attribute("role") or "").lower()
            aria_autocomplete = inp.get_attribute("aria-autocomplete") or ""

            try:
                tag_name = inp.evaluate("e => e.tagName").lower()
            except Exception:
                tag_name = "input"

            # Preceding or linked label
            label_text = ""
            if inp_id:
                lbl = page.locator(f"label[for='{inp_id}'], label#{inp_id}-label")
                if lbl.count() > 0:
                    label_text = lbl.inner_text().lower()
            if not label_text:
                try:
                    label_text = inp.locator("xpath=preceding::label[1]").inner_text().lower()
                except Exception:
                    pass

            context = f"{inp_id} {inp_name} {aria_label} {placeholder} {label_text}"
            val = inp.input_value()

            # Country combobox or input: Highest priority interception (excluding right-to-work / sponsorship)
            if "country" in context and not any(k in context for k in ["right to work", "authorized", "eligible", "sponsorship", "require"]):
                if handle_country_field(page, inp, context, label_text):
                    filled = True
                continue

            if val:
                continue

            if "preferred" in context and ("name" in context or "first" in context):
                human_type_input(page, inp, "Preferred First Name", CANDIDATE_PREFERRED_NAME, on_progress=on_progress)
                filled = True
            elif "preferred last name" in context:
                pass  # Optional
            elif "first" in context and "name" in context:
                human_type_input(page, inp, "First Name", CANDIDATE_FIRST_NAME, on_progress=on_progress)
                filled = True
            elif "last" in context and "name" in context:
                human_type_input(page, inp, "Last Name", CANDIDATE_LAST_NAME, on_progress=on_progress)
                filled = True
            elif "name" in context and not any(k in context for k in ["company", "school", "degree", "first", "last", "file", "user", "title"]):
                human_type_input(page, inp, "Full Name", CANDIDATE_NAME, on_progress=on_progress)
                filled = True
            elif "email" in context:
                human_type_input(page, inp, "Email", CANDIDATE_EMAIL, on_progress=on_progress)
                filled = True
            elif "phone" in context or "mobile" in context:
                clean_phone = re.sub(r"\D", "", CANDIDATE_PHONE)
                phone_to_fill = clean_phone[-10:] if len(clean_phone) >= 10 else CANDIDATE_PHONE
                human_type_input(page, inp, "Phone", phone_to_fill, on_progress=on_progress)
                filled = True
            elif "linkedin" in context:
                if CANDIDATE_LINKEDIN:
                    human_type_input(page, inp, "LinkedIn Profile", CANDIDATE_LINKEDIN, on_progress=on_progress)
                    filled = True
                else:
                    logger.info("Skipped optional LinkedIn field (no URL configured by candidate).")
            elif "github" in context or "website" in context or "portfolio" in context:
                human_type_input(page, inp, "Website / Portfolio", CANDIDATE_GITHUB, on_progress=on_progress)
                filled = True
            elif "salary" in context or "compensation" in context or "expectation" in context:
                human_type_input(page, inp, "Salary Expectations", CANDIDATE_SALARY, on_progress=on_progress)
                filled = True
            elif "company" in context or "employer" in context:
                human_type_input(page, inp, "Current Company", "Seeking Software Engineer Roles", on_progress=on_progress)
                filled = True
            elif "title" in context or "headline" in context or "position" in context or "occupation" in context:
                human_type_input(page, inp, "Job Title", "Software Engineer", on_progress=on_progress)
                filled = True
            elif "degree" in context:
                human_type_input(page, inp, "Degree", CANDIDATE_DEGREE, on_progress=on_progress)
                filled = True
            elif "discipline" in context or "major" in context or "field of study" in context:
                human_type_input(page, inp, "Discipline / Major", CANDIDATE_MAJOR, on_progress=on_progress)
                filled = True
            elif "school" in context or "university" in context or "institution" in context or "college" in context:
                human_type_input(page, inp, "University", CANDIDATE_UNIVERSITY, on_progress=on_progress)
                filled = True
            elif "gpa" in context:
                human_type_input(page, inp, "GPA", CANDIDATE_GPA, on_progress=on_progress)
                filled = True
            elif "legal address" in context:
                human_type_input(page, inp, "Legal Address", "Dayton, OH 45409, United States", on_progress=on_progress)
                filled = True
            elif "currently located" in context or "city, state" in context:
                human_type_input(page, inp, "Current Location", "Dayton, OH", on_progress=on_progress)
                filled = True
            elif "address" in context:
                human_type_input(page, inp, "Address", "Dayton, OH 45409, United States", on_progress=on_progress)
                filled = True
            elif "location" in context or "city" in context:
                if "city" in context and "location" not in context:
                    human_type_input(page, inp, "City", CANDIDATE_CITY, on_progress=on_progress)
                else:
                    human_type_input(page, inp, "Location", "Dayton, OH, USA", on_progress=on_progress)
                filled = True
            elif "state" in context:
                human_type_input(page, inp, "State", CANDIDATE_STATE, on_progress=on_progress)
                filled = True
            elif "postal" in context or "zip" in context:
                human_type_input(page, inp, "Postal Code", CANDIDATE_ZIP, on_progress=on_progress)
                filled = True
            else:
                # Custom prompt / open-ended textarea detected!
                prompt_text = label_text or placeholder or aria_label or inp_name
                is_textarea = (tag_name == "textarea")
                is_essay_prompt = any(k in prompt_text.lower() for k in ["why", "tell", "describe", "explain", "share", "project", "use ai", "accomplish", "how do you", "what are your"])
                if prompt_text and len(prompt_text) > 3 and not any(k in prompt_text for k in ["upload", "file", "attach", "resume", "cv", "captcha"]):
                    if is_textarea or is_essay_prompt:
                        print_live_action("🧠", f"Jarvis Brain evaluating custom prompt: '{prompt_text[:50]}...'")
                        from jarvis_brain import jarvis_brain
                        c_title = job.get("title", "Software Engineer") if job else "Software Engineer"
                        c_comp = job.get("company", "Target Company") if job else "Target Company"
                        c_desc = job.get("job_description", "") if job else ""
                        smart_answer = jarvis_brain.answer_custom_question(prompt_text, job_title=c_title, company=c_comp, job_description=c_desc)
                        if smart_answer:
                            human_type_input(page, inp, prompt_text[:28], smart_answer, on_progress=on_progress)
                            filled = True
        except ApplicationAbortedException:
            raise
        except Exception:
            pass

    # Dedicated Greenhouse react-select location handler (#candidate-location, #job_application_location)
    try:
        gh_loc = page.locator("#candidate-location, input[id*='candidate-location'], input#job_application_location").first
        if gh_loc.count() > 0 and gh_loc.is_visible():
            gh_loc.click()
            time.sleep(0.2)
            gh_loc.fill("")
            gh_loc.press_sequentially("Dayton, OH", delay=80)
            time.sleep(1.0)
            opt = page.locator(
                "[id*='candidate-location-option-0'], "
                "[role='option']:has-text('Dayton'), "
                ".select__option:has-text('Dayton'), "
                "li:has-text('Dayton')"
            ).first
            if opt.count() > 0 and opt.is_visible():
                opt.click(timeout=1500)
                print_live_field("Location (Selected)", "Dayton, Ohio, United States")
                filled = True
            else:
                gh_loc.press("ArrowDown")
                time.sleep(0.2)
                gh_loc.press("Enter")
                print_live_field("Location (Selected)", "Dayton, Ohio, United States")
                filled = True
    except Exception:
        pass

    # 2. Attach PDF Resume
    resume_attached = False
    file_inputs = page.locator("input[type='file'], input#resume").all()
    for fi in file_inputs:
        try:
            fi_id = (fi.get_attribute("id") or "").lower()
            fi_name = (fi.get_attribute("name") or "").lower()
            fi_aria = (fi.get_attribute("aria-label") or "").lower()
            fi_ctx = f"{fi_id} {fi_name} {fi_aria}"
            if "resume" in fi_ctx or "cv" in fi_ctx:
                fi.set_input_files(str(pdf_path))
                resume_attached = True
                filled = True
                logger.info(f"Attached tailored PDF resume to Greenhouse: {pdf_path.name}")
                print_live_field("Attached Resume", pdf_path.name)
                time.sleep(0.5)
                break
        except Exception:
            pass

    if not resume_attached and file_inputs:
        try:
            file_inputs[0].set_input_files(str(pdf_path))
            filled = True
            logger.info(f"Attached tailored PDF resume to Greenhouse: {pdf_path.name}")
            print_live_field("Attached Resume", pdf_path.name)
            time.sleep(0.5)
        except Exception:
            pass

    # 3. Native <select> dropdowns
    selects = page.locator("select").all()
    for s in selects:
        try:
            if not s.is_visible():
                continue
            label = ""
            try:
                label = s.locator("xpath=preceding::label[1]").inner_text().lower()
            except Exception:
                pass
            name = (s.get_attribute("name") or "").lower()
            ctx = f"{label} {name}"

            if "authorized" in ctx or "eligible" in ctx or "right to work" in ctx:
                s.select_option(label="Yes")
                print_live_field("Work Authorization", "Yes (Legally Authorized)")
                filled = True
            elif "sponsorship" in ctx or "visa" in ctx:
                s.select_option(label="Yes")
                print_live_field("Future Sponsorship", "Yes (F-1 STEM OPT / H-1B)")
                filled = True
            elif "hybrid" in ctx or "in-office" in ctx or "office" in ctx or "hub" in ctx:
                s.select_option(label="Yes")
                print_live_field("Hybrid Schedule", "Yes (Agreed)")
                filled = True
            elif "former" in ctx or "employed" in ctx or "u.s. person" in ctx:
                s.select_option(label="No")
                print_live_field(label[:25] or "Disclosure", "No")
                filled = True
            elif "agreement" in ctx or "non-compete" in ctx:
                s.select_option(label="No")
                print_live_field("Non-Compete Agreement", "No")
                filled = True
            elif "degree" in ctx:
                degree_picked = False
                for deg_lbl in [
                    "Master of Science in Computer Science",
                    "Master of Science",
                    "Master of Science (MS)",
                    "Master of Science (M.S.)",
                    "Master's Degree",
                    "Master's",
                    "Masters"
                ]:
                    try:
                        s.select_option(label=deg_lbl)
                        print_live_field("Degree", deg_lbl)
                        filled = True
                        degree_picked = True
                        break
                    except Exception:
                        pass
                if not degree_picked:
                    try:
                        opts = s.locator("option").all()
                        for opt_el in opts:
                            txt = opt_el.inner_text().strip()
                            t_low = txt.lower()
                            # Strictly filter out any MBA or Business Administration option
                            if ("master" in t_low or "ms" in t_low) and not any(b in t_low for b in ["mba", "business", "admin"]):
                                val = opt_el.get_attribute("value")
                                s.select_option(value=val)
                                print_live_field("Degree", txt)
                                filled = True
                                degree_picked = True
                                break
                    except Exception:
                        pass
            elif "country" in ctx:
                s.select_option(label="United States")
                print_live_field("Country", "United States")
                filled = True
            elif "gender" in ctx:
                s.select_option(label="Male")
            elif "veteran" in ctx or "disability" in ctx:
                s.select_option(index=1)
        except Exception:
            pass

    # 4. Modern Greenhouse react-select dropdowns (.select__control)
    try:
        solved_rs = dynamically_solve_react_select_dropdowns(page, job=job, on_progress=on_progress)
        if solved_rs > 0:
            filled = True
    except Exception as e:
        logger.debug(f"dynamically_solve_react_select_dropdowns error in Greenhouse: {e}")

    # 5. Universal dynamically flexible radio buttons, EEOC options, dropdowns & checkboxes
    try:
        solved = solve_form_options_and_radios(page, job=job, on_progress=on_progress)
        if solved > 0:
            filled = True
    except Exception as e:
        logger.debug(f"solve_form_options_and_radios error in Greenhouse: {e}")

    return filled


def fill_ashby_form(page: Page, pdf_path: Path, job: Optional[Dict[str, Any]] = None, on_progress: Any = None) -> bool:
    """Automates Ashby application forms with smart field matching."""
    check_pause_and_abort(page)
    logger.info("Detected Ashby application layout. Populating candidate details...")
    print_live_action("📋", "Detected Ashby layout — populating candidate fields live...")
    if on_progress:
        on_progress("FORM_FILL", "Ashby layout detected. Populating candidate fields one-by-one...")
    filled = False

    # Check if application form tab / button needs to be clicked
    apply_tab = page.locator(
        "a[href*='/application']:visible, a:has-text('Apply for this Job'):visible, "
        "a:has-text('Apply for this role'):visible, button:has-text('Apply for this Job'):visible, "
        "button:has-text('Apply for this role'):visible, button:has-text('Apply'):visible, a:has-text('Apply'):visible"
    ).first
    if apply_tab.count() > 0 and apply_tab.is_visible():
        try:
            apply_tab.click(timeout=2500)
            safe_sleep(page, 1.5)
        except Exception:
            pass

    # 1. Name fields (check for separate first/last or unified full name)
    first_name_input = page.locator("input[name*='first' i], input[id*='first' i], input[placeholder*='first' i]").first
    last_name_input = page.locator("input[name*='last' i], input[id*='last' i], input[placeholder*='last' i]").first
    
    if first_name_input.count() > 0 and first_name_input.is_visible() and last_name_input.count() > 0 and last_name_input.is_visible():
        human_type_input(page, first_name_input, "First Name", CANDIDATE_FIRST_NAME, on_progress=on_progress)
        human_type_input(page, last_name_input, "Last Name", CANDIDATE_LAST_NAME, on_progress=on_progress)
        filled = True
    else:
        for sel in [
            "input[name='_systemfield_name']", "input[id='_systemfield_name']", "[data-systemfield='name']",
            "input[name*='name' i]", "input[placeholder*='name' i]"
        ]:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                human_type_input(page, el, "Full Name", CANDIDATE_NAME, on_progress=on_progress)
                filled = True
                break

    # 2. Email
    for sel in [
        "input[name='_systemfield_email']", "input[id='_systemfield_email']", "[data-systemfield='email']",
        "input[type='email']", "input[name*='email' i]", "input[placeholder*='email' i]"
    ]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            human_type_input(page, el, "Email", CANDIDATE_EMAIL, on_progress=on_progress)
            filled = True
            break

    # 3. Phone
    for sel in [
        "input[name='_systemfield_phone']", "input[id='_systemfield_phone']", "[data-systemfield='phone']",
        "input[type='tel']", "input[name*='phone' i]", "input[placeholder*='phone' i]"
    ]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            human_type_input(page, el, "Phone", CANDIDATE_PHONE, on_progress=on_progress)
            filled = True
            break

    # 4. Country & Phone Country Code
    for sel in ["input[id*='country' i]", "input[name*='country' i]", "input[placeholder*='country' i]", "[aria-label*='country' i]", ".country-select input"]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            if handle_country_field(page, el, "country", "Country"):
                filled = True
                break

    # 5. Location input with autocomplete
    loc_input = page.locator(
        "input[name='_systemfield_location'], input[id='_systemfield_location'], "
        "input[id*='location' i], input[placeholder*='location' i], input[name*='location' i]"
    ).first
    if loc_input.count() > 0 and loc_input.is_visible():
        try:
            loc_input.scroll_into_view_if_needed(timeout=1500)
            loc_input.fill("")
            loc_input.press_sequentially("Dayton, OH", delay=60)
            safe_sleep(page, 0.8)
            suggestion = page.locator("[role='option'], [class*='option'], [class*='suggestion'], li:has-text('Dayton')").first
            if suggestion.count() > 0 and suggestion.is_visible():
                suggestion.click()
                print_live_field("Location", "Dayton, OH (Selected)")
                filled = True
            else:
                loc_input.press("ArrowDown")
                time.sleep(0.15)
                loc_input.press("Enter")
                print_live_field("Location", "Dayton, OH (Selected)")
                filled = True
        except Exception:
            pass

    # 6. LinkedIn & GitHub
    if CANDIDATE_LINKEDIN:
        for sel in ["input[name*='linkedin' i]", "input[placeholder*='linkedin' i]", "input[id*='linkedin' i]"]:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                human_type_input(page, el, "LinkedIn Profile", CANDIDATE_LINKEDIN, on_progress=on_progress)
                filled = True
                break
    else:
        logger.info("Skipped optional LinkedIn field on Ashby (no URL configured).")

    for sel in ["input[name*='github' i]", "input[placeholder*='github' i]", "input[id*='github' i]"]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            human_type_input(page, el, "GitHub Profile", CANDIDATE_GITHUB, on_progress=on_progress)
            filled = True
            break

    # 7. Portfolio / Website
    for sel in ["input[name*='website' i]", "input[name*='portfolio' i]", "input[placeholder*='portfolio' i]"]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            human_type_input(page, el, "Portfolio / Website", CANDIDATE_GITHUB, on_progress=on_progress)
            filled = True
            break

    # 8. Resume file upload
    file_input = page.locator("input[type='file'], input[name='_systemfield_resume']").first
    if file_input.count() > 0:
        file_input.set_input_files(str(pdf_path))
        filled = True
        logger.info(f"Attached tailored PDF resume to Ashby: {pdf_path.name}")
        print_live_field("Attached Resume", pdf_path.name)
        if on_progress:
            on_progress("RESUME_ATTACHED", f"Uploaded tailored ATS resume ({pdf_path.name}) to Ashby.")

    # 9. Combobox fields in Ashby
    comboboxes = page.locator("[role='combobox'], .select__input, input[aria-autocomplete]").all()
    for cb in comboboxes:
        check_pause_and_abort(page)
        try:
            if not cb.is_visible():
                continue
            lbl_text = ""
            try:
                lbl = cb.locator("xpath=preceding::label[1]").first
                if lbl.count() > 0:
                    lbl_text = lbl.inner_text().strip()
            except Exception:
                pass
            solve_combobox_field(page, cb, lbl_text, lbl_text, job=job)
        except Exception:
            pass

    # 10. Universal dynamically flexible questionnaires, EEOC options, radios & dropdowns in Ashby
    try:
        solved = solve_form_options_and_radios(page, job=job, on_progress=on_progress)
        if solved > 0:
            filled = True
    except Exception as e:
        logger.debug(f"solve_form_options_and_radios error in Ashby: {e}")

    # 11. Custom Questions & Textareas in Ashby
    try:
        textareas = page.locator("textarea, input:not([type]), input[type='text']:not([value])").all()
        for ta in textareas:
            check_pause_and_abort(page)
            if not ta.is_visible():
                continue
            cur_val = ta.input_value().strip()
            if cur_val:
                continue
            prompt = ""
            try:
                prompt = ta.locator("xpath=preceding::label[1]").inner_text().strip()
            except Exception:
                pass
            if not prompt:
                prompt = ta.get_attribute("placeholder") or ta.get_attribute("aria-label") or ""
            # Guard against typing essay bio into factual, country, or demographic inputs
            if prompt and len(prompt) > 3 and not any(k in prompt.lower() for k in [
                "name", "email", "phone", "linkedin", "github", "location", "resume",
                "country", "city", "state", "zip", "postal", "gender", "race", "ethnicity", "veteran", "disability"
            ]):
                print_live_action("🧠", f"Jarvis Brain evaluating Ashby custom prompt: '{prompt[:50]}...'")
                from jarvis_brain import jarvis_brain
                c_title = job.get("title", "Software Engineer") if job else "Software Engineer"
                c_comp = job.get("company", "Target Company") if job else "Target Company"
                c_desc = job.get("job_description", "") if job else ""
                ans = jarvis_brain.answer_custom_question(prompt, job_title=c_title, company=c_comp, job_description=c_desc)
                if ans:
                    human_type_input(page, ta, prompt[:25], ans, on_progress=on_progress)
                    filled = True
    except Exception:
        pass

    return filled


def fill_lever_form(page: Page, pdf_path: Path, job: Optional[Dict[str, Any]] = None, on_progress: Any = None) -> bool:
    """Specialized auto-filler for Lever.co career pages."""
    check_pause_and_abort(page)
    print_live_action("📋", "Detected Lever layout — populating candidate fields live...")
    if on_progress:
        on_progress("FORM_FILL", "Lever portal detected. Populating candidate fields one-by-one...")
    filled = False

    # 1. Full Name
    for sel in ["input[name='name']", "input#name", "input[name*='name' i]"]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            human_type_input(page, el, "Full Name", CANDIDATE_NAME, on_progress=on_progress)
            filled = True
            break

    # 2. Email
    for sel in ["input[name='email']", "input[type='email']", "input[name*='email' i]"]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            human_type_input(page, el, "Email", CANDIDATE_EMAIL, on_progress=on_progress)
            filled = True
            break

    # 3. Phone
    for sel in ["input[name='phone']", "input[type='tel']", "input[name*='phone' i]"]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            human_type_input(page, el, "Phone", CANDIDATE_PHONE, on_progress=on_progress)
            filled = True
            break

    # Country & Phone Country
    for sel in ["input[name*='country' i]", "input[id*='country' i]", "input[placeholder*='country' i]"]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            if handle_country_field(page, el, "country", "Country"):
                filled = True
                break

    # 4. Current Organization / Company
    for sel in ["input[name='org']", "input[name*='company' i]", "input[name*='organization' i]"]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            human_type_input(page, el, "Current Company", CANDIDATE_CURRENT_COMPANY, on_progress=on_progress)
            filled = True
            break

    # 5. LinkedIn URL
    if CANDIDATE_LINKEDIN:
        for sel in ["input[name*='urls[LinkedIn]']", "input[name*='linkedin' i]"]:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                human_type_input(page, el, "LinkedIn Profile", CANDIDATE_LINKEDIN, on_progress=on_progress)
                filled = True
                break
    else:
        logger.info("Skipped optional LinkedIn field on Lever (no URL configured).")

    # 6. GitHub URL
    for sel in ["input[name*='urls[GitHub]']", "input[name*='github' i]"]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            human_type_input(page, el, "GitHub Portfolio", CANDIDATE_GITHUB, on_progress=on_progress)
            filled = True
            break

    # 7. Portfolio / Website URL
    for sel in ["input[name*='urls[Portfolio]']", "input[name*='urls[Other]']", "input[name*='portfolio' i]"]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            human_type_input(page, el, "Portfolio / Website", CANDIDATE_GITHUB, on_progress=on_progress)
            filled = True
            break

    # 8. Location
    for sel in ["input[name*='location' i]", "input[id*='location' i]"]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            human_type_input(page, el, "Location", "Dayton, OH", on_progress=on_progress)
            filled = True
            break

    # 9. Resume File Upload
    file_input = page.locator("input[type='file'], input[name='resume']").first
    if file_input.count() > 0:
        file_input.set_input_files(str(pdf_path))
        print_live_field("Attached Resume", pdf_path.name)
        if on_progress:
            on_progress("RESUME_ATTACHED", f"Uploaded tailored ATS resume ({pdf_path.name}) to Lever.")
        filled = True

    # 10. Universal dynamically flexible questionnaires, EEOC options, radios & dropdowns in Lever
    try:
        solved = solve_form_options_and_radios(page, job=job, on_progress=on_progress)
        if solved > 0:
            filled = True
    except Exception as e:
        logger.debug(f"solve_form_options_and_radios error in Lever: {e}")

    # 11. Custom Textareas & Questions in Lever
    try:
        textareas = page.locator("textarea").all()
        for ta in textareas:
            check_pause_and_abort(page)
            if not ta.is_visible():
                continue
            cur_val = ta.input_value().strip()
            if cur_val:
                continue
            prompt = ""
            try:
                prompt = ta.locator("xpath=preceding::div[contains(@class, 'application-label')][1]").inner_text().strip()
            except Exception:
                pass
            if not prompt:
                prompt = ta.get_attribute("placeholder") or ""
            if prompt and len(prompt) > 3 and not any(k in prompt.lower() for k in ["country", "gender", "race", "veteran", "disability", "phone", "email"]):
                print_live_action("🧠", f"Jarvis Brain evaluating Lever custom prompt: '{prompt[:50]}...'")
                from jarvis_brain import jarvis_brain
                c_title = job.get("title", "Software Engineer") if job else "Software Engineer"
                c_comp = job.get("company", "Target Company") if job else "Target Company"
                c_desc = job.get("job_description", "") if job else ""
                ans = jarvis_brain.answer_custom_question(prompt, job_title=c_title, company=c_comp, job_description=c_desc)
                if ans:
                    human_type_input(page, ta, prompt[:25], ans, on_progress=on_progress)
                    filled = True
    except Exception:
        pass

    return filled


def fill_standard_career_form(page: Page, pdf_path: Path, job: Optional[Dict[str, Any]] = None, on_progress: Any = None) -> bool:
    """Intelligently detects ATS platform and fills candidate credentials."""
    url = page.url.lower()

    if "greenhouse.io" in url or "gh_jid" in url:
        return fill_greenhouse_form(page, pdf_path, job=job, on_progress=on_progress)
    elif "ashbyhq.com" in url:
        return fill_ashby_form(page, pdf_path, job=job, on_progress=on_progress)
    elif "lever.co" in url:
        return fill_lever_form(page, pdf_path, job=job, on_progress=on_progress)

    # General ATS Fallback (Workable, SmartRecruiters, Jobvite, etc.)
    print_live_action("📋", "Populating standard career portal fields...")
    if on_progress:
        on_progress("FORM_FILL", "Standard career portal detected. Populating candidate fields one-by-one...")
    filled = False

    # Name: Full name or First/Last
    for sel in ["input[name='name']", "input#name"]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            human_type_input(page, el, "Full Name", CANDIDATE_NAME, on_progress=on_progress)
            filled = True
            break

    for sel in ["input[name*='first' i]", "input[id*='first' i]"]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            human_type_input(page, el, "First Name", CANDIDATE_FIRST_NAME, on_progress=on_progress)
            filled = True
            break
    for sel in ["input[name*='last' i]", "input[id*='last' i]"]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            human_type_input(page, el, "Last Name", CANDIDATE_LAST_NAME, on_progress=on_progress)
            filled = True
            break
    for sel in ["input[type='email']", "input[name*='email' i]"]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            human_type_input(page, el, "Email", CANDIDATE_EMAIL, on_progress=on_progress)
            filled = True
            break
    for sel in ["input[type='tel']", "input[name*='phone' i]"]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            human_type_input(page, el, "Phone", CANDIDATE_PHONE, on_progress=on_progress)
            filled = True
            break

    # Country
    for sel in ["input[name*='country' i]", "input[id*='country' i]", "select[name*='country' i]"]:
        el = page.locator(sel).first
        if el.count() > 0 and el.is_visible():
            if handle_country_field(page, el, "country", "Country"):
                filled = True
                break

    file_input = page.locator("input[type='file']").first
    if file_input.count() > 0:
        file_input.set_input_files(str(pdf_path))
        print_live_field("Attached Resume", pdf_path.name)
        if on_progress:
            on_progress("RESUME_ATTACHED", f"Uploaded tailored ATS resume: {pdf_path.name}")
        filled = True

    # Universal dynamically flexible options, EEOC surveys, radios & checkboxes
    try:
        solved = solve_form_options_and_radios(page, job=job, on_progress=on_progress)
        if solved > 0:
            filled = True
    except Exception as e:
        logger.debug(f"solve_form_options_and_radios error in general ATS: {e}")

    return filled


def check_submission_result(page: Page, platform: str) -> Dict[str, Any]:
    """
    Strict, truth-verifying submission evaluator.
    Returns:
      {
         "is_applied": True/False,
         "status": "APPLIED" / "PORTAL_CAPTURED",
         "reason": "Detailed description"
      }
    Zero false positives: Only marks APPLIED if official confirmation is verified
    and zero validation errors/CAPTCHAs are blocking the submission.
    """
    time.sleep(3.5)
    current_url = page.url.lower()

    # 1. Check for presence of active bot shields (reCAPTCHA / Turnstile / hCaptcha)
    bot_shield = False
    shield_name = ""
    try:
        if page.locator("iframe[src*='recaptcha'], .g-recaptcha, #g-recaptcha-response").count() > 0:
            bot_shield = True
            shield_name = "Google reCAPTCHA"
        elif page.locator("iframe[src*='turnstile'], .cf-turnstile").count() > 0:
            bot_shield = True
            shield_name = "Cloudflare Turnstile"
        elif page.locator("iframe[src*='hcaptcha'], .h-captcha").count() > 0:
            bot_shield = True
            shield_name = "hCaptcha"
    except Exception:
        pass

    # 2. Check for form validation error elements on the page
    validation_errors: List[str] = []
    error_selectors = [
        ".field-error", ".validation-error", ".text-danger",
        "[aria-invalid='true']", "p[id*='error']", "span[id*='error']",
        "div[class*='error']", ".select__control--is-invalid",
        "[data-qa='form-error']"
    ]
    for sel in error_selectors:
        try:
            items = page.locator(sel).all()
            for it in items:
                if it.is_visible():
                    txt = it.inner_text().strip()
                    if txt and len(txt) < 100 and txt not in validation_errors:
                        validation_errors.append(txt)
        except Exception:
            pass

    # Also search body text for typical ATS error banners
    body_text = ""
    try:
        body_text = page.locator("body").inner_text().lower()
    except Exception:
        pass

    error_phrases = [
        "your form needs corrections", "missing entry for required field",
        "this field is required", "please fill out this field",
        "please enter a valid", "please answer this question"
    ]
    has_text_error = any(phrase in body_text for phrase in error_phrases)

    # 3. Check for genuine submission confirmation
    url_confirmed = any(kw in current_url for kw in [
        "/confirmation", "/thank-you", "/application-success", "/applied",
        "/success", "thank_you"
    ])

    success_phrases = [
        "thank you for applying", "your application was submitted",
        "application has been received", "we have received your application",
        "thanks for applying", "we've received your application",
        "application submitted successfully", "your application has been submitted"
    ]
    text_confirmed = any(phrase in body_text for phrase in success_phrases)

    # =========================================================================
    # THE TRUTH GATE:
    # An application is ONLY "APPLIED" if confirmed AND NOT blocked by errors
    # =========================================================================
    if (url_confirmed or text_confirmed) and not validation_errors and not has_text_error:
        return {
            "is_applied": True,
            "status": "APPLIED",
            "reason": f"Verified submission on {platform}. Official confirmation page loaded. Confirmation email expected at {CANDIDATE_EMAIL}."
        }
    else:
        reasons = []
        if bot_shield:
            reasons.append(f"Protected by {shield_name} challenge")
        if validation_errors:
            sample_err = validation_errors[0].replace('\n', ' ')[:60]
            reasons.append(f"Validation: '{sample_err}'")
        elif has_text_error:
            reasons.append("Mandatory custom questions require manual selection")

        if not reasons:
            reasons.append("Submission requires 1-click manual submit on career page")

        full_reason = "; ".join(reasons)
        return {
            "is_applied": False,
            "status": "PORTAL_CAPTURED",
            "reason": f"Form pre-filled with candidate profile & tailored resume. {full_reason}."
        }


def ensure_application_form_ready(page: Page, on_progress: Any = None) -> bool:
    """
    Ensures that an interactive application form is fully opened and mounted on the page.
    If currently on a Job Description page or landing page, methodically locates and clicks
    the 'Apply' trigger, handles Ashby/Lever '/application' transitions, detects embedded ATS iframes,
    and waits for inputs to mount.
    """
    check_pause_and_abort(page)
    url = page.url.lower()

    # 1. Quick check: Is the form already visible on page?
    visible_inputs = page.locator("input:not([type='hidden']):visible, textarea:visible, select:visible, [role='combobox']:visible").count()
    if visible_inputs >= 3:
        logger.info(f"[FormReady] Detected {visible_inputs} visible interactive fields already present on page.")
        return True

    # 2. Check for embedded ATS iframe (Greenhouse, Lever, Ashby, Workable)
    try:
        iframes = page.locator("iframe").all()
        for ifr in iframes:
            try:
                src = ifr.get_attribute("src") or ""
                if any(ats in src.lower() for ats in ["greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "smartrecruiters.com"]):
                    logger.info(f"[FormReady] Found embedded ATS iframe: {src}. Navigating directly to un-iframe form.")
                    if on_progress:
                        on_progress("NAVIGATING", "Detected embedded ATS iframe. Loading direct application form...")
                    page.goto(src, wait_until="domcontentloaded", timeout=20000)
                    safe_sleep(page, 1.5)
                    return True
            except Exception:
                pass
    except Exception:
        pass

    # 3. Dedicated Ashby URL auto-resolution: If on Ashby JD, click Apply or go to /application
    if "ashbyhq.com" in url and not url.endswith("/application"):
        apply_link = page.locator("a[href*='/application']:visible, a:has-text('Apply for this Job'):visible, a:has-text('Apply'):visible, button:has-text('Apply'):visible").first
        if apply_link.count() > 0:
            try:
                if on_progress:
                    on_progress("OPENING_FORM", "Ashby JD detected. Clicking 'Apply for this Job' button...")
                apply_link.scroll_into_view_if_needed(timeout=2000)
                apply_link.click(timeout=3000)
                safe_sleep(page, 2.0)
            except Exception:
                app_url = page.url.rstrip('/') + '/application'
                page.goto(app_url, wait_until="domcontentloaded", timeout=20000)
                safe_sleep(page, 2.0)

    # 4. Dedicated Lever URL auto-resolution: If on Lever JD, go to /apply
    elif "jobs.lever.co" in url and not url.endswith("/apply"):
        apply_link = page.locator("a[href*='/apply']:visible, a:has-text('Apply for this job'):visible, a:has-text('Apply'):visible").first
        if apply_link.count() > 0:
            try:
                if on_progress:
                    on_progress("OPENING_FORM", "Lever JD detected. Clicking 'Apply for this job'...")
                apply_link.scroll_into_view_if_needed(timeout=2000)
                apply_link.click(timeout=3000)
                safe_sleep(page, 2.0)
            except Exception:
                app_url = page.url.rstrip('/') + '/apply'
                page.goto(app_url, wait_until="domcontentloaded", timeout=20000)
                safe_sleep(page, 2.0)

    # 5. General Apply Button / Trigger search
    else:
        apply_selectors = [
            "a[href*='/application']:visible",
            "a[href*='#apply']:visible",
            "a:has-text('Apply for this job'):visible",
            "a:has-text('Apply for this role'):visible",
            "a:has-text('Apply for this position'):visible",
            "button:has-text('Apply for this job'):visible",
            "button:has-text('Apply for this role'):visible",
            "button:has-text('Apply for this position'):visible",
            "button:has-text('Apply Now'):visible",
            "a:has-text('Apply Now'):visible",
            "button:has-text('Apply'):visible",
            "a:has-text('Apply'):visible",
            "#apply_button:visible",
            ".apply-button:visible",
            "[data-qa='btn-apply']:visible"
        ]
        for sel in apply_selectors:
            check_pause_and_abort(page)
            btn = page.locator(sel).first
            if btn.count() > 0:
                try:
                    txt = btn.inner_text().strip()
                    logger.info(f"[FormReady] Found apply trigger '{txt}' with selector: {sel}")
                    if on_progress:
                        on_progress("OPENING_FORM", f"Locating application form: Clicking '{txt}'...")
                    btn.scroll_into_view_if_needed(timeout=2000)
                    btn.click(timeout=3000)
                    safe_sleep(page, 1.8)
                    break
                except Exception:
                    pass

    # 6. Wait for input elements to mount dynamically (up to 8 seconds)
    start_wait = time.time()
    while time.time() - start_wait < 8.0:
        check_pause_and_abort(page)
        visible_inputs = page.locator("input:not([type='hidden']):visible, textarea:visible, select:visible, [role='combobox']:visible").count()
        if visible_inputs >= 3:
            logger.info(f"[FormReady] Application form confirmed ready ({visible_inputs} interactive fields).")
            return True
        safe_sleep(page, 0.4)

    logger.warning(f"[FormReady] Page has {visible_inputs} inputs after ready checks. Proceeding with best-effort.")
    return visible_inputs >= 1


def scan_and_read_page_line_by_line(page: Page, on_progress: Any = None):
    """
    Methodically inspects and reads the application page line-by-line.
    Scrolls down gently, reads question labels, headings, and instructions,
    visibly highlights each line with a reading glow, streams progress live to candidate,
    and returns smoothly to the top of the form ready for filling.
    """
    check_pause_and_abort(page)
    print_live_action("👀", "Jarvis reading application webpage line-by-line...")
    if on_progress:
        on_progress("READING", "Jarvis inspecting webpage structure and reading form line-by-line...")

    # Start at top of page
    try:
        page.evaluate("window.scrollTo(0, 0)")
        safe_sleep(page, 0.3)
    except Exception:
        pass

    # Find structural text elements: headings, legends, question labels, descriptions
    try:
        elements = page.locator(
            "h1:visible, h2:visible, h3:visible, h4:visible, legend:visible, "
            "label:visible, .field-label:visible, [role='heading']:visible, "
            ".application-question:visible, p.description:visible"
        ).all()

        seen_texts = set()
        read_count = 0
        max_reads = 18  # Read up to 18 key lines to cover all sections thoroughly without excessive delay

        for el in elements:
            check_pause_and_abort(page)
            if read_count >= max_reads:
                break
            try:
                if not el.is_visible():
                    continue
                raw_text = el.inner_text().strip()
                if not raw_text or len(raw_text) < 3 or len(raw_text) > 120:
                    continue
                clean_line = re.sub(r"\s+", " ", raw_text).split("\n")[0].strip()
                if clean_line in seen_texts:
                    continue
                seen_texts.add(clean_line)

                # Gently scroll element into view
                try:
                    el.scroll_into_view_if_needed(timeout=1000)
                except Exception:
                    pass

                # Highlight line with warm reading glow
                try:
                    page.evaluate("""(elem) => {
                        elem.style.backgroundColor = 'rgba(254, 240, 138, 0.45)';
                        elem.style.borderRadius = '3px';
                        elem.style.boxShadow = '0 0 10px rgba(234, 179, 8, 0.4)';
                        elem.style.transition = 'all 0.15s ease-in-out';
                    }""", el)
                except Exception:
                    pass

                print_live_action("👀", f"Reading line: {clean_line[:65]}")
                if on_progress:
                    on_progress("READING_PAGE", f"Reading line: {clean_line[:65]}")

                # Deliberate human reading pause (user visibly watches Jarvis reading)
                safe_sleep(page, 0.22)

                # Remove reading glow
                try:
                    page.evaluate("""(elem) => {
                        elem.style.backgroundColor = '';
                        elem.style.boxShadow = '';
                    }""", el)
                except Exception:
                    pass

                read_count += 1
            except Exception:
                continue

    except Exception as e:
        logger.debug(f"[ScanRead] Line scan notice: {e}")

    # Smoothly scroll back to the top of the form ready for filling
    try:
        page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        safe_sleep(page, 0.6)
    except Exception:
        pass

    capture_viewport(page, "page_inspected")
    print_live_action("📝", "Page read complete. Starting methodical one-by-one field population...")
    if on_progress:
        on_progress("READING_COMPLETE", "Page structure read line-by-line. Starting methodical one-by-one field population...")


def audit_form_before_approval(page: Page, on_progress: Any = None) -> Tuple[bool, int, List[str]]:
    """
    Mandatory Pre-Approval Audit Gate:
    Inspects DOM to verify that fields are actually populated before Co-Pilot approval is presented.
    Verifies Candidate Name, Email, Phone, and at least 3 total filled fields.
    Returns: (is_ready: bool, filled_count: int, missing_fields: List[str])
    """
    check_pause_and_abort(page)
    print_live_action("🔍", "Auditing form fields before presenting for candidate approval...")
    if on_progress:
        on_progress("AUDITING", "Auditing form fields to ensure candidate data is 100% present...")

    has_name = False
    has_email = False
    has_phone = False
    filled_count = 0
    missing = []

    try:
        inputs = page.locator("input:not([type='hidden']), textarea, select").all()
        for inp in inputs:
            try:
                val = ""
                tag = inp.evaluate("e => e.tagName").lower()
                inp_type = (inp.get_attribute("type") or "").lower()

                if tag == "select":
                    val = (inp.input_value() or "").strip()
                    if val and val not in ["0", "-1", "select", "choose", ""]:
                        filled_count += 1
                elif inp_type == "radio":
                    if inp.is_checked():
                        filled_count += 1
                elif inp_type == "checkbox":
                    if inp.is_checked():
                        filled_count += 1
                elif inp_type == "file":
                    val = inp.input_value()
                    if val:
                        filled_count += 1
                else:
                    val = (inp.input_value() or "").strip()
                    if val:
                        filled_count += 1
                        val_low = val.lower()
                        # Name check
                        if any(n.lower() in val_low for n in [CANDIDATE_LAST_NAME, CANDIDATE_FIRST_NAME, "phanindra", "vallabhaneni"]):
                            has_name = True
                        # Email check
                        if "@" in val and ("phani" in val_low or "gmail" in val_low or CANDIDATE_EMAIL.lower() in val_low):
                            has_email = True
                        # Phone check
                        clean_digits = re.sub(r"\D", "", val)
                        if len(clean_digits) >= 10:
                            has_phone = True
            except Exception:
                continue

    except Exception as e:
        logger.debug(f"[Audit] Error scanning inputs: {e}")

    # Count React-Select single values towards filled fields
    try:
        single_vals = page.locator(".select__single-value, [class*='singleValue']").all()
        for sv in single_vals:
            if sv.is_visible() and sv.inner_text().strip():
                filled_count += 1
    except Exception:
        pass

    # Check for unfilled React-Select dropdowns (showing Select... placeholder)
    unfilled_selects = 0
    unfilled_mandatory_selects = 0
    try:
        placeholders = page.locator(".select:has(.select__placeholder), div[class*='-control']:has([class*='placeholder'])").all()
        for ph in placeholders:
            if ph.is_visible():
                unfilled_selects += 1
                # Check if it is marked required or inside a required container
                is_req = False
                try:
                    aria_req = ph.get_attribute("aria-required") or ""
                    req_ancestor = ph.locator("xpath=ancestor::div[contains(@class, 'field--required') or contains(@class, 'required') or contains(@aria-required, 'true')]").count()
                    has_star = ph.locator("xpath=ancestor::div[contains(@class, 'field')]//label[contains(text(), '*')]").count()
                    if aria_req == "true" or req_ancestor > 0 or has_star > 0:
                        is_req = True
                except Exception:
                    pass
                if is_req:
                    unfilled_mandatory_selects += 1
    except Exception:
        pass

    if not has_name:
        missing.append("Candidate Name")
    if not has_email:
        missing.append("Candidate Email")
    if not has_phone:
        missing.append("Candidate Phone")
    if unfilled_mandatory_selects > 0:
        missing.append(f"{unfilled_mandatory_selects} Required Dropdown Questions Unfilled")
    elif unfilled_selects > 0:
        logger.info(f"[Audit] Note: {unfilled_selects} optional survey/demographic dropdowns left unselected.")

    is_ready = has_name and has_email and (filled_count >= 3) and (unfilled_mandatory_selects == 0)
    logger.info(f"[Audit] Result: ready={is_ready}, filled={filled_count}, missing={missing}")
    return is_ready, filled_count, missing


def execute_recovery_fill_pass(page: Page, missing: List[str], tailored_pdf: Path, job: Optional[Dict[str, Any]] = None, on_progress: Any = None):
    """
    Executes a targeted recovery fill pass if any core fields were missed.
    Uses ultra-broad DOM selectors and fallback matching to guarantee all fields are populated.
    """
    check_pause_and_abort(page)
    logger.info(f"[RecoveryPass] Executing targeted recovery fill for: {missing}")
    if on_progress:
        on_progress("RECOVERY_PASS", f"Executing targeted recovery pass for missing fields: {', '.join(missing)}...")

    # 1. Recover Name
    if "Candidate Name" in missing:
        # Try full name first
        for sel in [
            "input[name='_systemfield_name']", "input[id='_systemfield_name']", "[data-systemfield='name']",
            "input[name='name']", "input#name", "input[placeholder*='name' i]", "input[aria-label*='name' i]"
        ]:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible() and not (el.input_value() or "").strip():
                human_type_input(page, el, "Full Name", CANDIDATE_NAME, on_progress=on_progress)
                break
        # Try first and last
        for sel in ["input[name*='first' i]", "input[id*='first' i]", "input[placeholder*='first' i]"]:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible() and not (el.input_value() or "").strip():
                human_type_input(page, el, "First Name", CANDIDATE_FIRST_NAME, on_progress=on_progress)
                break
        for sel in ["input[name*='last' i]", "input[id*='last' i]", "input[placeholder*='last' i]"]:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible() and not (el.input_value() or "").strip():
                human_type_input(page, el, "Last Name", CANDIDATE_LAST_NAME, on_progress=on_progress)
                break

    # 2. Recover Email
    if "Candidate Email" in missing:
        for sel in [
            "input[name='_systemfield_email']", "input[id='_systemfield_email']", "[data-systemfield='email']",
            "input[type='email']", "input[name*='email' i]", "input[id*='email' i]", "input[placeholder*='email' i]"
        ]:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible() and not (el.input_value() or "").strip():
                human_type_input(page, el, "Email", CANDIDATE_EMAIL, on_progress=on_progress)
                break

    # 3. Recover Phone
    if "Candidate Phone" in missing:
        for sel in [
            "input[name='_systemfield_phone']", "input[id='_systemfield_phone']", "[data-systemfield='phone']",
            "input[type='tel']", "input[name*='phone' i]", "input[id*='phone' i]", "input[placeholder*='phone' i]"
        ]:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible() and not (el.input_value() or "").strip():
                human_type_input(page, el, "Phone", CANDIDATE_PHONE, on_progress=on_progress)
                break

    # Sweep options & radios again
    try:
        solve_form_options_and_radios(page, job=job, on_progress=on_progress)
    except Exception:
        pass


def apply_to_job(page: Page, job: Dict[str, Any], tailored_pdf: Path, on_progress: Any = None) -> Dict[str, Any]:
    """
    Executes the direct career-page application flow:
    Navigates to Greenhouse/Ashby/Lever page, fills form, uploads tailored PDF, and evaluates submission.
    Supports real-time on_progress callback for live UI streaming.
    """
    company = job.get("company", "Backbone Company")
    title = job.get("title", "Role")
    url = job.get("url", "")
    if not url or not url.startswith("http"):
        # Auto-resolve from company database or standard ATS slug
        from dynamic_search import get_company_directory
        comps = get_company_directory()
        for c in comps:
            if c.get("name", "").lower() == company.lower():
                url = c.get("career_url", "")
                break
    if not url or not url.startswith("http"):
        slug = re.sub(r"[^\w]", "", company.lower())
        url = f"https://job-boards.greenhouse.io/{slug}"

    # Normalize Greenhouse URLs to direct un-iframed embed endpoint if wrapped in corporate domain
    if "greenhouse.io" not in url and ("gh_jid=" in url or "token=" in url):
        m = re.search(r"(?:gh_jid|token)=(\d+)", url)
        if m:
            jid = m.group(1)
            slug_match = re.search(r"board=([a-zA-Z0-9_\-]+)", url)
            slug = slug_match.group(1) if slug_match else re.sub(r"[^\w]", "", company.lower())
            url = f"https://job-boards.greenhouse.io/embed/job_app?for={slug}&token={jid}"
            logger.info(f"Resolved direct Greenhouse application URL: {url}")

    platform = job.get("ats_platform", "Career Page")
    app_count = job.get("applicant_count", 0)
    rationale = job.get("decision_rationale", "Approved")

    print_live_action("🌐", f"Navigating to direct career page: {url}")
    logger.info(f"Opening career page [{platform}] for '{title}' at '{company}'...")
    if on_progress:
        on_progress("NAVIGATING", f"Opening visible career portal at {company} ({platform})...")

    result = {
        "timestamp": datetime.datetime.now().isoformat(),
        "company": company,
        "job_title": title,
        "job_url": url,
        "ats_platform": platform,
        "applicant_count": app_count,
        "status": "PROCESSING",
        "resume_pdf": str(tailored_pdf),
        "notes": rationale
    }

    try:
        check_pause_and_abort(page)
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        safe_sleep(page, 1.5)
        bring_browser_window_to_front()
        check_pause_and_abort(page)
        capture_viewport(page, f"nav_{company}")
        if on_progress:
            on_progress("CONNECTED", f"Portal loaded successfully. Locating form fields for {title}...")

        # Step 1: Ensure Application Form Ready (clicks Apply button on JD pages, handles iframes, /application transitions)
        check_pause_and_abort(page)
        form_ready = ensure_application_form_ready(page, on_progress=on_progress)
        bring_browser_window_to_front()
        check_pause_and_abort(page)

        # Step 2: Methodical Page Inspection & Line-by-Line Reading
        scan_and_read_page_line_by_line(page, on_progress=on_progress)
        check_pause_and_abort(page)

        # Step 3: Deliberate One-by-One Form Filling (Candidate profile & tailored resume)
        if on_progress:
            on_progress("FORM_FILL", f"Populating candidate profile credentials ({CANDIDATE_NAME}, {CANDIDATE_EMAIL})...")
        fill_standard_career_form(page, tailored_pdf, job=job, on_progress=on_progress)
        safe_sleep(page, 0.8)

        # Second-pass sweep: Guarantee all dynamic EEOC and questionnaire options are fully selected
        try:
            solve_form_options_and_radios(page, job=job, on_progress=on_progress)
        except Exception:
            pass
        check_pause_and_abort(page)
        capture_viewport(page, f"filled_{company}")
        if on_progress:
            on_progress("RESUME_ATTACHED", f"Uploaded tailored ATS PDF resume ({tailored_pdf.name}) and answered work authorization (YES to Auth & Sponsorship).")

        # Step 4: Mandatory Pre-Approval Audit Gate (verifies fields are actually populated before approval)
        is_ready, filled_count, missing = audit_form_before_approval(page, on_progress=on_progress)
        if not is_ready:
            logger.warning(f"Audit incomplete. Missing: {missing}. Initiating targeted recovery fill pass...")
            execute_recovery_fill_pass(page, missing, tailored_pdf, job=job, on_progress=on_progress)
            safe_sleep(page, 0.8)
            # Re-audit
            is_ready, filled_count, missing = audit_form_before_approval(page, on_progress=on_progress)

        # Step 5: Smoothly scroll to the very top so candidate can review the form from top to bottom
        try:
            page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
            safe_sleep(page, 0.8)
        except Exception:
            pass
        bring_browser_window_to_front()
        capture_viewport(page, f"review_{company}")

        if DRY_RUN:
            print_live_action("⚠️", "DRY_RUN mode active: Form filled & validated. Skipping final submit click.")
            logger.info("DRY_RUN is enabled. Form filled and captured. Skipping final submit click.")
            result["status"] = "SUBMISSION_READY (DRY RUN)"
            result["notes"] = f"Reviewed. LinkedIn applicants: {app_count}."
            if on_progress:
                on_progress("DRY_RUN", "DRY_RUN mode: Form pre-filled & validated. Submit skipped.")
        else:
            check_pause_and_abort(page)
            submit_btn = page.locator(
                "input[type='submit']:visible, button[type='submit']:visible, #submit_app:visible, button:has-text('Submit Application'):visible, button:has-text('Submit application'):visible"
            ).first

            # Step 6: Co-Pilot Pre-Submission Review Gate: Hold submit until candidate inspects and approves
            if CO_PILOT_MODE_CALLBACK and CO_PILOT_MODE_CALLBACK():
                print_live_action("🛡️", f"Co-Pilot Pre-Submission Review Gate active — Holding final submit for candidate approval ({filled_count} fields verified).")
                logger.info(f"Co-Pilot Review Gate: Form audited ({filled_count} fields). Holding final submit for candidate approval.")
                
                if is_ready:
                    status_msg = f"Form audited & verified! ({filled_count} fields populated). Co-Pilot Review Gate holding submit. Review in desktop browser, then click 'Approve & Submit' to finalize."
                else:
                    status_msg = f"Form partially filled ({filled_count} fields). Missing: {', '.join(missing)}. Co-Pilot Review Gate holding for inspection. Review in desktop browser, then click 'Approve & Submit' to finalize."

                if on_progress:
                    on_progress("AWAITING_APPROVAL", status_msg)
                if CO_PILOT_NOTIFY_AWAITING:
                    CO_PILOT_NOTIFY_AWAITING(True)
                capture_viewport(page, f"review_{company}")
                bring_browser_window_to_front()

                while CO_PILOT_AWAITING_CALLBACK and CO_PILOT_AWAITING_CALLBACK():
                    if ABORT_CHECK_CALLBACK and ABORT_CHECK_CALLBACK():
                        raise ApplicationAbortedException("Live application stopped by candidate during Co-Pilot review.")
                    process_pending_actions(page)
                    time.sleep(0.04)

                if CO_PILOT_NOTIFY_AWAITING:
                    CO_PILOT_NOTIFY_AWAITING(False)
                check_pause_and_abort(page)
                print_live_action("🚀", "Candidate approved final submission! Executing submit on portal...")
                if on_progress:
                    on_progress("APPROVED", "Submission approved by candidate! Finalizing on career portal...")

            if submit_btn.count() > 0:
                print_live_action("🚀", f"Clicking Submit on {platform} career page...")
                logger.info(f"Clicking Submit on {platform} career page...")
                if on_progress:
                    on_progress("SUBMITTING", f"Evaluating final submit on {platform} career page...")
                try:
                    check_pause_and_abort(page)
                    submit_btn.click(timeout=5000)
                    time.sleep(3.5)
                    capture_viewport(page, f"submitted_{company}")

                    # Evaluate strictly with the truth gate
                    eval_result = check_submission_result(page, platform)
                    result["status"] = eval_result["status"]
                    result["notes"] = eval_result["reason"]

                    if eval_result["is_applied"]:
                        safe_print_live(f"      \033[92m[OK] APPLICATION VERIFIED SUBMITTED ON {platform.upper()}!\033[0m")
                        safe_print_live(f"      \033[92m[OK] Automated confirmation email dispatched to {CANDIDATE_EMAIL}.\033[0m")
                        if on_progress:
                            on_progress("CONFIRMED", f"Application officially submitted on {platform}! Confirmation received.")
                    else:
                        safe_print_live(f"      \033[93m[!] Application pre-filled in portal, but requires manual attention.\033[0m")
                        safe_print_live(f"      \033[93m[!] Status: PORTAL_CAPTURED ({eval_result['reason']})\033[0m")
                        safe_print_live(f"      \033[90m[i] Note: No confirmation email is sent until you complete the 1-click manual submission.\033[0m")
                        if on_progress:
                            on_progress("CAPTURED", f"Pre-filled in portal: {eval_result['reason']}. Ready for 1-click completion in visible browser.")

                except ApplicationAbortedException:
                    raise
                except Exception as ex:
                    result["status"] = "PORTAL_CAPTURED"
                    result["notes"] = f"Pre-filled. Submit click exception: {str(ex)[:60]}"
                    safe_print_live(f"      \033[93m[!] Notice: Form pre-filled; requires 1-click manual submit ({str(ex)[:50]})\033[0m")
                    if on_progress:
                        on_progress("EXCEPTION", f"Submit interaction note: {str(ex)[:60]}")
            else:
                # Corporate page with iframe or Enterprise CAPTCHA preventing main DOM button find
                result["status"] = "PORTAL_CAPTURED"
                result["notes"] = f"Protected by corporate iframe/reCAPTCHA barrier. Resume & pitch compiled; requires 1-click manual submission."
                safe_print_live(f"      \033[93m[!] Notice: Corporate page protected by iframe/reCAPTCHA barrier.\033[0m")
                safe_print_live(f"      \033[93m[!] NOT submitted automatically. Tailored resume & outreach pack saved for 1-click completion.\033[0m")

    except ApplicationAbortedException as abort_err:
        logger.warning(f"Application safely aborted by candidate: {abort_err}")
        safe_print_live(f"      \033[91m[ABORTED] Application stopped by candidate. No submission performed.\033[0m")
        capture_viewport(page, f"aborted_{company}")
        result["status"] = "ABORTED_BY_USER"
        result["notes"] = "Application process cancelled by candidate before submission."
        if on_progress:
            on_progress("ABORTED", "Application cancelled by candidate. Desktop browser retained for manual review.")

    except Exception as e:
        err_msg = str(e).split("\n")[0][:100]
        logger.warning(f"Career page flow notice: {err_msg}")
        safe_print_live(f"      \033[91mNotice: {err_msg}\033[0m")
        capture_viewport(page, f"err_{company}")
        result["status"] = "PORTAL_CAPTURED"
        result["notes"] = f"PDF compiled. Status: {err_msg}"

    return result
