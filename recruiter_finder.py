"""
Jarvis Recruiter Discovery & 1-Click Gmail Draft Engine
Provides:
- 1-Click LinkedIn Boolean search queries for hiring managers and recruiters
- Inferred corporate email address syntax
- Direct 1-Click Gmail Compose links with pre-filled pitch and candidate credentials
"""

import urllib.parse
import re
from typing import Dict, Any, List

from config import (
    CANDIDATE_NAME,
    CANDIDATE_EMAIL,
    CANDIDATE_PHONE,
    CANDIDATE_LOCATION,
    CANDIDATE_LINKEDIN
)


def get_recruiter_intel(company: str, role_title: str = "Software Engineer") -> Dict[str, Any]:
    """
    Synthesizes recruiter search shortcuts, probable email patterns,
    and 1-click Gmail compose links.
    """
    clean_comp = re.sub(r"[^\w\s]", "", company).strip()
    encoded_comp = urllib.parse.quote_plus(clean_comp)
    encoded_role = urllib.parse.quote_plus(role_title)

    # 1. Targeted LinkedIn Boolean Search Shortcuts
    em_query = f'"{clean_comp}" AND ("Engineering Manager" OR "Software Engineering Manager" OR "Lead Engineer")'
    recruiter_query = f'"{clean_comp}" AND ("Technical Recruiter" OR "Talent Partner" OR "Lead Recruiter")'
    vp_query = f'"{clean_comp}" AND ("Head of Engineering" OR "Director of Engineering" OR "VP of Engineering")'

    linkedin_em_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote_plus(em_query)}"
    linkedin_recruiter_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote_plus(recruiter_query)}"
    linkedin_vp_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote_plus(vp_query)}"

    # 2. Inferred Corporate Email Domain
    domain_slug = clean_comp.lower().replace(" ", "")
    common_patterns = [
        f"recruiting@{domain_slug}.com",
        f"careers@{domain_slug}.com",
        f"engineering-jobs@{domain_slug}.com"
    ]

    # 3. Personalized Cold Email Pitch Draft
    email_subject = f"Application for {role_title} — {CANDIDATE_NAME}"
    email_body = f"""Hi Team,

I recently applied for the {role_title} position at {company} and wanted to briefly share why my background is a strong fit.

I am a Python backend & ML engineer (M.S. in Computer Science from University of Dayton, GPA 3.68/4.0) with 3+ years of production experience:
• Built REST API integrations and scalable data pipeline services for Warner Bros. Discovery at Accenture Solutions.
• Engineered FastAPI microservices with role-based access control (RBAC) and query auditing over sensitive institutional data at the University of Dayton.
• Fine-tuned GPT-4.1 on Azure AI Foundry to 88% accuracy (50.6% loss reduction) for an institutional assistant serving 11,000+ students.

I would welcome the opportunity to discuss how my technical skills in Python, Docker, and distributed systems can support {company}'s engineering goals.

Resume PDF is attached for your review.

Best regards,

{CANDIDATE_NAME}
{CANDIDATE_PHONE} | {CANDIDATE_EMAIL}
{CANDIDATE_LOCATION}""" + (f" | {CANDIDATE_LINKEDIN}" if CANDIDATE_LINKEDIN else " | Open to US Remote & Relocation") + """
"""

    # 4. Direct 1-Click Gmail Compose Link
    encoded_subj = urllib.parse.quote_plus(email_subject)
    encoded_body = urllib.parse.quote_plus(email_body)
    gmail_compose_url = f"https://mail.google.com/mail/?view=cm&fs=1&to={common_patterns[0]}&su={encoded_subj}&body={encoded_body}"

    # 5. LinkedIn 1-Click Connection Note (< 300 characters)
    linkedin_note = (
        f"Hi! I applied for {role_title} at {company}. I have 3+ yrs experience building Python REST APIs & data pipelines "
        f"(Warner Bros. Discovery @ Accenture & Univ. of Dayton MS CS). Would love to connect and share my background! - Phanindra"
    )[:299]

    return {
        "company": company,
        "role_title": role_title,
        "linkedin_searches": {
            "engineering_manager": linkedin_em_url,
            "technical_recruiter": linkedin_recruiter_url,
            "engineering_leadership": linkedin_vp_url
        },
        "email_patterns": common_patterns,
        "gmail_compose_url": gmail_compose_url,
        "email_subject": email_subject,
        "email_body": email_body,
        "linkedin_connection_note": linkedin_note
    }


if __name__ == "__main__":
    print("\n--- JARVIS RECRUITER DISCOVERY TEST ---")
    data = get_recruiter_intel("Scale AI", "Software Engineer, Platform")
    print(f"[OK] Company: {data['company']}")
    print(f"[OK] EM Search: {data['linkedin_searches']['engineering_manager']}")
    print(f"[OK] Recruiter Search: {data['linkedin_searches']['technical_recruiter']}")
    print(f"[OK] 1-Click Gmail Link: {data['gmail_compose_url'][:80]}...")
    print(f"[OK] LinkedIn Note ({len(data['linkedin_connection_note'])} chars): {data['linkedin_connection_note']}")
