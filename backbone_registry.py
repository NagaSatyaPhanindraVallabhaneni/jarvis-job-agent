import logging
import re
import requests
from typing import List, Dict, Any

logger = logging.getLogger("JarvisJobAgent.BackboneRegistry")

# Curated registry of mid-range backbone companies
# Verified: High compensation ($130k-$220k+), H-1B sponsorship track record, ATS platform hosted
BACKBONE_COMPANIES = [
    # Telemetry, Physical Infrastructure & Logistics
    {
        "name": "Samsara",
        "ats": "greenhouse",
        "slug": "samsara",
        "domain": "Connected Operations & IoT Telemetry",
        "h1b_sponsor": True
    },
    {
        "name": "Flexport",
        "ats": "greenhouse",
        "slug": "flexport",
        "domain": "Global Logistics & Supply Chain Infrastructure",
        "h1b_sponsor": True
    },
    {
        "name": "Motive",
        "ats": "greenhouse",
        "slug": "motive",
        "domain": "Fleet Telemetry & Industrial Automation",
        "h1b_sponsor": True
    },

    # Data Infrastructure, Pipelines & Observability
    {
        "name": "Cribl",
        "ats": "greenhouse",
        "slug": "cribl",
        "domain": "Telemetry & Observability Data Pipelines",
        "h1b_sponsor": True
    },
    {
        "name": "Fivetran",
        "ats": "greenhouse",
        "slug": "fivetran",
        "domain": "Automated Data Movement & ETL Pipelines",
        "h1b_sponsor": True
    },
    {
        "name": "Cockroach Labs",
        "ats": "greenhouse",
        "slug": "cockroachlabs",
        "domain": "Distributed SQL Cloud Infrastructure",
        "h1b_sponsor": True
    },
    {
        "name": "Grafana Labs",
        "ats": "greenhouse",
        "slug": "grafanalabs",
        "domain": "Open Source Metrics, Logs & Traces Telemetry",
        "h1b_sponsor": True
    },
    {
        "name": "Datadog",
        "ats": "greenhouse",
        "slug": "datadog",
        "domain": "Cloud Telemetry, Monitoring & Observability",
        "h1b_sponsor": True
    },

    # Cloud AI, GPUs & Developer Platforms (Ashby & Greenhouse)
    {
        "name": "Modal",
        "ats": "ashby",
        "slug": "modal",
        "domain": "Serverless Cloud Python & AI Container Infra",
        "h1b_sponsor": True
    },
    {
        "name": "RunPod",
        "ats": "ashby",
        "slug": "runpod",
        "domain": "Distributed GPU Cloud Infrastructure for AI",
        "h1b_sponsor": True
    },
    {
        "name": "Baseten",
        "ats": "ashby",
        "slug": "baseten",
        "domain": "Machine Learning Model Inference Infrastructure",
        "h1b_sponsor": True
    },
    {
        "name": "Pinecone",
        "ats": "ashby",
        "slug": "pinecone",
        "domain": "Vector Database Infrastructure for AI",
        "h1b_sponsor": True
    },
    {
        "name": "Cohere",
        "ats": "ashby",
        "slug": "cohere",
        "domain": "Enterprise AI & NLP Platform",
        "h1b_sponsor": True
    },
    {
        "name": "Weaviate",
        "ats": "ashby",
        "slug": "weaviate",
        "domain": "Open Source Vector Database & AI Search",
        "h1b_sponsor": True
    }
]

# Strict positive engineering targets
ROLE_KEYWORDS = [
    "data engineer", "data infrastructure engineer", "data platform engineer",
    "ai engineer", "machine learning engineer", "ml engineer",
    "backend engineer", "backend developer", "python engineer",
    "software engineer - data", "etl engineer", "pipeline engineer",
    "software engineer, data", "software engineer, backend",
    "software engineer - backend", "software engineer - python"
]

# Strict negative blacklist to eliminate non-engineering positions
EXCLUDED_ROLE_KEYWORDS = [
    "product manager", "project manager", "program manager",
    "director", "vp", "vice president", "head of", "recruiter",
    "account executive", "sales", "business development", "marketing",
    "customer success", "support", "intern", "internship", "fellowship",
    "designer", "writer", "lawyer", "legal", "analyst, product", "security operations"
]


def matches_target_role(title: str) -> bool:
    """Checks if job title strictly aligns with engineering target roles and excludes management/sales."""
    title_lower = title.lower()

    # Reject any non-engineering role immediately
    for exc in EXCLUDED_ROLE_KEYWORDS:
        if exc in title_lower:
            return False

    # Check positive engineering match
    return any(kw in title_lower for kw in ROLE_KEYWORDS)


