"""
Jarvis AI Technical & System Design Interview Kit Generator
Generates authoritative, company-tailored interview preparation kits for every applied role.
Features:
- Company domain architecture & system design deep-dives
- Python backend & data engineering technical patterns
- Behavioral STAR responses mapped strictly to candidate Naga Satya Phanindra Vallabhaneni's authentic credentials
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any

from config import (
    CANDIDATE_NAME,
    CANDIDATE_EMAIL,
    CANDIDATE_PHONE,
    CANDIDATE_LOCATION,
    RESUMES_DIR
)
from h1b_radar import get_h1b_sponsor_info

logger = logging.getLogger("JarvisJobAgent.InterviewPrep")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def generate_interview_kit(company: str, title: str, job_description: str = "") -> str:
    """
    Synthesizes a comprehensive, high-caliber interview briefing and cheat sheet.
    """
    clean_company = company.strip().replace("/", "_").replace("\\", "_")
    company_dir = RESUMES_DIR / "by_company" / clean_company
    company_dir.mkdir(parents=True, exist_ok=True)
    out_file = company_dir / f"Interview_Prep_{clean_company}.md"

    h1b_info = get_h1b_sponsor_info(company, title)

    # Domain specific system design prompt selection
    comp_lower = company.lower()
    if any(k in comp_lower for k in ["stripe", "brex", "ramp", "plaid", "block", "chime", "mercury"]):
        system_design_title = "Distributed High-Throughput Idempotent Payment & Ledger Engine"
        system_design_desc = (
            "Design a globally distributed payment transaction pipeline with strict ACID guarantees, "
            "zero double-spending via Redis-based idempotency keys, and asynchronous ledger audit replication."
        )
        arch_details = (
            "- **Idempotency Gate:** SHA-256 hash of payload stored in Redis with 120s TTL and distributed locking (Redlock).\n"
            "- **API Gateway:** FastAPI microservices validating JWT tokens with rate-limiting via Token Bucket.\n"
            "- **Event Broker:** Apache Kafka topic `tx.initiated` partitioned by `account_id` ensuring sequential consistency.\n"
            "- **Double-Entry Ledger:** PostgreSQL with serializable isolation, immutable audit logs, and async batching."
        )
    elif any(k in comp_lower for k in ["scale", "anthropic", "openai", "cursor", "elevenlabs", "anyscale"]):
        system_design_title = "Foundation Model High-Velocity Training & Inference Serving Pipeline"
        system_design_desc = (
            "Design a distributed model inference orchestration layer handling 50k RPS with dynamic batching, "
            "token streaming over gRPC/WebSockets, and real-time telemetry."
        )
        arch_details = (
            "- **Inference Routing:** Envoy proxy performing priority load balancing across Ray/vLLM GPU worker clusters.\n"
            "- **Batching Engine:** Continuous dynamic batching queue minimizing GPU idle time and memory fragmentation.\n"
            "- **State & Context Caching:** Radix-tree KV-cache in distributed NVMe storage for prefix caching.\n"
            "- **Observability:** Prometheus metrics monitoring TTFT (Time-To-First-Token) and p99 generation latency."
        )
    else:
        system_design_title = "Distributed Real-Time Telemetry & Event Streaming Platform"
        system_design_desc = (
            "Design an event ingestion service handling millions of device/client heartbeats with sub-second OLAP queries."
        )
        arch_details = (
            "- **Ingestion Ingress:** High-performance Go / FastAPI endpoints receiving compressed protobuf payloads.\n"
            "- **Buffering Tier:** Kafka / Redpanda cluster with 3x replication factor.\n"
            "- **Analytical Storage:** ClickHouse column-store with MergeTree tables partitioned by event timestamp.\n"
            "- **Query Layer:** Governed REST & GraphQL endpoints with cached materialized views."
        )

    kit_content = f"""# Technical Interview Briefing Kit — {company}
**Target Role:** {title}  
**Candidate:** {CANDIDATE_NAME} ({CANDIDATE_LOCATION})  
**Contact:** {CANDIDATE_EMAIL} | {CANDIDATE_PHONE}  
**H-1B Sponsor Rating:** {h1b_info['approval_rate']}% Approval ({h1b_info['status']})  
**Certified LCA Salary Band:** {h1b_info['salary_range']} (Median: ${h1b_info['median_base']:,})  

---

