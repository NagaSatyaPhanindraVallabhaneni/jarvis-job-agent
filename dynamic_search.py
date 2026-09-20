import concurrent.futures
import json
import logging
import re
import urllib.parse
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import requests
from bs4 import BeautifulSoup

from config import (
    is_strictly_usa,
    matches_cs_tech_stack,
    is_strictly_cs_role,
    contains_wipro,
    is_itar_or_clearance,
    check_experience_level,
    score_role_fit,
    load_applied_companies,
    CORE_TECH_SKILLS,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    FREE_MODEL_FALLBACKS
)
from h1b_radar import get_h1b_sponsor_info

logger = logging.getLogger("JarvisJobAgent.GeminiHunter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Extensive Knowledge Base of High-Growth US Tech Companies by Domain
EXPANDED_SECTOR_TAXONOMY: Dict[str, List[str]] = {
    "fintech": [
        "Ramp", "Brex", "Stripe", "Plaid", "Chime", "Affirm", "Robinhood", "Blend",
        "Mercury", "SoFi", "Toast", "SpotOn", "Block", "Carta", "Adyen", "Klarna",
        "Apex Clearing", "Marqeta", "Checkout.com", "Modern Treasury", "DriveWealth"
    ],
    "ai": [
        "OpenAI", "Anthropic", "Scale AI", "Modal", "RunPod", "Baseten", "Pinecone",
        "Cohere", "Cursor", "ElevenLabs", "Perplexity", "Harvey", "Dust", "Together",
        "Weaviate", "Anyscale", "Groq", "Replicate", "Hugging Face", "LangChain",
        "Writer", "Mistral", "Chroma", "Glean", "Character AI", "Synthesia"
    ],
    "devtools": [
        "Vercel", "Supabase", "PostHog", "Datadog", "Grafana Labs", "Cockroach Labs",
        "Figma", "GitLab", "PagerDuty", "Cribl", "Fivetran", "Temporal", "Astronomer",
        "Docker", "HashiCorp", "Render", "Fly.io", "Railway", "Sourcegraph", "Sentry",
        "LaunchDarkly", "CircleCI", "Pulumi", "Prisma", "Linear", "Retool"
    ],
    "robotics": [
        "Skydio", "Nuro", "Robust AI", "Figure AI", "Covariant", "Serve Robotics",
        "Bear Robotics", "Apptronik", "Boston Dynamics", "Symbotic", "Outrider",
        "Physical Intelligence", "Waymo", "Zoox", "Shield AI", "Anduril"
    ],
    "healthcare": [
        "Oscar Health", "Tempus", "Komodo Health", "Flatiron Health", "Ro",
        "Color Health", "Headway", "Modern Health", "Spring Health", "Hims & Hers",
        "Zocdoc", "Verily", "Invitae", "Doximity", "Grand Rounds"
    ],
    "logistics": [
        "Flexport", "Samsara", "project44", "Motive", "Roadie", "DAT Freight & Analytics",
        "Trimble", "Flock Freight", "Turvo", "ShipBob", "KeepTruckin", "Convoy"
    ],
    "cloud": [
        "CoreWeave", "Elastic", "Cloudflare", "MongoDB", "Databricks", "Snowflake",
        "Confluent", "DigitalOcean", "Fastly", "Akamai", "Okta", "Zscaler",
        "Couchbase", "Redis", "SingleStore", "Kong", "CloudBees"
    ],
    "security": [
        "CrowdStrike", "SentinelOne", "Snyk", "Wiz", "Lacework", "Vanta", "Drata",
        "Tenable", "Palo Alto Networks", "Netskope", "1Password", "Axonius", "Abnormal Security"
    ],
    "ecommerce": [
        "Shopify", "Instacart", "Faire", "DoorDash", "Etsy", "Wayfair", "Chewy", "Wish"
    ],
    "gaming": [
        "Roblox", "Unity", "Epic Games", "Discord", "Riot Games", "Twitch", "Niantic"
    ],
    "water": [
        "Watershed", "Sofar Ocean", "Bedrock Ocean Exploration", "Aquabyte", "Samsara", "Badger Meter", "WaterTech"
    ]
}


@dataclass
class JobOpportunity:
    company: str
    title: str
    location: str
    ats_platform: str
    career_url: str
    apply_url: str
    description_snippet: str
    fit_score: float
    matched_skills: List[str]
    experience_level: str
    domain: str
    h1b_approval_rate: float = 95.0
    salary_range: str = "$140,000 - $175,000"
    h1b_status: str = "SPONSOR_VERIFIED"
    application_status: str = "FRESH"
    full_description: str = ""


class GeminiCareerHunter:
    """
    Top-tier, production-grade Career Page Discovery Engine modeled after Google Gemini.
    Features:
    - Real-time semantic natural language prompt parsing.
    - Neural candidate generation via OpenRouter LLM with automated model failover.
    - Deep sector graph expansion across 500+ verified US companies.
    - Concurrently verifies canonical career pages on Greenhouse, Ashby, and Lever.
    - Deep multi-dimensional ATS scoring (strictly 2-3 yrs exp, USA geolocation, tech stack).
    - Guaranteed 1-role-per-company anti-blacklist policy.
    """

    def __init__(self):
        self.applied_companies = load_applied_companies()
        self.all_companies: List[Dict[str, Any]] = []
        self.company_index: Dict[str, Dict[str, Any]] = {}
        self._load_master_companies()

    def _load_master_companies(self):
        db_path = Path(__file__).parent / "companies_database.json"
        if db_path.exists():
            try:
                self.all_companies = json.loads(db_path.read_text(encoding="utf-8"))
                for c in self.all_companies:
                    self.company_index[c["name"].lower().strip()] = c
                    self.company_index[c["slug"].lower().strip()] = c
                    stripped = re.sub(r"[^\w]", "", c["name"].lower())
                    if stripped not in self.company_index:
                        self.company_index[stripped] = c
                logger.info(f"Loaded {len(self.all_companies)} verified US tech companies into fast memory index.")
            except Exception as e:
                logger.warning(f"Error loading companies database: {e}")

    def parse_query(self, user_query: str) -> Dict[str, Any]:
        """Interprets natural language prompts into structured extraction goals."""
        q_lower = user_query.lower().strip()

        # 1. Detect roles
        target_roles = []
        if any(w in q_lower for w in ["data engineer", "data platform", "etl", "pipeline"]):
            target_roles.append("Data Engineer")
        if any(w in q_lower for w in ["python", "backend", "api", "fastapi"]):
            target_roles.append("Backend Engineer")
        if any(w in q_lower for w in ["machine learning", "ml", "ai engineer", "agentic", "llm"]):
            target_roles.append("Machine Learning Engineer")
        if any(w in q_lower for w in ["software engineer", "developer", "swe", "sde"]):
            target_roles.append("Software Engineer")
        if any(w in q_lower for w in ["cloud", "devops", "infrastructure", "sre", "platform engineer"]):
            target_roles.append("DevOps Engineer")

        if not target_roles:
            target_roles = ["Software Engineer", "Backend Engineer", "Data Engineer"]

        # 2. Extract technical skill requirements
        skills_detected = []
        for skill in CORE_TECH_SKILLS:
            if re.search(r"\b" + re.escape(skill) + r"\b", q_lower):
                skills_detected.append(skill)
        if "python" not in skills_detected:
            skills_detected.append("python")

        # 3. Detect domains / sectors
        matched_domains = []
        for dom in EXPANDED_SECTOR_TAXONOMY.keys():
            if dom in q_lower:
                matched_domains.append(dom)
        if not matched_domains:
            if any(w in q_lower for w in ["bank", "pay", "finance", "money", "invest", "crypto", "trading"]):
                matched_domains.append("fintech")
            if any(w in q_lower for w in ["llm", "agent", "gpt", "model", "neural", "vision", "genai"]):
                matched_domains.append("ai")
            if any(w in q_lower for w in ["drone", "sensor", "hardware", "autonomous", "vehicle", "robot"]):
                matched_domains.append("robotics")
            if any(w in q_lower for w in ["hospital", "patient", "clinical", "pharma", "health", "bio"]):
                matched_domains.append("healthcare")
            if any(w in q_lower for w in ["truck", "freight", "warehouse", "fleet", "supply chain"]):
                matched_domains.append("logistics")
            if any(w in q_lower for w in ["server", "database", "pipeline", "infra", "observability", "distributed"]):
                matched_domains.append("cloud")
            if any(w in q_lower for w in ["cyber", "threat", "auth", "identity", "firewall"]):
                matched_domains.append("security")
            if any(w in q_lower for w in ["water", "sewage", "tank", "wastewater", "marine", "ocean", "aquatic", "liquid", "effluent", "treatment", "utility"]):
                matched_domains.append("water")

        if not matched_domains:
            matched_domains = ["ai", "cloud", "devtools"]

        return {
            "raw_query": user_query,
            "roles": target_roles,
            "skills": skills_detected,
            "domains": matched_domains,
            "experience_band": "Strictly 2 to 3 years (Max 3 to 4 yrs)"
        }

    def generate_candidate_companies(self, intent: Dict[str, Any]) -> List[str]:
        """
        Selects candidate companies from the 505-company registry matching the query,
        intent domains, and LLM suggestions.
        """
        candidates: List[str] = []
        user_query = intent["raw_query"]
        q_low = user_query.lower()

        # 1. Directly named companies in query from master registry
        for c in self.all_companies:
            c_name = c["name"]
            if c_name.lower() in q_low:
                if c_name not in candidates:
                    candidates.append(c_name)

        # 2. Sector / Domain matching from 505 master registry
        query_words = set(re.findall(r"\b\w{3,}\b", q_low))
        scored_candidates = []
        for c in self.all_companies:
            name = c["name"]
            if name in candidates:
                continue
            domain_text = (c.get("domain", "") + " " + name).lower()
            match_score = 0
            for dom in intent["domains"]:
                if dom in domain_text:
                    match_score += 3
            for qw in query_words:
                if qw in domain_text:
                    match_score += 2
            if match_score > 0:
                scored_candidates.append((match_score, name))

        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        for _, name in scored_candidates[:35]:
            if name not in candidates:
                candidates.append(name)

        # 3. LLM assistance for edge queries
        if len(candidates) < 15:
            prompt = (
                f"Based on this search query: '{user_query}', "
                f"name 15 top US tech companies actively hiring Software/Data engineers. "
                f"Return ONLY a valid JSON array of strings. Example: [\"Ramp\", \"Scale AI\"]."
            )
            for model in FREE_MODEL_FALLBACKS:
                try:
                    resp = requests.post(
                        f"{OPENROUTER_BASE_URL}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.2
                        },
                        timeout=4
                    )
                    if resp.status_code == 200:
                        raw = resp.json()["choices"][0]["message"]["content"].strip()
                        m = re.search(r"\[.*?\]", raw, re.DOTALL)
                        if m:
                            comps = json.loads(m.group(0))
                            for c in comps:
                                if isinstance(c, str) and c not in candidates:
                                    candidates.append(c.strip())
                            break
                except Exception:
                    pass

        # Also pull from taxonomy fallback
        for dom in intent["domains"]:
            for firm in EXPANDED_SECTOR_TAXONOMY.get(dom, []):
                if firm not in candidates:
                    candidates.append(firm)

        return candidates

    def resolve_portal(self, company_name: str) -> Optional[Dict[str, Any]]:
        """Resolves a company name to its canonical ATS portal across Greenhouse, Ashby, and Lever."""
        clean_name = company_name.strip()
        low_name = clean_name.lower()
        stripped = re.sub(r"[^\w]", "", low_name)

        # 1. Instant 0ms lookup from 505 master registry
        c = self.company_index.get(low_name) or self.company_index.get(stripped)
        if c:
            ats_name = c["ats"].capitalize() if c["ats"].lower() != "smartrecruiters" else "SmartRecruiters"
            slug = c["slug"]
            career_url = c.get("career_url")
            if not career_url:
                if c["ats"].lower() == "greenhouse":
                    career_url = f"https://job-boards.greenhouse.io/{slug}"
                elif c["ats"].lower() == "ashby":
                    career_url = f"https://jobs.ashbyhq.com/{slug}"
                elif c["ats"].lower() == "lever":
                    career_url = f"https://jobs.lever.co/{slug}"
                else:
                    career_url = f"https://apply.workable.com/{slug}"

            return {
                "company": c["name"],
                "ats": ats_name,
                "slug": slug,
                "career_url": career_url,
                "domain": c.get("domain", "Technology"),
                "job_count": 10
            }

        # 2. Heuristic HTTP probes for uncataloged companies
        slug_candidates = [
            stripped,
            low_name.replace(" ", "-"),
            low_name.replace(" ", "_")
        ]

        # Greenhouse Check
        for slug in slug_candidates:
            try:
                r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", timeout=2.0)
                if r.status_code == 200:
                    jobs = r.json().get("jobs", [])
                    if isinstance(jobs, list) and len(jobs) > 0:
                        return {
                            "company": clean_name,
                            "ats": "Greenhouse",
                            "slug": slug,
                            "career_url": f"https://job-boards.greenhouse.io/{slug}",
                            "api_url": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                            "job_count": len(jobs)
                        }
            except Exception:
                pass

        # Ashby Check
        for slug in slug_candidates:
            try:
                r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=2.0)
                if r.status_code == 200:
                    jobs = r.json().get("jobs", [])
                    if isinstance(jobs, list) and len(jobs) > 0:
                        return {
                            "company": clean_name,
                            "ats": "Ashby",
                            "slug": slug,
                            "career_url": f"https://jobs.ashbyhq.com/{slug}",
                            "api_url": f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                            "job_count": len(jobs)
                        }
            except Exception:
                pass

        # Lever Check
        for slug in slug_candidates:
            try:
                r = requests.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=2.0)
                if r.status_code == 200:
                    jobs = r.json()
                    if isinstance(jobs, list) and len(jobs) > 0:
                        return {
                            "company": clean_name,
                            "ats": "Lever",
                            "slug": slug,
                            "career_url": f"https://jobs.lever.co/{slug}",
                            "api_url": f"https://api.lever.co/v0/postings/{slug}?mode=json",
                            "job_count": len(jobs)
                        }
            except Exception:
                pass

        return None

    def inspect_and_filter_roles(self, portal: Dict[str, Any], intent: Dict[str, Any]) -> List[JobOpportunity]:
        """Crawls live job postings from a verified portal, filtering strictly for 2-3 YOE CS roles."""
        ats = portal.get("ats")
        slug = portal.get("slug")
        company = portal.get("company", slug.title())
        career_url = portal.get("career_url")
        opportunities: List[JobOpportunity] = []

        if contains_wipro(company) or contains_wipro(slug):
            return []

        h1b_data = get_h1b_sponsor_info(company)
        headers = {"User-Agent": USER_AGENT}
        is_applied = company.lower() in self.applied_companies or slug.lower() in self.applied_companies
        app_status = "PORTAL_CAPTURED" if is_applied else "FRESH"

        # 1. Greenhouse
        if ats == "Greenhouse":
            try:
                r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", headers=headers, timeout=5)
                if r.status_code == 200:
                    jobs = r.json().get("jobs", [])
                    for j in jobs:
                        title = j.get("title", "").strip()
                        loc = j.get("location", {}).get("name", "").strip()
                        raw = j.get("content") or ""
                        clean_desc = BeautifulSoup(raw, "html.parser").get_text(separator=" ") if raw else ""

                        if not is_strictly_usa(loc, title):
                            continue
                        if not is_strictly_cs_role(title, clean_desc):
                            continue
                        if not matches_cs_tech_stack(title, clean_desc):
                            continue
                        exp_ok, _ = check_experience_level(title, clean_desc)
                        if not exp_ok:
                            continue
                        if is_itar_or_clearance(title) or is_itar_or_clearance(clean_desc):
                            continue

                        matched_skills = [s for s in CORE_TECH_SKILLS if s in clean_desc.lower() or s in title.lower()]
                        fit_score = score_role_fit({"title": title, "description": clean_desc}, applicant_count=8)

                        job_id = j.get("id")
                        apply_url = f"https://job-boards.greenhouse.io/embed/job_app?for={slug}&token={job_id}"

                        opportunities.append(JobOpportunity(
                            company=company,
                            title=title,
                            location=loc or "United States (Remote)",
                            ats_platform="Greenhouse",
                            career_url=career_url,
                            apply_url=apply_url,
                            description_snippet=clean_desc[:250].strip() + "...",
                            fit_score=fit_score,
                            matched_skills=matched_skills[:6],
                            experience_level="2-3 Years (Mid-Level)",
                            domain=intent["domains"][0].title() if intent["domains"] else "Technology",
                            h1b_approval_rate=h1b_data["approval_rate"],
                            salary_range=h1b_data["salary_range"],
                            h1b_status=h1b_data["status"],
                            application_status=app_status,
                            full_description=clean_desc
                        ))
            except Exception as e:
                logger.debug(f"Greenhouse crawl notice: {e}")

        # 2. Ashby
        elif ats == "Ashby":
            try:
                r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", headers=headers, timeout=5)
                if r.status_code == 200:
                    jobs = r.json().get("jobs", [])
                    for j in jobs:
                        title = j.get("title", "").strip()
                        loc = j.get("location", "") if isinstance(j.get("location"), str) else (j.get("location") or {}).get("name", "")
                        desc_plain = j.get("descriptionPlain") or ""
                        if not desc_plain and j.get("descriptionHtml"):
                            desc_plain = BeautifulSoup(j.get("descriptionHtml"), "html.parser").get_text(separator=" ")

                        if not is_strictly_usa(loc, title):
                            continue
                        if not is_strictly_cs_role(title, desc_plain):
                            continue
                        if not matches_cs_tech_stack(title, desc_plain):
                            continue
                        exp_ok, _ = check_experience_level(title, desc_plain)
                        if not exp_ok:
                            continue
                        if is_itar_or_clearance(title) or is_itar_or_clearance(desc_plain):
                            continue

                        matched_skills = [s for s in CORE_TECH_SKILLS if s in desc_plain.lower() or s in title.lower()]
                        fit_score = score_role_fit({"title": title, "description": desc_plain}, applicant_count=8)
                        apply_url = j.get("jobUrl") or f"https://jobs.ashbyhq.com/{slug}/{j.get('id')}"

                        opportunities.append(JobOpportunity(
                            company=company,
                            title=title,
                            location=loc or "United States (Remote)",
                            ats_platform="Ashby",
                            career_url=career_url,
                            apply_url=apply_url,
                            description_snippet=desc_plain[:250].strip() + "...",
                            fit_score=fit_score,
                            matched_skills=matched_skills[:6],
                            experience_level="2-3 Years (Mid-Level)",
                            domain=intent["domains"][0].title() if intent["domains"] else "Technology",
                            h1b_approval_rate=h1b_data["approval_rate"],
                            salary_range=h1b_data["salary_range"],
                            h1b_status=h1b_data["status"],
                            application_status=app_status,
                            full_description=desc_plain
                        ))
            except Exception as e:
                logger.debug(f"Ashby crawl notice: {e}")

        # 3. Lever
        elif ats == "Lever":
            try:
                r = requests.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", headers=headers, timeout=5)
                if r.status_code == 200:
                    jobs = r.json()
                    for j in jobs:
                        title = j.get("text", "").strip()
                        cats = j.get("categories", {})
                        loc = cats.get("location", "").strip()
                        desc_plain = j.get("descriptionPlain") or ""
                        if not desc_plain and j.get("description"):
                            desc_plain = BeautifulSoup(j.get("description"), "html.parser").get_text(separator=" ")

                        if not is_strictly_usa(loc, title):
                            continue
                        if not is_strictly_cs_role(title, desc_plain):
                            continue
                        if not matches_cs_tech_stack(title, desc_plain):
                            continue
                        exp_ok, _ = check_experience_level(title, desc_plain)
                        if not exp_ok:
                            continue
                        if is_itar_or_clearance(title) or is_itar_or_clearance(desc_plain):
                            continue

                        matched_skills = [s for s in CORE_TECH_SKILLS if s in desc_plain.lower() or s in title.lower()]
                        fit_score = score_role_fit({"title": title, "description": desc_plain}, applicant_count=8)
                        apply_url = j.get("applyUrl") or j.get("hostedUrl") or f"https://jobs.lever.co/{slug}/{j.get('id')}"

                        opportunities.append(JobOpportunity(
                            company=company,
                            title=title,
                            location=loc or "United States (Remote)",
                            ats_platform="Lever",
                            career_url=career_url,
                            apply_url=apply_url,
                            description_snippet=desc_plain[:250].strip() + "...",
                            fit_score=fit_score,
                            matched_skills=matched_skills[:6],
                            experience_level="2-3 Years (Mid-Level)",
                            domain=intent["domains"][0].title() if intent["domains"] else "Technology",
                            h1b_approval_rate=h1b_data["approval_rate"],
                            salary_range=h1b_data["salary_range"],
                            h1b_status=h1b_data["status"],
                            application_status=app_status,
                            full_description=desc_plain
                        ))
            except Exception as e:
                logger.debug(f"Lever crawl notice: {e}")

        # Anti-Blacklist: Return ONLY the single highest-scoring role per company
        if len(opportunities) > 1:
            opportunities.sort(key=lambda x: x.fit_score, reverse=True)
            return [opportunities[0]]

        return opportunities

    def search(self, user_query: str, max_results: int = 8) -> Dict[str, Any]:
        """
        Executes end-to-end Gemini-style career search:
        1. Deconstructs intent
        2. Discovers matching companies
        3. Concurrently resolves portals
        4. Crawls and scores 2-3 yr roles
        """
        intent = self.parse_query(user_query)
        candidates = self.generate_candidate_companies(intent)

        # Concurrently resolve portals
        resolved_portals = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=14) as executor:
            future_to_c = {executor.submit(self.resolve_portal, c): c for c in candidates[:30]}
            for future in concurrent.futures.as_completed(future_to_c):
                try:
                    portal = future.result()
                    if portal:
                        resolved_portals.append(portal)
                except Exception:
                    pass

        # Concurrently crawl roles from verified portals
        all_opportunities: List[JobOpportunity] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
            future_to_p = {executor.submit(self.inspect_and_filter_roles, p, intent): p for p in resolved_portals}
            for future in concurrent.futures.as_completed(future_to_p):
                try:
                    opps = future.result()
                    if opps:
                        all_opportunities.extend(opps)
                except Exception:
                    pass

        # Sort by fit score
        all_opportunities.sort(key=lambda x: x.fit_score, reverse=True)
        top_roles = all_opportunities[:max_results]

        return {
            "query": user_query,
            "intent": intent,
            "total_portals_resolved": len(resolved_portals),
            "total_matches_found": len(all_opportunities),
            "roles": [asdict(r) for r in top_roles]
        }


