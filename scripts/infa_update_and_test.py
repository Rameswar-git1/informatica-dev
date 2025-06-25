import requests
import os
import json
import time
import sys

# Validate required environment variables
required_env_vars = ['IICS_POD_URL', 'uat_sessionId', 'UAT_COMMIT_HASH', 'GH_TOKEN', 'GITHUB_REPO']
for var in required_env_vars:
    if not os.getenv(var):
        print(f"Missing required environment variable: {var}")
        sys.exit(1)

URL = os.environ['IICS_POD_URL']
UAT_SESSION_ID = os.environ['uat_sessionId']
UAT_COMMIT_HASH = os.environ['UAT_COMMIT_HASH']
GITHUB_TOKEN = os.environ['GH_TOKEN']
GITHUB_REPO = os.environ['GITHUB_REPO']

HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "INFA-SESSION-ID": UAT_SESSION_ID
}
HEADERS_V2 = {
    "Content-Type": "application/json; charset=utf-8",
    "icSessionId": UAT_SESSION_ID
}
BODY = {"commitHash": UAT_COMMIT_HASH}

# Function to check if commit exists in GitHub
def check_commit_in_github(repo, commit_hash, token):
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    url = f"https://api.github.com/repos/{repo}/commits/{commit_hash}"
    response = requests.get(url, headers=headers)
    return response.status_code == 200

# Check if the commit exists in GitHub
if not check_commit_in_github(GITHUB_REPO, UAT_COMMIT_HASH, GITHUB_TOKEN):
    print(f"Commit {UAT_COMMIT_HASH} not found in GitHub repository {GITHUB_REPO}.")
    sys.exit(1)

print(f"Syncing the commit {UAT_COMMIT_HASH} to the UAT repo")

# Retry logic for pullByCommitHash
for attempt in range(3):
    try:
        p = requests.post(f"{URL}/public/core/v3/pullByCommitHash", headers=HEADERS, json=BODY)
        if p.status_code == 200:
            break
        elif p.status_code == 404:
            print(f"Commit {UAT_COMMIT_HASH} not found. Attempt {attempt + 1}/3")
        elif p.status_code == 422:
            print("Unprocessable Entity: Possibly invalid commit hash or repo access issue.")
        else:
            print(f"Unexpected error: {p.status_code} - {p.text}")
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
    time.sleep(10)
else:
    print("All attempts to sync commit failed.")
    sys.exit(99)

pull_json = p.json()
PULL_ACTION_ID = pull_json.get('pullActionId')
PULL_STATUS = 'IN_PROGRESS'

# Poll for pull status
while PULL_STATUS == 'IN_PROGRESS':
    print("Getting pull status from Informatica...")
    time.sleep(10)
    ps = requests.get(f"{URL}/public/core/v3/sourceControlAction/{PULL_ACTION_ID}", headers=HEADERS)
    pull_status_json = ps.json()
    PULL_STATUS = pull_status_json['status']['state']

if PULL_STATUS != 'SUCCESSFUL':
    print('Exception caught: Pull was not successful')
    sys.exit(99)

# Get all the objects for commit
r = requests.get(f"{URL}/public/core/v3/commit/{UAT_COMMIT_HASH}", headers=HEADERS)
if r.status_code != 200:
    print("Exception caught while fetching commit details:")
    print(r.text)
    sys.exit(99)

request_json = r.json()
r_filtered = [x for x in request_json['changes'] if x['type'] == 'MTT']

# Run tests for each mapping task
for x in r_filtered:
    BODY = {
        "@type": "job",
        "taskId": x['appContextId'],
        "taskType": "MTT"
    }
    try:
        t = requests.post(f"{URL}/api/v2/job/", headers=HEADERS_V2, json=BODY)
        t.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to start job for task {x['name']}: {e}")
        sys.exit(99)

    test_json = t.json()
    PARAMS = f"?runId={test_json['runId']}"
    STATE = 0

    while STATE == 0:
        time.sleep(60)
        a = requests.get(f"{URL}/api/v2/activity/activityLog{PARAMS}", headers=HEADERS_V2)
        activity_log = a.json()
        STATE = activity_log[0]['state']
        if STATE != 1:
            print(f"Mapping task: {activity_log[0]['objectName']} failed.")
            sys.exit(99)
        else:
            print(f"Mapping task: {activity_log[0]['objectName']} completed successfully.")

# Logout
requests.post(f"{URL}/public/core/v3/logout", headers=HEADERS)