## 1. Company Profile & Engineering Context
- **Organization:** {company}
- **Immigration Standing:** {h1b_info['policy_summary']}
- **Core Technology Ecosystem:** Python, Docker, Kubernetes, AWS/GCP, PostgreSQL, Redis, Distributed Microservices.

---

## 2. Company-Specific System Design Deep Dive

### Problem Statement: {system_design_title}
{system_design_desc}

### Architectural Blueprint:
```
[Client / External Ingress]
           │
           ▼
    [API Gateway / Auth]  ── (Redis Idempotency & Rate Limit)
           │
           ▼
 [FastAPI Microservices]
           │
    ┌──────┴────────────────────────┐
    ▼                               ▼
[Async Event Broker (Kafka)]   [Cache Layer (Redis)]
    │                               │
    ▼                               ▼
[Worker Consumer Pool]        [Primary Relational DB (PostgreSQL)]
    │
    ▼
[Analytical Columnar Store / Data Warehouse]
```

### Key Technical Trade-Offs to Articulate:
{arch_details}

---

## 3. Python & Backend Technical Questions (Live Coding Prep)

### Question 1: Distributed Concurrency & Rate Limiting
- **Prompt:** Implement a thread-safe token bucket rate limiter in Python using `asyncio` or Redis locks.
- **Key Concepts:** Atomic CAS (Compare-And-Swap), Redis Lua scripts, token regeneration math (`tokens = min(capacity, last_tokens + elapsed * fill_rate)`).
- **Phanindra's Anchor Project:** Relate to the rate-limiting and RBAC architecture built for institutional data queries at the University of Dayton.

### Question 2: Memory-Efficient Large Dataset Processing
- **Prompt:** How do you stream and transform 50GB of JSON telemetry data without exceeding 512MB RAM in Python?
- **Key Concepts:** Python generators (`yield`), `ijson` iterative parser, batch database commits (`execute_batch` / `COPY`), asyncio threadpools.
- **Phanindra's Anchor Project:** Relate to the scalable data pipelines engineered for Warner Bros. Discovery at Accenture Solutions.

---

## 4. STAR Behavioral Scripts (Candidate Experience Mapping)

### Scenario 1: "Describe a challenging technical problem you solved in production."
- **Situation:** At the University of Dayton, legacy relational databases containing sensitive student data had no standardized natural language interface or fine-grained audit trail.
- **Task:** Build a high-performance, secure backend microservice layer allowing AI assistants to query institutional records while strictly enforcing role-based access control (RBAC).
- **Action:** Engineered FastAPI and FastMCP microservice endpoints with query auditing, SQL injection prevention layers, and fine-tuned GPT-4.1 on Azure AI Foundry (lowering loss by 50.6%).
- **Result:** Successfully deployed production assistant (FlyerGPT) achieving 88% response accuracy and zero security leakage across 11,000+ active students.

### Scenario 2: "Tell me about a time you optimized system performance or reliability."
- **Situation:** At Accenture Solutions, Warner Bros. Discovery platform required high-throughput REST API integrations and reliable data transformation pipelines.
- **Task:** Eliminate latency bottlenecks during peak data sync windows without increasing cloud compute costs.
- **Action:** Containerized services using Docker, restructured synchronous REST bottlenecks into asynchronous pipeline workers, and implemented Redis caching for frequently requested catalog metadata.
- **Result:** Cut end-to-end data synchronization latency by over 35% and ensured 99.9% uptime during live media release events.

---

## 5. Recruiter Pitch & Strategic Closing Questions
When the interviewer asks: *"Do you have any questions for us?"* ask these high-signal questions:
1. *"How does the engineering team currently manage schema evolution and backwards compatibility across your distributed microservices?"*
2. *"What is the current bottleneck in your data ingestion/inference pipeline as your user volume scales this year?"*
3. *"How does the team balance shipping new features with technical debt and infrastructure reliability?"*

---
*Generated automatically by Jarvis Job Agent Interview Kit Engine for Naga Satya Phanindra Vallabhaneni.*
"""

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(kit_content)

    logger.info(f"Generated Interview Prep Kit: {out_file.name}")
    return str(out_file)


if __name__ == "__main__":
    print("\n--- JARVIS INTERVIEW PREP KIT TEST ---")
    p = generate_interview_kit("Scale AI", "Software Engineer, Platform")
    print(f"[OK] Generated Interview Kit at: {p}")