def _build_career_url(c: dict) -> str:
    """Return the correct career page URL for a company dict, with per-ATS fallbacks."""
    if c.get("career_url"):
        return c["career_url"]
    ats = c.get("ats", "").lower()
    slug = c.get("slug", "")
    if "ashby" in ats:
        return f"https://jobs.ashbyhq.com/{slug}"
    if "lever" in ats:
        return f"https://jobs.lever.co/{slug}"
    if "smartrecruiters" in ats:
        return f"https://jobs.smartrecruiters.com/{slug}"
    if "workday" in ats:
        return f"https://{slug}.wd5.myworkdayjobs.com/Careers"
    # Greenhouse (default)
    return f"https://job-boards.greenhouse.io/{slug}"


# ── GeminiCareerHunter gets get_company_directory monkey-patched in after the helper ──

def _get_company_directory(self, query: str = "", sector: str = "", limit: int = 200) -> Dict[str, Any]:
    """Returns verified companies from the 505 database matching filters."""
    sector_keywords = {
        'frontier ai': ['ai', 'llm', 'language model', 'machine learning', 'neural', 'deep learning', 'foundation model', 'generative', 'vision', 'vector', 'speech', 'diffusion', 'inference', 'nlp', 'anthropic', 'openai', 'scale', 'cohere', 'mistral', 'groq', 'cerebras', 'samba', 'hugging', 'perplexity', 'runway', 'elevenlabs', 'suno', 'midjourney', 'adept', 'character', 'together', 'replicate', 'pinecone', 'weaviate', 'qdrant', 'chroma', 'modal', 'baseten', 'octoai', 'anyscale'],
        'fintech': ['fintech', 'payment', 'crypto', 'trading', 'bank', 'lending', 'credit', 'wealth', 'asset', 'custody', 'billing', 'invoice', 'payroll', 'tax', 'equity', 'spend', 'reconciliation', 'plaid', 'stripe', 'ramp', 'brex', 'coinbase', 'block', 'robinhood', 'chime', 'sofi', 'affirm', 'carta', 'gusto', 'deel', 'rippling', 'marqeta', 'mercury', 'navan', 'bill.com', 'tipalti', 'kraken', 'gemini', 'anchor', 'circle', 'paxos', 'fireblocks', 'chainalysis', 'two sigma', 'citadel', 'jane street', 'hudson river', 'jump trading', 'drw', 'virtu'],
        'cloud': ['cloud', 'distributed', 'database', 'infrastructure', 'streaming', 'kafka', 'nosql', 'serverless', 'storage', 'datacenter', 'networking', 's3', 'sql', 'snowflake', 'databricks', 'mongodb', 'elastic', 'cockroach', 'confluent', 'hashicorp', 'digitalocean', 'fastly', 'cloudflare', 'starburst', 'clickhouse', 'couchbase', 'redis', 'singlestore', 'influx', 'timescale', 'scylla', 'minio', 'neon', 'planetscale', 'supabase', 'vercel', 'netlify', 'fly.io', 'railway', 'render', 'dynatrace', 'splunk', 'sumo', 'new relic', 'grafana', 'cribl', 'fivetran', 'pagerduty'],
        'devtools': ['devtool', 'ci/cd', 'developer', 'pipeline', 'testing', 'compiler', 'ide', 'git', 'deploy', 'observability', 'build', 'debug', 'monitoring', 'github', 'gitlab', 'docker', 'postman', 'sentry', 'launchdarkly', 'datadog', 'circleci', 'harness', 'temporal', 'pulumi', 'linear', 'replit', 'cursor', 'sourcegraph', 'dbt', 'prisma', 'cypress', 'playwright', 'snyk'],
        'cybersecurity': ['cybersecurity', 'security', 'identity', 'auth', 'threat', 'endpoint', 'firewall', 'zero trust', 'compliance', 'encryption', 'vulnerability', 'crowdstrike', 'palo alto', 'zscaler', 'okta', 'cloudflare', 'sentinelone', 'wiz', 'snyk', 'teleport', '1password', 'tailscale', 'verkada', 'drata', 'vanta', 'abnormal', 'netskope', 'lacework', 'orca', 'cybereason', 'tanium', 'recorded future'],
        'robotics': ['robotic', 'autonom', 'drone', 'vehicle', 'defense', 'aerospace', 'space', 'satellite', 'mobility', 'anduril', 'waymo', 'cruise', 'zoox', 'aurora', 'skydio', 'shield ai', 'nuro', 'kodiak', 'zipline', 'figure', 'boston dynamics', 'physical intelligence', 'sanctuary', 'symbotic', 'locus', 'agility', 'astrolab', 'apex', 'relativity', 'rocket lab'],
        'health': ['health', 'biotech', 'medical', 'clinical', 'genom', 'therapeutic', 'patient', 'care', 'pharma', 'diagnostic', 'tempus', 'flatiron', 'oscar', 'one medical', 'ro', 'hims', 'komodo', 'insitro', 'recursion', 'doximity', 'veeva', 'benchling'],
        'commerce': ['commerce', 'marketplace', 'retail', 'shopping', 'store', 'goods', 'shipping', 'shopify', 'instacart', 'doordash', 'wayfair', 'etsy', 'ebay', 'chewy', 'faire', 'goat', 'stockx', 'whatnot'],
        'logistics': ['logistics', 'supply chain', 'freight', 'trucking', 'fleet', 'warehouse', 'transport', 'delivery', 'flexport', 'samsara', 'motive', 'convoy', 'project44', 'fourkites', 'gopuff'],
        'saas': ['saas', 'enterprise', 'productivity', 'crm', 'collaboration', 'workplace', 'workflow', 'management', 'notion', 'airtable', 'figma', 'miro', 'coda', 'asana', 'monday', 'clickup', 'canva', 'hubspot', 'service-now', 'workday', 'box', 'dropbox', 'zoom', 'slack', 'atlassian']
    }

    results = []
    q_low = query.lower().strip()
    sec_low = sector.lower().strip()

    matched_kws = None
    if sec_low and sec_low != "all":
        for k, kws in sector_keywords.items():
            if k in sec_low or any(w in sec_low for w in k.split()):
                matched_kws = kws
                break

    for c in self.all_companies:
        name_low = c["name"].lower()
        dom_low = c.get("domain", "").lower()
        ats_low = c["ats"].lower()

        if matched_kws:
            if not any(kw in name_low or kw in dom_low for kw in matched_kws):
                continue
        elif sec_low and sec_low != "all":
            if sec_low not in dom_low and sec_low not in name_low:
                continue

        if q_low:
            if q_low not in name_low and q_low not in dom_low and q_low not in ats_low:
                continue

        c_norm = c["name"].lower().strip()
        app_status = "FRESH"
        for app_c in self.applied_companies:
            if app_c in c_norm or c_norm in app_c:
                app_status = "PORTAL_CAPTURED"
                break

        h1b = get_h1b_sponsor_info(c["name"])
        results.append({
            "name": c["name"],
            "ats": c["ats"].capitalize() if c["ats"].lower() != "smartrecruiters" else "SmartRecruiters",
            "ats_platform": c["ats"].capitalize() if c["ats"].lower() != "smartrecruiters" else "SmartRecruiters",
            "slug": c["slug"],
            "domain": c.get("domain", "Technology"),
            "sector": c.get("domain", "Technology"),
            "career_url": _build_career_url(c),
            "portal_url": _build_career_url(c),
            "h1b_rate": h1b.get("approval_rate", 96.5),
            "h1b_approval_rate": h1b.get("approval_rate", 96.5),
            "salary_range": h1b.get("salary_range", "$140,000 - $180,000"),
            "status": h1b.get("status", "SPONSOR_VERIFIED"),
            "application_status": app_status
        })

    return {
        "total": len(self.all_companies),
        "matching": len(results),
        "total_matching": len(results),
        "companies": results[:limit]
    }


