import datetime
import logging
import re
import shutil
from pathlib import Path
from typing import Dict, Any, Optional
from playwright.sync_api import sync_playwright, Browser
from config import (
    RESUMES_DIR,
    CANDIDATE_NAME,
    CANDIDATE_EMAIL,
    CANDIDATE_PHONE,
    CANDIDATE_LOCATION
)
from tailor import generate_recruiter_outreach

logger = logging.getLogger("JarvisJobAgent.PDFGen")

BY_COMPANY_DIR = RESUMES_DIR / "by_company"
BY_COMPANY_DIR.mkdir(parents=True, exist_ok=True)


def generate_resume_html(tailored_data: Dict[str, Any]) -> str:
    """Creates an authoritative, comprehensive 100% ATS-compliant HTML resume document."""
    name = CANDIDATE_NAME
    email = CANDIDATE_EMAIL
    phone = CANDIDATE_PHONE
    location = CANDIDATE_LOCATION
    title = tailored_data.get("tailored_title") or "Python Backend Engineer | Machine Learning Engineer"
    summary = tailored_data.get("professional_summary") or (
        "Python backend engineer with 3+ years of production experience and an M.S. in Computer Science, "
        "specializing in REST API development, data pipeline engineering, and applied machine learning. "
        "Built REST API integrations and scalable data pipelines for the Warner Bros. Discovery platform at Accenture, "
        "and engineered FastAPI microservices with role-based access control and audit logging over sensitive institutional "
        "data at the University of Dayton. Fine-tuned GPT-4.1 to 88% accuracy for a production LLM assistant serving 11,000+ students. "
        "IEEE-published researcher with hands-on experience across distributed systems, cloud infrastructure (AWS, Azure), and CI/CD."
    )

    # 1. Technical Skills (7 comprehensive categories)
    skills_dict = tailored_data.get("highlighted_skills", {})
    if not skills_dict:
        skills_dict = {
            "Languages": "Python, SQL, PL/SQL, Java, C/C++, JavaScript, PHP, Bash/Shell",
            "Backend & APIs": "FastAPI, FastMCP, Flask, REST API Design, Async I/O & Concurrency, Authentication & RBAC, CSRF Protection, WTForms",
            "Databases & Data Engineering": "PostgreSQL, MySQL, Schema Design & Normalization, Query Optimization, ETL Pipeline Design, Apache Spark, Hadoop (MapReduce), HDFS, Hive",
            "Machine Learning & AI": "GPT-4.1 Fine-Tuning, LLM Agent Integration, Model Context Protocol (MCP), Azure OpenAI, Azure AI Foundry, PyTorch, TensorFlow, Keras, Hugging Face Transformers, BERT, RoBERTa, Scikit-learn, Pandas, NumPy",
            "Cloud & DevOps": "AWS (EC2, S3, VPC, EBS), Azure, Docker, Jenkins, CI/CD Pipelines, Git/GitHub, Bitbucket",
            "Systems & Security": "Distributed Systems, Scalability, Fault Tolerance, Load Balancing, Multithreading, TLS/SSL, Data Leakage Prevention, Wireshark, OpenSSL",
            "Practices": "Agile/Scrum, Sprint Planning, QA & Regression Testing, Root-Cause Analysis, Code Review"
        }

    skills_html = ""
    for category, items in skills_dict.items():
        skills_html += f"""
        <div class="skill-row">
            <span class="skill-category">{category}:</span>
            <span class="skill-items">{items}</span>
        </div>
        """

    # 2. Professional Experience (University of Dayton, Accenture Solutions, LJ Technologies)
    experiences = tailored_data.get("experience", [])
    if not experiences:
        experiences = [
            {
                "company": "University of Dayton",
                "title": "AI Solutions Associate",
                "location": "Dayton, OH",
                "period": "Dec 2024 – May 2026",
                "bullets": [
                    "Engineered a FastAPI/FastMCP microservice (Affinaquest) exposing the university’s donor database through a governed, natural-language query layer — role-based access control, SQL-level query restrictions, connection audit logging, and async concurrency limits to prevent data leakage.",
                    "Built a reusable MCP agent framework with structured tool schemas, pluggable data-source connectors, and protocol-based query routing, standardizing how new AI integrations connected to institutional systems.",
                    "Built an end-to-end Python ETL pipeline that scraped, cleaned, and structured 4,400+ institutional Q&A records into JSONL for model training, with automated evaluation gating every release.",
                    "Fine-tuned GPT-4.1 on Azure AI Foundry over that dataset — 88% test accuracy, 50.6% loss reduction over baseline — and deployed the model behind a production service layer serving 11,000+ students; presented the system at Stander Symposium 2026."
                ]
            },
            {
                "company": "Accenture Solutions",
                "title": "Application Developer — Warner Bros. Discovery Platform",
                "location": "India",
                "period": "Oct 2022 – June 2024",
                "bullets": [
                    "Engineered REST API integrations and scalable data pipeline services in Python and Docker, powering high-throughput data delivery for the Warner Bros. Discovery platform’s global distribution partners.",
                    "Owned analytics platform integration and partner onboarding for NLCD end to end, validating inter-service communication, API contracts, and integration tests so new partners launched without data-flow failures.",
                    "Resolved high-impact performance bottlenecks by applying distributed computing patterns, data-structure optimization, and database query tuning, raising pipeline throughput and data retrieval speed.",
                    "Automated deployment across distributed teams with CI/CD pipelines in Jenkins, GitHub, and Docker, keeping release quality high on fast-moving sprint cycles.",
                    "Led fault-tolerance analysis and root-cause resolution on complex integration failures across DEV → QA → PROD, backed by QA, unit, and regression testing frameworks, cutting service downtime.",
                    "Built Python automation for metadata extraction and normalization, improving data accuracy and partner satisfaction."
                ]
            },
            {
                "company": "LJ Technologies",
                "title": "Data Engineer and Python Developer",
                "location": "India",
                "period": "Jan 2021 – July 2022",
                "bullets": [
                    "Developed automated data pipelines in Python and Pandas to ingest high-volume datasets into MySQL databases, eliminating manual data handling workflows.",
                    "Created lightweight REST web services in Flask to deliver real-time operational data to internal analytics dashboards.",
                    "Optimized relational SQL queries and table indexing architectures, reducing average query execution times by 30%.",
                    "Automated data synchronization, scheduled batch processing, and database backups using Bash scripts and Linux cron jobs."
                ]
            }
        ]

    experience_html = ""
    for exp in experiences:
        company = exp.get("company", "")
        exp_title = exp.get("title", "")
        period = exp.get("period", "")
        loc = exp.get("location", "")
        bullets = exp.get("bullets", [])
        bullets_li = "".join([f"<li>{b}</li>" for b in bullets])
        loc_span = f'<span class="job-location">{loc}</span>' if loc else ""
        experience_html += f"""
        <div class="job-entry">
            <div class="job-header">
                <span class="job-company">{company}</span>
                <span class="job-period">{period}</span>
            </div>
            <div class="job-subheader">
                <span class="job-title">{exp_title}</span>
                {loc_span}
            </div>
            <ul class="job-bullets">
                {bullets_li}
            </ul>
        </div>
        """

    # 3. Projects (Affinaquest MCP Server, FlyerGPT, Phishing URL Detection, Flask & PHP, Plant Yield ML)
    projects = tailored_data.get("projects", [])
    if not projects:
        projects = [
            {
                "name": "Affinaquest MCP Server — Governed Database API",
                "organization": "University of Dayton",
                "period": "2026",
                "tech": "Python, FastAPI, FastMCP, PostgreSQL, MySQL",
                "bullets": [
                    "FastAPI/FastMCP service exposing a production donor database through an access-controlled, natural-language query layer: RBAC, SQL-level restrictions, connection audit logging, async concurrency caps."
                ]
            },
            {
                "name": "FlyerGPT — Fine-Tuned LLM Assistant",
                "organization": "University of Dayton",
                "period": "2025 – 2026",
                "tech": "Python, Azure AI Foundry, Azure OpenAI, JSONL, BeautifulSoup4",
                "bullets": [
                    "Fine-tuned GPT-4.1 on Azure AI Foundry over 4,400+ curated Q&A records — 88% accuracy, 50.6% loss reduction — deployed to 11,000+ students through a Python service layer with automated evaluation gating."
                ]
            },
            {
                "name": "Phishing URL Detection with BERT & RoBERTa",
                "organization": "CPS579",
                "period": "2025",
                "tech": "Python, PyTorch, Hugging Face Transformers, Scikit-learn, TF-IDF",
                "bullets": [
                    "Fine-tuned BERT (95%) and RoBERTa (96%) on a 549,346-URL dataset, reaching an F1-score of 0.95 on malicious URL classification; stress-tested with prompt injection and adversarial robustness analysis."
                ]
            },
            {
                "name": "Full-Stack Web Applications — Flask & PHP Platforms",
                "organization": "Academic & Production",
                "period": "2021 – 2023",
                "tech": "Python, Flask, PHP, MySQL, Flask-WTF",
                "bullets": [
                    "Built a Flask social platform with modular routing, session-based authentication, CSRF protection, and normalized MySQL schemas; shipped a second PHP/MySQL platform with foreign-key relationships via Agile sprints."
                ]
            },
            {
                "name": "Plant Yield & Growth Prediction Using ML and DL",
                "organization": "GRIET",
                "period": "2021 – 2022",
                "tech": "Python, TensorFlow, Keras, Scikit-learn",
                "bullets": [
                    "Built LSTM and CNN models forecasting crop growth from multi-variable agricultural data; benchmarked against SVR, Random Forest, and MLP on MAE, RMSE, and R2. Published at IEEE ICEARS 2022; awarded Most Valuable Player for the undergraduate major project."
                ]
            }
        ]

    projects_html = ""
    for proj in projects:
        pname = proj.get("name", "")
        org = proj.get("organization", "")
        pperiod = proj.get("period", "")
        tech = proj.get("tech", "")
        bullets = proj.get("bullets", [])
        bullets_li = "".join([f"<li>{b}</li>" for b in bullets])
        header_right = f"{org}, {pperiod}" if org else pperiod
        tech_span = f'<div class="project-tech"><strong>Tools:</strong> {tech}</div>' if tech else ""
        projects_html += f"""
        <div class="project-entry">
            <div class="project-header">
                <span class="project-title">{pname}</span>
                <span class="project-period">{header_right}</span>
            </div>
            <ul class="job-bullets">
                {bullets_li}
            </ul>
            {tech_span}
        </div>
        """

    # 4. Education
    education_list = tailored_data.get("education", [])
    if not education_list:
        education_list = [
            {
                "institution": "University of Dayton",
                "degree": "M.S., Computer Science",
                "period": "Aug 2024 – May 2026",
                "location": "Dayton, OH",
                "gpa": "GPA 3.68",
                "honors": "Presenter, Stander Symposium 2026"
            },
            {
                "institution": "GRIET",
                "degree": "B.Tech, Electronics & Communication Engineering",
                "period": "Jul 2018 – May 2022",
                "location": "Hyderabad, India",
                "gpa": "GPA 7.37/10",
                "honors": "MVP, Undergraduate Major Project"
            }
        ]

    edu_html = ""
    for edu in education_list:
        inst = edu.get("institution", "")
        deg = edu.get("degree", "")
        period = edu.get("period", "")
        loc = edu.get("location", "")
        gpa = edu.get("gpa", "")
        honors = edu.get("honors", "")
        details_parts = [p for p in [gpa, honors, loc] if p]
        details_str = " | ".join(details_parts)
        edu_html += f"""
        <div class="edu-entry">
            <div class="edu-top">
                <div><span class="edu-inst">{inst}</span> &mdash; <span class="edu-degree">{deg}</span></div>
                <span class="edu-period">{period}</span>
            </div>
            <div class="edu-details">{details_str}</div>
        </div>
        """

    # 5. Publications & Certifications
    pub_cert = tailored_data.get("publications_certifications", {})
    pub_str = pub_cert.get("publication", "Plant Yield and Growth Prediction Using ML and DL Algorithms — IEEE, 2022 International Conference on Electronics and Renewable Systems (ICEARS).")
    certs = pub_cert.get("certifications", [
        "GitHub Foundations (GitHub Education, 2025)",
        "Oracle AI Foundations Associate",
        "NPTEL — Joy of Computing Using Python"
    ])
    certs_str = " | ".join(certs)

    pub_cert_html = f"""
    <div class="pub-cert-entry">
        <div class="pub-row"><strong>Publication:</strong> {pub_str}</div>
        <div class="cert-row"><strong>Certifications:</strong> {certs_str}</div>
    </div>
    """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
    @page {{
        size: letter;
        margin: 0.35in 0.45in;
    }}
    * {{
        box-sizing: border-box;
        margin: 0;
        padding: 0;
    }}
    body {{
        font-family: Arial, "Helvetica Neue", Helvetica, sans-serif;
        color: #1a1a1a;
        font-size: 9.5pt;
        line-height: 1.32;
        background: #ffffff;
    }}
    .header {{
        text-align: center;
        border-bottom: 2px solid #002244;
        padding-bottom: 5px;
        margin-bottom: 8px;
    }}
    .candidate-name {{
        font-size: 18pt;
        font-weight: bold;
        letter-spacing: 0.5px;
        color: #002244;
        text-transform: uppercase;
    }}
    .candidate-title {{
        font-size: 10.5pt;
        font-weight: bold;
        color: #003366;
        margin-top: 1px;
    }}
    .contact-line {{
        font-size: 9pt;
        color: #333333;
        margin-top: 3px;
    }}
    .contact-line a {{
        color: #003366;
        text-decoration: none;
    }}
    .section {{
        margin-bottom: 8px;
    }}
    .section-title {{
        font-size: 10.5pt;
        font-weight: bold;
        text-transform: uppercase;
        color: #002244;
        border-bottom: 1.2px solid #002244;
        padding-bottom: 1px;
        margin-bottom: 4px;
        letter-spacing: 0.4px;
    }}
    .summary-text {{
        font-size: 9.2pt;
        color: #222222;
        text-align: justify;
        line-height: 1.34;
    }}
    .skill-row {{
        margin-bottom: 2.5px;
        font-size: 9pt;
        line-height: 1.28;
    }}
    .skill-category {{
        font-weight: bold;
        color: #002244;
    }}
    .skill-items {{
        color: #222222;
    }}
    .job-entry, .project-entry, .edu-entry {{
        margin-bottom: 7px;
        page-break-inside: avoid;
        break-inside: avoid;
    }}
    .job-header, .project-header, .edu-top {{
        display: flex;
        justify-content: space-between;
        font-weight: bold;
        font-size: 9.8pt;
        color: #002244;
    }}
    .job-subheader {{
        display: flex;
        justify-content: space-between;
        font-size: 9.2pt;
        font-weight: 600;
        color: #333333;
        margin-bottom: 2px;
    }}
    .job-title {{
        font-style: italic;
    }}
    .job-period, .project-period, .edu-period {{
        font-weight: bold;
        color: #444444;
        font-size: 9pt;
    }}
    .job-location {{
        color: #555555;
        font-size: 9pt;
        font-weight: normal;
    }}
    .job-bullets {{
        margin-left: 18px;
    }}
    .job-bullets li {{
        margin-bottom: 2.5px;
        font-size: 9pt;
        color: #111111;
        text-align: justify;
        line-height: 1.3;
    }}
    .project-tech {{
        font-size: 8.8pt;
        color: #333333;
        margin-left: 18px;
        margin-top: 2px;
    }}
    .edu-entry {{
        margin-bottom: 4px;
    }}
    .edu-inst {{
        font-weight: bold;
        color: #002244;
    }}
    .edu-degree {{
        font-weight: 600;
        color: #222222;
    }}
    .edu-details {{
        font-size: 8.8pt;
        color: #555555;
        margin-top: 1px;
    }}
    .pub-cert-entry {{
        font-size: 9pt;
        line-height: 1.35;
        color: #222222;
    }}
    .pub-row, .cert-row {{
        margin-bottom: 3px;
    }}
    .pub-cert-entry strong {{
        color: #002244;
    }}
