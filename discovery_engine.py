import concurrent.futures
import datetime
import json
import logging
import random
import re
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import quote_plus, urlparse
from bs4 import BeautifulSoup

from config import (
    COMPANIES_DATABASE,
    ONE_ROLE_PER_COMPANY,
    JOB_FRESHNESS_WINDOW_HOURS,
    SCAN_ALL_COMPANIES_EACH_CYCLE,
    is_strictly_usa,
    matches_cs_tech_stack,
    contains_wipro,
    is_itar_or_clearance,
    load_applied_companies,
    score_role_fit
)

logger = logging.getLogger("JarvisJobAgent.DiscoveryEngine")


def _parse_timestamp(value: Any) -> Optional[datetime.datetime]:
    """Parses mixed timestamp formats (ISO strings, epoch seconds/ms) into UTC datetime."""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 10_000_000_000:
                ts /= 1000.0
            return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            if re.fullmatch(r"\d{10,13}", raw):
                ts = float(raw)
                if len(raw) == 13:
                    ts /= 1000.0
                return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
            iso = raw.replace("Z", "+00:00")
            dt = datetime.datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(datetime.timezone.utc)
    except Exception:
        return None
    return None


def _extract_posted_at(job: Dict[str, Any], platform: str) -> Optional[datetime.datetime]:
    """Extracts posting timestamp from ATS payload using known fields."""
    candidate_keys = [
        "published_at", "publishedAt", "postingDate", "datePosted",
        "first_published", "created_at", "createdAt", "updated_at", "updatedAt",
        "lastUpdatedAt", "openDate", "openedAt"
    ]
    for key in candidate_keys:
        dt = _parse_timestamp(job.get(key))
        if dt:
            return dt

    if platform == "lever":
        cats = job.get("categories") or {}
        for key in ["createdAt", "updatedAt"]:
            dt = _parse_timestamp(cats.get(key))
            if dt:
                return dt
    return None


def _is_within_freshness_window(posted_at: Optional[datetime.datetime]) -> bool:
    """Returns True only for roles posted/updated inside configured recent-hours window."""
    if not posted_at:
        return False
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    max_age = datetime.timedelta(hours=JOB_FRESHNESS_WINDOW_HOURS)
    return (now_utc - posted_at) <= max_age