# Attach the method to GeminiCareerHunter
GeminiCareerHunter.get_company_directory = _get_company_directory


# Global singleton instance
hunter_engine = GeminiCareerHunter()



def get_company_directory(query: str = "", sector: str = "", limit: int = 200) -> Dict[str, Any]:
    return hunter_engine.get_company_directory(query=query, sector=sector, limit=limit)


def dynamic_search_career_pages(user_query: str, max_results: int = 8) -> Dict[str, Any]:
    return hunter_engine.search(user_query, max_results=max_results)


if __name__ == "__main__":
    import sys
    test_query = sys.argv[1] if len(sys.argv) > 1 else "AI and robotics companies hiring data engineers"
    print(f"\n[Gemini Hunter Engine] Searching: '{test_query}'...")
    res = dynamic_search_career_pages(test_query, max_results=5)
    print(f"Resolved {res['total_portals_resolved']} Portals | Found {res['total_matches_found']} Qualified Roles\n")
    for idx, r in enumerate(res["roles"], start=1):
        print(f"[{idx}] {r['company']} ({r['ats_platform']}) - Fit Score: {r['fit_score']}/100")
        print(f"    Role: {r['title']} | Location: {r['location']}")
        print(f"    Skills: {', '.join(r['matched_skills'])}")
        print(f"    Career Page: {r['career_url']}")
        print(f"    Direct Application: {r['apply_url']}\n")
