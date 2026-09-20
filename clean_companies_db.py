import json
from pathlib import Path

db_path = Path(r"d:\jarvis_job_agent\companies_database.json")
data = json.loads(db_path.read_text(encoding="utf-8"))

def build_direct_career_url(item):
    ats = (item.get("ats") or "greenhouse").lower()
    slug = (item.get("slug") or "").strip()
    name = (item.get("name") or "").strip()
    clean_slug = slug or name.lower().replace(" ", "").replace(".", "").replace("&", "")

    if "ashby" in ats:
        return f"https://jobs.ashbyhq.com/{clean_slug}"
    elif "greenhouse" in ats:
        return f"https://job-boards.greenhouse.io/{clean_slug}"
    elif "lever" in ats:
        return f"https://jobs.lever.co/{clean_slug}"
    elif "smartrecruiters" in ats:
        return f"https://jobs.smartrecruiters.com/{clean_slug}"
    elif "workday" in ats:
        return f"https://{clean_slug}.wd5.myworkdayjobs.com/Careers"
    else:
        return f"https://job-boards.greenhouse.io/{clean_slug}"

updated = 0
for item in data:
    url = item.get("career_url", "")
    if not url or "google.com" in url:
        item["career_url"] = build_direct_career_url(item)
        updated += 1

db_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Fixed {updated} companies in companies_database.json with direct career portals!")
