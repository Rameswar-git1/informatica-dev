
import requests
import os
import json
import time
import sys

# Environment variables
URL = os.environ.get('IICS_POD_URL')
SESSION_ID = os.environ.get('sessionId')
COMMIT_HASH = os.environ.get('COMMIT_HASH')

if not URL or not SESSION_ID or not COMMIT_HASH:
    print("Missing required environment variables.")
    sys.exit(1)

HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "INFA-SESSION-ID": SESSION_ID
}
HEADERS_V2 = {
    "Content-Type": "application/json; charset=utf-8",
    "icSessionId": SESSION_ID
}

print(f" Getting all objects for the commit: {COMMIT_HASH}")

# Get all the objects for the commit
try:
    r = requests.get(f"{URL}/public/core/v3/commit/{COMMIT_HASH}", headers=HEADERS)
    r.raise_for_status()
    request_json = r.json()
except Exception as e:
    print(f" Failed to fetch commit data: {e}")
    sys.exit(99)

# Filter only Mapping Tasks
r_filtered = [x for x in request_json.get('changes', []) if x.get('type') == 'MTT']

if not r_filtered:
    print(" No Mapping Tasks (MTT) found in the commit.")
    sys.exit(0)

# Run tests for each Mapping Task
for task in r_filtered:
    task_id = task.get('appContextId')
    if not task_id:
        print(" Skipping task with missing appContextId.")
        continue

    print(f" Triggering job for task ID: {task_id}")
    body = {"@type": "job", "taskId": task_id, "taskType": "MTT"}

    try:
        t = requests.post(f"{URL}/api/v2/job/", headers=HEADERS_V2, json=body)
        t.raise_for_status()
        test_json = t.json()
    except Exception as e:
        print(f" Failed to trigger job: {e}")
        sys.exit(99)

    run_id = test_json.get('runId')
    task_id = test_json.get('taskId')
    if not run_id or not task_id:
        print(" Missing runId or taskId in job response.")
        sys.exit(99)

    print(f" Monitoring job runId: {run_id}, taskId: {task_id}")
    params = f"?runId={run_id}&taskId={task_id}"

    state = 0
    retries = 0
    max_retries = 5

    while state == 0 and retries < max_retries:
        time.sleep(200)
        try:
            a = requests.get(f"{URL}/api/v2/activity/activityLog{params}", headers=HEADERS_V2)
            a.raise_for_status()
            activity_log = a.json()
        except Exception as e:
            print(f"Attempt {retries + 1}:  Error fetching activity log: {e}")
            retries += 1
            continue

        if isinstance(activity_log, list) and activity_log:
            log_entry = activity_log[0]
            state = log_entry.get('state', 0)
            object_name = log_entry.get('objectName', 'Unknown Task')
            print(f" Attempt {retries + 1}: Task '{object_name}' state = {state}")
        else:
            print(f" Attempt {retries + 1}: Activity log empty or malformed: {activity_log}")
            retries += 1

    if retries == max_retries:
        print(" Activity log not available after multiple attempts.")
        sys.exit(99)

    if state != 1:
        print(f" Mapping task '{object_name}' failed.")
        sys.exit(99)
    else:
        print(f" Mapping task '{object_name}' completed successfully.")

# Logout
try:
    requests.post(f"{URL}/public/core/v3/logout", headers=HEADERS)
    print(" Logged out successfully.")
except Exception as e:
    print(f" Logout failed: {e}")
