import argparse
import io
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dynamic_search import dynamic_search_career_pages
from applicant import apply_to_job
from tailor import tailor_resume
from pdf_generator import generate_tailored_pdf
from dashboard import log_applied_job
from playwright.sync_api import sync_playwright

# ANSI Color Codes
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_CYAN = "\033[96m"
C_YELLOW = "\033[93m"
C_GREEN = "\033[92m"
C_BLUE = "\033[94m"
C_MAGENTA = "\033[95m"
C_WHITE = "\033[97m"
C_GRAY = "\033[90m"


def print_banner():
    print(f"\n{C_CYAN}{'=' * 95}{C_RESET}")
    print(f"{C_BOLD}{C_WHITE}  [!] JARVIS DYNAMIC CAREER PAGE HUNTER (GEMINI-STYLE NLP DISCOVERY){C_RESET}")
    print(f"  {C_GRAY}Type ANY natural language query to dynamically discover official career portals & 2-3 yr CS roles.{C_RESET}")
    print(f"  {C_GRAY}Examples:{C_RESET} {C_YELLOW}'fintech AI startups hiring backend python'{C_RESET} | {C_YELLOW}'autonomous robotics data engineers'{C_RESET}")
    print(f"  {C_GRAY}Commands:{C_RESET} {C_GREEN}apply <#>{C_RESET} (autonomous submit in GUI) | {C_GREEN}open <#>{C_RESET} (open link) | {C_GREEN}exit{C_RESET}")
    print(f"{C_CYAN}{'=' * 95}{C_RESET}\n")


def display_results(results: List[Dict[str, Any]]):
    if not results:
        print(f"{C_YELLOW}[!] No matching 2-3 yr Computer Science roles identified for this query.{C_RESET}\n")
        return

    print(f"\n{C_BOLD}{C_GREEN}Found {len(results)} Matching 2-3 Year US CS Opportunities:{C_RESET}\n")
    print(f"{C_GRAY}{'-' * 95}{C_RESET}")
    for idx, r in enumerate(results, start=1):
        score_color = C_GREEN if r['fit_score'] >= 90 else C_YELLOW
        print(f"{C_BOLD}[{idx}] {r['company']}{C_RESET} ({C_CYAN}{r['ats_platform']}{C_RESET}) | {score_color}Match Score: {r['fit_score']}/100{C_RESET}")
        print(f"    {C_WHITE}Role:{C_RESET} {C_BOLD}{r['title']}{C_RESET}")
        print(f"    {C_GRAY}Location:{C_RESET} {r['location']}")
        print(f"    {C_GRAY}Career Portal:{C_RESET} {C_CYAN}{r['career_url']}{C_RESET}")
        print(f"    {C_GRAY}Direct Application:{C_RESET} {C_BLUE}{r['apply_url']}{C_RESET}\n")
    print(f"{C_GRAY}{'-' * 95}{C_RESET}\n")


def apply_to_discovered_role(role: Dict[str, Any]):
    print(f"\n{C_BOLD}{C_MAGENTA}[*] Launching visible Chromium automation for {role['company']} - {role['title']}...{C_RESET}\n")
    
    # 1. Compile Tailored ATS PDF
    print(f"|  {C_CYAN}[>] Tailoring resume and compiling high-contrast ATS letter PDF for {role['company']}...{C_RESET}")
    tailored_data = tailor_resume(role["title"], role["company"], role["description"])
    pdf_path = generate_tailored_pdf(tailored_data, role["company"], role["title"])
    print(f"|  {C_GREEN}[OK] Tailored Resume PDF saved: {pdf_path.name}{C_RESET}")

    # 2. Launch Visible Chromium Window
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=80,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"]
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1.5
        )
        page = context.new_page()
        
        # Apply
        app_result = apply_to_job(page, role, pdf_path)
        log_applied_job(app_result)
        
        status = app_result.get("status", "PORTAL_CAPTURED")
        if status == "APPLIED":
            print(f"\n{C_BOLD}{C_GREEN}🎉 Successfully submitted application to {role['company']}!{C_RESET}")
        else:
            print(f"\n{C_BOLD}{C_YELLOW}[!] Status: {status} &bull; Form populated & resume attached in visible browser.{C_RESET}")
            
        print(f"Leaving browser open for 15s for your visual inspection...")
        time.sleep(15)
        browser.close()


def interactive_loop():
    print_banner()
    last_results = []
    
    while True:
        try:
            user_input = input(f"{C_BOLD}{C_CYAN}Jarvis-Hunter>{C_RESET} ").strip()
            if not user_input:
                continue
                
            cmd = user_input.lower()
            if cmd in ("exit", "quit", "q"):
                print("Exiting Jarvis Career Page Hunter. Goodbye!")
                break
                
            if cmd.startswith("apply "):
                parts = cmd.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    idx = int(parts[1]) - 1
                    if 0 <= idx < len(last_results):
                        apply_to_discovered_role(last_results[idx])
                    else:
                        print(f"{C_RED}[!] Invalid index. Choose 1 to {len(last_results)}.{C_RESET}")
                else:
                    print(f"{C_RED}[!] Usage: apply <number>{C_RESET}")
                continue

            if cmd.startswith("open "):
                parts = cmd.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    idx = int(parts[1]) - 1
                    if 0 <= idx < len(last_results):
                        import webbrowser
                        url = last_results[idx]["career_url"]
                        print(f"Opening {url}...")
                        webbrowser.open(url)
                    else:
                        print(f"{C_RED}[!] Invalid index.{C_RESET}")
                continue

            # Natural Language Search Query
            print(f"\n{C_GRAY}[>] Processing query with Gemini-style NLP engine: '{user_input}'...{C_RESET}")
            search_data = dynamic_search_career_pages(user_input, max_results=6)
            last_results = search_data["roles"]
            display_results(last_results)
            
            if last_results:
                print(f"{C_GRAY}Tip: Type {C_GREEN}'apply 1'{C_GRAY} to launch visible browser application for #1.{C_RESET}\n")

        except (KeyboardInterrupt, EOFError):
            print("\nExiting. Goodbye!")
            break
        except Exception as e:
            print(f"{C_RED}[!] Error: {e}{C_RESET}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis Dynamic Gemini-Style Career Page Hunter")
    parser.add_argument("query", nargs="?", default="", help="Natural language search query")
    parser.add_argument("--apply", type=int, default=0, help="Automatically apply to result index (1-based)")
    args = parser.parse_args()

    if args.query:
        print_banner()
        print(f"{C_GRAY}[>] Searching for: '{args.query}'...{C_RESET}")
        res = dynamic_search_career_pages(args.query, max_results=6)
        roles = res["roles"]
        display_results(roles)
        if args.apply and 1 <= args.apply <= len(roles):
            apply_to_discovered_role(roles[args.apply - 1])
    else:
        interactive_loop()