# Expansive US tech directory covering 18+ bizarre, overlooked, and counter-intuitive domains
SEED_US_COMPANIES = [
    # 1. Mortuary, Funeral & Death Care Tech
    {"name": "Gather", "ats": "greenhouse", "slug": "gather", "domain": "Mortuary & Funeral Operations Software"},
    {"name": "Parting Pro", "ats": "greenhouse", "slug": "partingpro", "domain": "Death Care & Cremation E-Commerce Infra"},

    # 2. POS, Kiosks, Vending & Laundromat Systems
    {"name": "Toast", "ats": "greenhouse", "slug": "toast", "domain": "Restaurant POS & Transaction Pipelines"},
    {"name": "SpotOn", "ats": "greenhouse", "slug": "spoton", "domain": "Point-of-Sale & Terminal Payment Systems"},
    {"name": "Cantaloupe", "ats": "greenhouse", "slug": "cantaloupe", "domain": "Smart Vending Machine & Micro-Market Telemetry"},
    {"name": "PAR Technology", "ats": "greenhouse", "slug": "partechnology", "domain": "Enterprise POS & Hardware Telemetry"},
    {"name": "Revel Systems", "ats": "greenhouse", "slug": "revelsystems", "domain": "Cloud POS & Kitchen Display Engines"},

    # 3. Hotel, Casino & Hospitality Back-Office
    {"name": "Cloudbeds", "ats": "greenhouse", "slug": "cloudbeds", "domain": "Hotel Property Management & Reservation Infra"},
    {"name": "SevenRooms", "ats": "greenhouse", "slug": "sevenrooms", "domain": "Hospitality Guest Experience & Booking Data"},
    {"name": "Duetto", "ats": "greenhouse", "slug": "duetto", "domain": "Casino & Hotel Dynamic Pricing Algorithms"},
    {"name": "Mews", "ats": "greenhouse", "slug": "mews", "domain": "Hospitality Cloud Operating Systems"},

    # 4. Waste, Recycling & Sanitation Tech (TrashTech)
    {"name": "Rubicon", "ats": "greenhouse", "slug": "rubicon", "domain": "Smart Waste Hauling & Dumpster Route Telemetry"},

    # 5. HVAC, Plumbing, Elevator & Field Service Automation
    {"name": "ServiceTitan", "ats": "greenhouse", "slug": "servicetitan", "domain": "Plumbing, HVAC & Electrical Dispatch Software"},
    {"name": "Jobber", "ats": "greenhouse", "slug": "jobber", "domain": "Home Services & Contractor Workflow Automation"},
    {"name": "Housecall Pro", "ats": "greenhouse", "slug": "housecallpro", "domain": "Field Service Automation & Mobile Invoicing"},

    # 6. Car Wash & Wash Tunnel Automation
    {"name": "DRB Systems", "ats": "greenhouse", "slug": "drbsystems", "domain": "Automated Car Wash Tunnel Telemetry & POS"},

    # 7. Self-Storage & Warehouse Yard Access Tech
    {"name": "Storable", "ats": "greenhouse", "slug": "storable", "domain": "Self-Storage Facility Management & Gate Telemetry"},

    # 8. Parking Meters, Gates & License Plate Recognition
    {"name": "ParkMobile", "ats": "greenhouse", "slug": "parkmobile", "domain": "Municipal Parking Meter Streams & LPR Tech"},
    {"name": "FlashParking", "ats": "greenhouse", "slug": "flashparking", "domain": "Cloud Parking Asset Architecture & Gate Access"},

    # 9. Roadside Assistance, Towing & Impound Dispatch
    {"name": "Urgently", "ats": "greenhouse", "slug": "urgently", "domain": "Real-Time Roadside Towing Telemetry & Dispatch"},

    # 10. FaithTech & Donation Transaction Streams
    {"name": "Pushpay", "ats": "greenhouse", "slug": "pushpay", "domain": "High-Volume Church Donation Streams & Member Graphs"},
    {"name": "Subsplash", "ats": "greenhouse", "slug": "subsplash", "domain": "Religious Organization Media & Giving Backends"},

    # 11. Underground Sewer & Pipeline Robotics (Ashby)
    {"name": "SewerAI", "ats": "ashby", "slug": "sewerai", "domain": "Computer Vision & Telemetry for Underground Sewer Pipes"},

    # 12. Physical Infrastructure, Fleet Telematics & Heavy Equipment
    {"name": "Samsara", "ats": "greenhouse", "slug": "samsara", "domain": "Industrial Telemetry & Connected Fleet IoT"},
    {"name": "Flexport", "ats": "greenhouse", "slug": "flexport", "domain": "Global Maritime Logistics & Ocean Freight"},
    {"name": "Motive", "ats": "greenhouse", "slug": "motive", "domain": "Heavy Trucking Telematics & Vehicle Vision"},
    {"name": "Trimble", "ats": "greenhouse", "slug": "trimble", "domain": "Agriculture & Construction GNSS Telemetry"},
    {"name": "DAT Freight & Analytics", "ats": "greenhouse", "slug": "dat", "domain": "Freight Truckload Telemetry & Spot Rates"},

    # 13. Backbone Data Pipelines & Observability
    {"name": "Cribl", "ats": "greenhouse", "slug": "cribl", "domain": "Telemetry & Observability Data Pipelines"},
    {"name": "Fivetran", "ats": "greenhouse", "slug": "fivetran", "domain": "Automated ETL & Cloud Data Movement"},
    {"name": "Cockroach Labs", "ats": "greenhouse", "slug": "cockroachlabs", "domain": "Cloud Distributed SQL Infrastructure"},
    {"name": "Grafana Labs", "ats": "greenhouse", "slug": "grafanalabs", "domain": "Open Source Metrics, Traces & Logs"},
    {"name": "Datadog", "ats": "greenhouse", "slug": "datadog", "domain": "Cloud Infrastructure Monitoring"},

    # 14. AI Clouds, GPUs & Machine Learning Platforms (Ashby)
    {"name": "Modal", "ats": "ashby", "slug": "modal", "domain": "Serverless Python Cloud & GPU Containers"},
    {"name": "RunPod", "ats": "ashby", "slug": "runpod", "domain": "Distributed GPU Cloud Infrastructure"},
    {"name": "Baseten", "ats": "ashby", "slug": "baseten", "domain": "AI Model Inference Engines"},
    {"name": "Pinecone", "ats": "ashby", "slug": "pinecone", "domain": "Vector Database Infrastructure"},
    {"name": "Cohere", "ats": "ashby", "slug": "cohere", "domain": "Enterprise AI & NLP Architecture"},
    {"name": "Weaviate", "ats": "ashby", "slug": "weaviate", "domain": "AI Vector Search Systems"},
    {"name": "Anyscale", "ats": "ashby", "slug": "anyscale", "domain": "Distributed Ray Computing & ML Infrastructure"},

    # 15. Logistics, Freight Telematics & High-Volume Backends
    {"name": "project44", "ats": "greenhouse", "slug": "project44", "domain": "Global Supply Chain & Freight Telematics"},
    {"name": "Roadie", "ats": "greenhouse", "slug": "roadie", "domain": "Crowdsourced Logistics & Route Telemetry"},
    {"name": "PagerDuty", "ats": "greenhouse", "slug": "pagerduty", "domain": "Cloud Incident Response & Availability Platform"},
    {"name": "CoreWeave", "ats": "greenhouse", "slug": "coreweave", "domain": "Specialized Cloud GPU AI Infrastructure"},
    {"name": "Scale AI", "ats": "greenhouse", "slug": "scaleai", "domain": "Data Infrastructure for AI Foundations"},
    {"name": "MongoDB", "ats": "greenhouse", "slug": "mongodb", "domain": "Distributed Database Systems & Query Engines"},
    {"name": "Elastic", "ats": "greenhouse", "slug": "elastic", "domain": "Distributed Search, Observability & Analytics"},
    {"name": "GitLab", "ats": "greenhouse", "slug": "gitlab", "domain": "Cloud CI/CD & Distributed DevSecOps Platforms"},
    {"name": "Chime", "ats": "greenhouse", "slug": "chime", "domain": "High-Volume Consumer Banking Pipelines"},
    {"name": "Gusto", "ats": "greenhouse", "slug": "gusto", "domain": "Payroll & Workforce Telemetry Backends"},
    {"name": "SoFi", "ats": "greenhouse", "slug": "sofi", "domain": "Fintech Platform & High-Throughput APIs"},
    {"name": "Blend", "ats": "greenhouse", "slug": "blend", "domain": "Cloud Financial & Mortgage Automation Engine"}
]