</style>
</head>
<body>

<div class="header">
    <div class="candidate-name">{name}</div>
    <div class="candidate-title">{title}</div>
    <div class="contact-line">
        {phone} &bull; <a href="mailto:{email}">{email}</a> &bull; {location}
    </div>
</div>

<div class="section">
    <div class="section-title">Professional Summary</div>
    <div class="summary-text">{summary}</div>
</div>

<div class="section">
    <div class="section-title">Technical Skills</div>
    {skills_html}
</div>

<div class="section">
    <div class="section-title">Professional Experience</div>
    {experience_html}
</div>

<div class="section">
    <div class="section-title">Projects</div>
    {projects_html}
</div>

<div class="section">
    <div class="section-title">Education</div>
    {edu_html}
</div>

<div class="section">
    <div class="section-title">Publications &amp; Certifications</div>
    {pub_cert_html}
</div>

</body>
</html>
"""
    return html


def compile_html_to_pdf(html_content: str, output_path: Path, browser: Optional[Browser] = None) -> Path:
    """Uses Playwright Chromium in a clean background thread to render HTML to high-fidelity PDF."""
    temp_html = output_path.with_suffix(".html")
    temp_html.write_text(html_content, encoding="utf-8")

    import threading
    err_box = [None]

    def _render_worker():
        try:
            with sync_playwright() as p:
                local_b = p.chromium.launch(headless=True)
                page = local_b.new_page()
                page.goto(temp_html.as_uri(), wait_until="networkidle")
                page.pdf(
                    path=str(output_path),
                    format="Letter",
                    print_background=True,
                    margin={"top": "0.4in", "bottom": "0.4in", "left": "0.45in", "right": "0.45in"}
                )
                local_b.close()
        except Exception as ex:
            err_box[0] = ex

    t = threading.Thread(target=_render_worker)
    t.start()
    t.join(timeout=15.0)

    if err_box[0]:
        raise err_box[0]

    logger.info(f"Compiled ATS-friendly PDF resume: {output_path.name}")
    return output_path


def generate_tailored_pdf(
    tailored_data: Dict[str, Any],
    company: str,
    job_title: str,
    domain: str = "Cloud & Data Infrastructure",
    browser: Optional[Browser] = None
) -> Path:
    """
    Generates tailored HTML and compiles it to PDF.
    Saves directly in organized company folder: resumes/by_company/<Company>/
    with exactly ONE authoritative resume PDF, HTML, and Recruiter Outreach note.
    Prevents loose duplicate clutter in the root folder.
    """
    clean_company = re.sub(r"[^\w\-_]", "_", company.strip())
    clean_title = re.sub(r"[^\w\-_]", "_", job_title.strip())

    # 1. Company dedicated folder
    company_folder = BY_COMPANY_DIR / clean_company
    company_folder.mkdir(parents=True, exist_ok=True)

    output_pdf = company_folder / f"Resume_{clean_company}_{clean_title[:25]}.pdf"
    html_content = generate_resume_html(tailored_data)
    compile_html_to_pdf(html_content, output_pdf, browser=browser)

    # 2. Recruiter outreach draft
    try:
        outreach_file = company_folder / f"Recruiter_Outreach_{clean_company}.txt"
        outreach_text = generate_recruiter_outreach(job_title, company, domain)
        outreach_file.write_text(outreach_text, encoding="utf-8")
        logger.info(f"Saved single perfect resume & recruiter outreach in: {company_folder}")
    except Exception as e:
        logger.warning(f"Could not write recruiter outreach: {e}")

    return output_pdf


def cleanup_loose_resumes():
    """
    Moves existing loose duplicate PDF and HTML files in resumes/ root
    into resumes/archive/ to clean up repository clutter and keep folder clean.
    """
    archive_dir = RESUMES_DIR / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    loose_files = list(RESUMES_DIR.glob("*.pdf")) + list(RESUMES_DIR.glob("*.html"))
    moved_count = 0
    for f in loose_files:
        try:
            target = archive_dir / f.name
            if target.exists():
                f.unlink()
            else:
                shutil.move(str(f), str(target))
            moved_count += 1
        except Exception:
            pass
    if moved_count > 0:
        logger.info(f"Cleaned up {moved_count} loose resume files into {archive_dir}")