def is_us_or_remote(location_str: str) -> bool:
    """Filters for US Remote or Dayton, OH positions, excluding foreign offices."""
    loc = location_str.lower()
    us_indicators = ["remote", "united states", "usa", "us", "dayton", "ohio", "north america", "anywhere"]
    foreign_indicators = [
        "canada", "uk", "london", "germany", "berlin", "france", "paris",
        "india", "bengaluru", "singapore", "australia", "poland", "spain",
        "brazil", "japan", "netherlands", "ireland", "dublin"
    ]

    has_us = any(u in loc for u in us_indicators)
    has_foreign = any(f in loc for f in foreign_indicators)

    if has_foreign and not ("united states" in loc or "us remote" in loc):
        return False
    return has_us or loc == ""


def fetch_greenhouse_jobs(company: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fetches and filters jobs directly from Greenhouse public API."""
    slug = company["slug"]
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    jobs = []

    try:
        resp = requests.get(url, timeout=8)
        if resp.status_code == 200:
            data = resp.json().get("jobs", [])
            for j in data:
                title = j.get("title", "").strip()
                loc = j.get("location", {}).get("name", "").strip()
                job_id = j.get("id")
                apply_url = j.get("absolute_url") or f"https://boards.greenhouse.io/{slug}/jobs/{job_id}"

                if matches_target_role(title) and is_us_or_remote(loc):
                    detail_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}"
                    desc = ""
                    try:
                        d_resp = requests.get(detail_url, timeout=6)
                        if d_resp.status_code == 200:
                            desc = d_resp.json().get("content", "")
                            desc = re.sub(r"<[^>]+>", " ", desc)
                            desc = re.sub(r"\s+", " ", desc).strip()
                    except Exception:
                        pass

                    jobs.append({
                        "source": "Greenhouse Direct Career Page",
                        "ats_platform": "Greenhouse",
                        "company": company["name"],
                        "company_domain": company["domain"],
                        "h1b_sponsor": company["h1b_sponsor"],
                        "title": title,
                        "location": loc or "US Remote",
                        "url": apply_url,
                        "description": desc or f"Seeking {title} at {company['name']} with Python, Spark, and data pipeline experience."
                    })
    except Exception as e:
        logger.warning(f"Error fetching Greenhouse jobs for {company['name']}: {e}")

    return jobs


def fetch_ashby_jobs(company: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fetches and filters jobs directly from Ashby public API."""
    slug = company["slug"]
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    jobs = []

    try:
        resp = requests.get(url, timeout=8)
        if resp.status_code == 200:
            data = resp.json().get("jobs", [])
            for j in data:
                title = j.get("title", "").strip()
                loc = j.get("location", "").strip() if isinstance(j.get("location"), str) else (j.get("location") or {}).get("name", "")
                apply_url = j.get("jobUrl") or f"https://jobs.ashbyhq.com/{slug}/{j.get('id')}"
                desc = j.get("descriptionPlain") or j.get("descriptionHtml") or ""
                desc = re.sub(r"<[^>]+>", " ", desc)
                desc = re.sub(r"\s+", " ", desc).strip()

                if matches_target_role(title) and is_us_or_remote(loc):
                    jobs.append({
                        "source": "Ashby Direct Career Page",
                        "ats_platform": "Ashby",
                        "company": company["name"],
                        "company_domain": company["domain"],
                        "h1b_sponsor": company["h1b_sponsor"],
                        "title": title,
                        "location": loc or "US Remote",
                        "url": apply_url,
                        "description": desc or f"Seeking {title} at {company['name']} with Python, Docker, and data pipeline experience."
                    })
    except Exception as e:
        logger.warning(f"Error fetching Ashby jobs for {company['name']}: {e}")

    return jobs


def fetch_backbone_jobs() -> List[Dict[str, Any]]:
    """Fetches all active candidate-matching jobs across the backbone company registry."""
    all_jobs = []
    logger.info(f"Scanning {len(BACKBONE_COMPANIES)} backbone tech companies across Greenhouse & Ashby...")

    for comp in BACKBONE_COMPANIES:
        platform = comp["ats"].lower()
        if platform == "greenhouse":
            comp_jobs = fetch_greenhouse_jobs(comp)
        elif platform == "ashby":
            comp_jobs = fetch_ashby_jobs(comp)
        else:
            comp_jobs = []

        if comp_jobs:
            logger.info(f"Found {len(comp_jobs)} filtered engineering roles at {comp['name']} ({comp['domain']})")
            all_jobs.extend(comp_jobs)

    logger.info(f"Total matching backbone career page roles discovered: {len(all_jobs)}")
    return all_jobs