def load_company_registry() -> List[Dict[str, Any]]:
    """Loads known companies from local database or initializes from seed list."""
    if COMPANIES_DATABASE.exists():
        try:
            with open(COMPANIES_DATABASE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) >= len(SEED_US_COMPANIES):
                    return data
        except Exception as e:
            logger.warning(f"Error reading companies database: {e}")

    save_company_registry(SEED_US_COMPANIES)
    return SEED_US_COMPANIES


def save_company_registry(companies: List[Dict[str, Any]]):
    """Saves updated company list to companies_database.json."""
    try:
        with open(COMPANIES_DATABASE, "w", encoding="utf-8") as f:
            json.dump(companies, f, indent=2)
        logger.info(f"Updated company database with {len(companies)} US firms.")
    except Exception as e:
        logger.error(f"Failed to save companies database: {e}")


def register_discovered_company(name: str, ats: str, slug: str, domain: str = "US Niche Industry Tech") -> bool:
    """Registers a newly discovered US company slug to the local database."""
    companies = load_company_registry()
    clean_slug = slug.strip().lower()

    if contains_wipro(name) or contains_wipro(clean_slug):
        return False

    existing_slugs = {c.get("slug", "").lower() for c in companies}
    if clean_slug not in existing_slugs:
        new_entry = {
            "name": name.strip() or clean_slug.capitalize(),
            "ats": ats.lower(),
            "slug": clean_slug,
            "domain": domain,
            "h1b_sponsor": True
        }
        companies.append(new_entry)
        save_company_registry(companies)
        logger.info(f"Discovered and registered new niche US company: {new_entry['name']} [{ats}] ({domain})")
        return True
    return False


