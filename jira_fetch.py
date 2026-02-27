import os
import json
import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth
from datetime import datetime

load_dotenv()

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL    = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

def fetch_all_bugs(project_key: str = "AP"):
    search_url = f"{JIRA_BASE_URL}/rest/api/3/search/jql"
    auth       = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    headers    = {"Accept": "application/json"}

    all_bugs   = []
    start_at   = 0
    page_size  = 50

    print(f"'{project_key}' projesindeki tüm buglar çekiliyor...\n")

    while True:
        params = {
            "jql"        : f"project = {project_key} AND issuetype = Bug ORDER BY created DESC",
            "startAt"    : start_at,
            "maxResults" : page_size,
            "fields"     : "summary,description,status,priority,components,labels,created,updated,resolutiondate,assignee,reporter"
        }

        response = requests.get(search_url, headers=headers, auth=auth, params=params)
        response.raise_for_status()
        data = response.json()

        issues = data.get("issues", [])
        if not issues:
            break

        for issue in issues:
            fields = issue["fields"]

            # Açıklama metnini düzleştir (ADF veya düz metin)
            description = ""
            raw_desc = fields.get("description")
            if isinstance(raw_desc, dict):
                description = extract_text_from_adf(raw_desc)
            elif isinstance(raw_desc, str):
                description = raw_desc

            bug = {
                "key"         : issue["key"],
                "summary"     : fields.get("summary", ""),
                "description" : description,
                "status"      : fields["status"]["name"],
                "priority"    : fields["priority"]["name"] if fields.get("priority") else "Medium",
                "components"  : [c["name"] for c in fields.get("components", [])],
                "labels"      : fields.get("labels", []),
                "created"     : fields.get("created", ""),
                "updated"     : fields.get("updated", ""),
                "resolved"    : fields.get("resolutiondate", None),
                "assignee"    : fields["assignee"]["displayName"] if fields.get("assignee") else "Unassigned",
                "reporter"    : fields["reporter"]["displayName"] if fields.get("reporter") else "Unknown",
            }
            all_bugs.append(bug)
            print(f"  [OK] {bug['key']} | {bug['priority']} | {bug['summary'][:60]}")

        start_at += page_size

        # Tüm kayıtlar çekildiyse dur
        if start_at >= data.get("total", 0):
            break

    print(f"\nToplam {len(all_bugs)} bug cekildi.")
    return all_bugs


def extract_text_from_adf(node: dict) -> str:
    """Atlassian Document Format'tan düz metin çıkar."""
    texts = []

    def traverse(n):
        if n.get("type") == "text":
            texts.append(n.get("text", ""))
        for child in n.get("content", []):
            traverse(child)

    traverse(node)
    return " ".join(texts).strip()


def save_bugs(bugs: list, output_file: str = "data/bugs.json"):
    os.makedirs("data", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(bugs, f, ensure_ascii=False, indent=2)
    print(f"\nVeri kaydedildi: {output_file}")


if __name__ == "__main__":
    bugs = fetch_all_bugs(project_key="AP")
    save_bugs(bugs)