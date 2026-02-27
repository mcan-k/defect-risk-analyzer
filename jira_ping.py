import os
import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv()

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

def fetch_bugs():
    search_url = f"{JIRA_BASE_URL}/rest/api/3/search/jql"
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json"}

    params = {
        "jql": "project = AP AND issuetype = Bug ORDER BY created DESC",
        "maxResults": 10,
        "fields": "summary,status,priority,components"
    }

    response = requests.get(search_url, headers=headers, auth=auth, params=params)
    data = response.json()

    total = data.get("total", 0)
    print(f"Toplam bug: {total}\n")

    for issue in data.get("issues", []):
        fields = issue["fields"]
        print(f"Key      : {issue['key']}")
        print(f"Özet     : {fields['summary']}")
        print(f"Durum    : {fields['status']['name']}")
        print(f"Öncelik  : {fields['priority']['name']}")
        print("-" * 40)

if __name__ == "__main__":
    fetch_bugs()