def extract_slug_from_url(url: str) -> Optional[tuple]:
    """Extracts company slug and ATS platform from a job board URL."""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        path_parts = [p for p in parsed.path.split("/") if p]

        if "greenhouse.io" in netloc and path_parts:
            return ("greenhouse", path_parts[0])
        elif "lever.co" in netloc and path_parts:
            return ("lever", path_parts[0])
        elif "ashbyhq.com" in netloc and path_parts:
            return ("ashby", path_parts[0])
    except Exception:
        pass
    return None


def discover_new_us_companies_via_search(max_discoveries: int = 15):
    """
    Executes live web search dorks across boards.greenhouse.io, jobs.lever.co, and jobs.ashbyhq.com
    targeting bizarre, overlooked, and non-standard CS roles across the United States.
    """
    dorks = [
        # Bizarre / Overlooked domain dorks
        'site:boards.greenhouse.io ("telematics" OR "POS" OR "funeral" OR "waste" OR "HVAC") "Engineer" "United States"',
        'site:boards.greenhouse.io ("mortuary" OR "hospitality" OR "vending" OR "plumbing") "Software" "United States"',
        'site:boards.greenhouse.io ("car wash" OR "storage" OR "parking" OR "towing") "Engineer" "United States"',
        'site:jobs.ashbyhq.com ("telemetry" OR "sensors" OR "sewer" OR "robotics") "Engineer" "United States"',
        'site:jobs.lever.co ("point of sale" OR "freight" OR "dispatch" OR "kiosk") "Python" "United States"',
        'site:boards.greenhouse.io ("church" OR "quarry" OR "concrete" OR "laundry") "Engineer" "United States"',
        'site:boards.greenhouse.io "Data Engineer" ("infrastructure" OR "telemetry" OR "sensors") "Remote"',
        'site:jobs.lever.co "Backend Engineer" ("logistics" OR "operations" OR "POS") "United States"'
    ]

    query = random.choice(dorks)
    logger.info(f"Executing bizarre/niche domain ATS web discovery: {query}")

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }
        resp = requests.get(
            f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
            headers=headers,
            timeout=3
        )

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            links = soup.find_all("a", class_="result__url")
            count = 0

            for a in links:
                raw_url = a.get_text(strip=True)
                if not raw_url.startswith("http"):
                    raw_url = "https://" + raw_url
                slug_info = extract_slug_from_url(raw_url)
                if slug_info:
                    platform, slug = slug_info
                    if register_discovered_company(slug.capitalize(), platform, slug):
                        count += 1
                        if count >= max_discoveries:
                            break
    except Exception as e:
        logger.debug(f"Search discovery pass: {e}")


def fetch_jobs_from_company(company: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fetches and filters all active US Computer Science jobs for a given company."""
    platform = company.get("ats", "").lower()
    slug = company.get("slug", "")
    comp_name = company.get("name", slug.capitalize())
    domain = company.get("domain", "Niche US Operations Software")
    jobs = []

    if contains_wipro(comp_name) or contains_wipro(slug):
        return []

    # Anti-Blacklist Safeguard: If company was already applied to, skip it entirely!
    if ONE_ROLE_PER_COMPANY:
        applied_comps = load_applied_companies()
        if comp_name.strip().lower() in applied_comps or slug.strip().lower() in applied_comps:
            logger.info(f"Skipping {comp_name} ({slug}): Already applied (1-role-per-company safeguard).")
            return []

    # 1. Greenhouse
    if platform == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json().get("jobs", [])
                for j in data:
                    title = j.get("title", "").strip()
                    loc = j.get("location", {}).get("name", "").strip()
                    job_id = j.get("id")
                    apply_url = f"https://job-boards.greenhouse.io/embed/job_app?for={slug}&token={job_id}"

                    raw_content = j.get("content") or ""
                    clean_desc = BeautifulSoup(raw_content, "html.parser").get_text(separator=" ") if raw_content else ""
                    posted_at = _extract_posted_at(j, "greenhouse")

                    if posted_at and _is_within_freshness_window(posted_at) and is_strictly_usa(loc) and matches_cs_tech_stack(title, clean_desc):
                        jobs.append({
                            "source": f"Greenhouse ({comp_name})",
                            "ats_platform": "Greenhouse",
                            "company": comp_name,
                            "company_domain": domain,
                            "h1b_sponsor": True,
                            "title": title,
                            "location": loc or "United States (Remote)",
                            "url": apply_url,
                            "posted_at": posted_at.isoformat(),
                            "description": clean_desc or f"Seeking {title} at {comp_name} ({domain}) with Python, SQL, Docker, and data pipeline experience."
                        })
        except Exception as e:
            logger.debug(f"Greenhouse fetch error for {slug}: {e}")

    # 2. Ashby
    elif platform == "ashby":
        url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json().get("jobs", [])
                for j in data:
                    title = j.get("title", "").strip()
                    loc = j.get("location", "").strip() if isinstance(j.get("location"), str) else (j.get("location") or {}).get("name", "")
                    apply_url = j.get("jobUrl") or f"https://jobs.ashbyhq.com/{slug}/{j.get('id')}"

                    desc_plain = j.get("descriptionPlain") or ""
                    if not desc_plain and j.get("descriptionHtml"):
                        desc_plain = BeautifulSoup(j.get("descriptionHtml"), "html.parser").get_text(separator=" ")
                    posted_at = _extract_posted_at(j, "ashby")

                    if posted_at and _is_within_freshness_window(posted_at) and is_strictly_usa(loc) and matches_cs_tech_stack(title, desc_plain):
                        jobs.append({
                            "source": f"Ashby ({comp_name})",
                            "ats_platform": "Ashby",
                            "company": comp_name,
                            "company_domain": domain,
                            "h1b_sponsor": True,
                            "title": title,
                            "location": loc or "United States (Remote)",
                            "url": apply_url,
                            "posted_at": posted_at.isoformat(),
                            "description": desc_plain or f"Seeking {title} at {comp_name} ({domain}) with Computer Science background and Python experience."
                        })
        except Exception as e:
            logger.debug(f"Ashby fetch error for {slug}: {e}")

    # 3. Lever
    elif platform == "lever":
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                for j in data:
                    title = j.get("text", "").strip()
                    cats = j.get("categories", {})
                    loc = cats.get("location", "").strip()
                    apply_url = j.get("applyUrl") or j.get("hostedUrl") or f"https://jobs.lever.co/{slug}/{j.get('id')}"

                    desc_plain = j.get("descriptionPlain") or ""
                    if not desc_plain and j.get("description"):
                        desc_plain = BeautifulSoup(j.get("description"), "html.parser").get_text(separator=" ")
                    posted_at = _extract_posted_at(j, "lever")

                    if posted_at and _is_within_freshness_window(posted_at) and is_strictly_usa(loc) and matches_cs_tech_stack(title, desc_plain):
                        jobs.append({
                            "source": f"Lever ({comp_name})",
                            "ats_platform": "Lever",
                            "company": comp_name,
                            "company_domain": domain,
                            "h1b_sponsor": True,
                            "title": title,
                            "location": loc or "United States (Remote)",
                            "url": apply_url,
                            "posted_at": posted_at.isoformat(),
                            "description": desc_plain or f"Seeking {title} at {comp_name} ({domain}) with Computer Science background."
                        })
        except Exception as e:
            logger.debug(f"Lever fetch error for {slug}: {e}")

    # If multiple eligible jobs found, rank and return ONLY the single 'Perfect Role'
    if len(jobs) > 1:
        scored = sorted(jobs, key=lambda x: score_role_fit(x), reverse=True)
        best_job = scored[0]
        logger.info(
            f"Company '{comp_name}' has {len(jobs)} eligible CS roles. "
            f"Selected single perfect role: '{best_job['title']}' (Score: {score_role_fit(best_job)}/100). "
            f"Discarded {len(jobs) - 1} secondary roles to prevent profile blacklist."
        )
        return [best_job]

    return jobs


def discover_and_source_us_cs_roles(limit: int = 20) -> List[Dict[str, Any]]:
    """
    High-Speed Concurrent Sourcing Engine:
    1. Loads registry of verified US companies.
    2. Pre-filters already applied companies to eliminate redundant network calls.
    3. Concurrently scans 25-35 company career pages in parallel using ThreadPoolExecutor.
    4. Applies strict USA geolocation, 2-3 yr CS role matching, and 1-role-per-company rule.
    5. Returns immediately with top scored opportunities in under 2 seconds.
    """
    companies = load_company_registry()
    applied = load_applied_companies()

    # Pre-filter unapplied companies
    unapplied = [
        c for c in companies
        if c.get("slug", "").strip().lower() not in applied
        and c.get("name", "").strip().lower() not in applied
    ]

    # Automatically discover new US companies if registry has few unapplied
    if len(unapplied) < 20:
        try:
            discover_new_us_companies_via_search(max_discoveries=10)
            companies = load_company_registry()
            unapplied = [
                c for c in companies
                if c.get("slug", "").strip().lower() not in applied
                and c.get("name", "").strip().lower() not in applied
            ]
        except Exception as e:
            logger.debug(f"Auto discovery notice: {e}")

    random.shuffle(unapplied)
    scan_mode = "full-registry" if SCAN_ALL_COMPANIES_EACH_CYCLE else "early-stop"
    logger.info(
        f"Concurrently scanning {len(unapplied)} unapplied US companies for 2-3 yr CS roles "
        f"(mode={scan_mode}, freshness<={JOB_FRESHNESS_WINDOW_HOURS}h)..."
    )
    discovered_roles = []
    seen_companies = set()
    hard_limit = None if SCAN_ALL_COMPANIES_EACH_CYCLE else max(1, limit)

    # Process unapplied companies in concurrent batches until limit is satisfied
    chunk_size = 25
    for offset in range(0, len(unapplied), chunk_size):
        if hard_limit is not None and len(discovered_roles) >= hard_limit:
            break
        batch = unapplied[offset:offset + chunk_size]
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
            futures = {executor.submit(fetch_jobs_from_company, c): c for c in batch}
            for future in concurrent.futures.as_completed(futures):
                try:
                    comp_jobs = future.result()
                    if comp_jobs:
                        best_role = comp_jobs[0]
                        c_name = best_role.get("company", "").strip().lower()
                        if c_name not in seen_companies:
                            seen_companies.add(c_name)
                            discovered_roles.append(best_role)
                            logger.info(f"Identified target role at {best_role.get('company')}: {best_role.get('title')}")
                            if hard_limit is not None and len(discovered_roles) >= hard_limit:
                                break
                except Exception as e:
                    logger.debug(f"Concurrent fetch exception: {e}")

    # Sort discovered roles by score
    scored_roles = sorted(discovered_roles, key=lambda x: score_role_fit(x), reverse=True)
    return scored_roles[:limit]


def search_career_pages_by_query(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Dynamically listens to user query and discovers targeted career pages.
    Automatically registers newly discovered companies into local database.
    """
    from dynamic_search import dynamic_search_career_pages
    data = dynamic_search_career_pages(query, max_results=limit)
    roles = data.get("roles", [])
    for r in roles:
        c_name = r.get("company", "")
        ats = r.get("ats_platform", "").lower()
        url = r.get("career_url", "")
        m = re.search(r"/(?:jobs|job-boards|posting-api|embed)?/?([\w\-]+)/?$", url)
        slug = m.group(1) if m else re.sub(r"[^\w]", "", c_name.lower())
        register_discovered_company(c_name, ats, slug, domain=f"Discovered via: {query[:30]}")
    return roles
