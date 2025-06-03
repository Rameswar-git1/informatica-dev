
# This sample source code is offered only as an example of what can or might be built using the IICS Github APIs,
# and is provided for educational purposes only. This source code is provided "as-is"
# and without representations or warrantees of any kind, is not supported by Informatica.
# Users of this sample code in whole or in part or any extraction or derivative of it
# assume all the risks attendant thereto, and Informatica disclaims any/all liabilities
# arising from any such use to the fullest extent permitted by law.

import requests
import os
import json
import time
import sys

URL = os.environ['IICS_POD_URL']
UAT_SESSION_ID = os.environ['uat_sessionId']
UAT_COMMIT_HASH = os.environ['UAT_COMMIT_HASH']

HEADERS = {"Content-Type": "application/json; charset=utf-8", "INFA-SESSION-ID": UAT_SESSION_ID }
HEADERS_V2 = {"Content-Type": "application/json; charset=utf-8", "icSessionId": UAT_SESSION_ID }

BODY={ "commitHash": UAT_COMMIT_HASH }

print("Syncing the commit " + UAT_COMMIT_HASH + " to the UAT repo")

# Sync Github and UAT Org
p = requests.post(URL + "/public/core/v3/pullByCommitHash", headers = HEADERS, json=BODY)

if p.status_code != 200:
    print(f"Exception caught during initial pullByCommitHash: Status Code {p.status_code}, Response: {p.text}")
    sys.exit(99)

pull_json = p.json()
PULL_ACTION_ID = pull_json.get('pullActionId') # Use .get() for safer access

if not PULL_ACTION_ID:
    print("ERROR: 'pullActionId' not found in the initial pull response.")
    print(f"Response: {pull_json}")
    sys.exit(99)

PULL_STATUS = 'IN_PROGRESS'
MAX_RETRIES = 10 # Add a max retry limit to prevent infinite loops
retry_count = 0

while PULL_STATUS == 'IN_PROGRESS' and retry_count < MAX_RETRIES:
    print("Getting pull status from Informatica...")
    time.sleep(10)
    ps = requests.get(URL + '/public/core/v3/sourceControlAction/' + PULL_ACTION_ID, headers = HEADERS, json=BODY)

    if ps.status_code != 200:
        print(f"Exception caught during pull status check: Status Code {ps.status_code}, Response: {ps.text}")
        sys.exit(99)

    try:
        pull_status_json = ps.json()
        PULL_STATUS = pull_status_json.get('status', {}).get('state') # Safely get nested state
        print(f"DEBUG: Current PULL_STATUS: {PULL_STATUS}")
        print(f"DEBUG: Full Pull Status JSON: {pull_status_json}")
    except json.JSONDecodeError:
        print(f"ERROR: Failed to decode JSON from pull status response. Raw response: {ps.text}")
        sys.exit(99)
    except AttributeError: # Handles cases where pull_status_json.get('status') might not be a dict
        print(f"ERROR: Unexpected structure in pull status JSON. Full response: {pull_status_json}")
        sys.exit(99)

    if PULL_STATUS is None:
        print("WARNING: 'status.state' not found in pull status response. Assuming failure or incomplete response.")
        print(f"Full response: {pull_status_json}")
        sys.exit(99) # Exit if state is not found

    retry_count += 1

if PULL_STATUS != 'SUCCESSFUL':
    print(f'Exception caught: Pull was not successful. Final status: {PULL_STATUS}')
    sys.exit(99)

print("Pull operation completed successfully.")

# Get all the objects for commit
r = requests.get(URL + "/public/core/v3/commit/" + UAT_COMMIT_HASH, headers = HEADERS)

if r.status_code != 200:
    print(f"Exception caught during commit object retrieval: Status Code {r.status_code}, Response: {r.text}")
    sys.exit(99)

try:
    request_json = r.json()
except json.JSONDecodeError:
    print(f"ERROR: Failed to decode JSON from commit object response. Raw response: {r.text}")
    sys.exit(99)

# Only get Mapping Tasks
r_filtered = [x for x in request_json.get('changes', []) if ( x.get('type') == 'MTT') ] # Use .get() for safer access

if not r_filtered:
    print("WARNING: No Mapping Tasks (MTT) found in the commit changes.")
    # You might want to exit here or continue depending on your workflow
    # For now, let's allow it to continue if no MTTs are found, but it won't run tests.

# This loop runs tests for each one of the mapping tasks
for x in r_filtered:
    task_id = x.get('appContextId')
    object_name = x.get('objectName', 'Unknown Task') # Get objectName for better logging

    if not task_id:
        print(f"WARNING: Skipping task '{object_name}' due to missing 'appContextId'. Full task data: {x}")
        continue # Skip to the next task if ID is missing

    BODY = {"@type": "job","taskId": task_id,"taskType": "MTT"}
    print(f"Attempting to run test for Mapping Task: {object_name} (ID: {task_id})")
    t = requests.post(URL + "/api/v2/job/", headers = HEADERS_V2, json = BODY )

    if t.status_code != 200:
        print(f"Exception caught when starting test for {object_name}: Status Code {t.status_code}, Response: {t.text}")
        sys.exit(99)

    try:
        test_json = t.json()
    except json.JSONDecodeError:
        print(f"ERROR: Failed to decode JSON from test start response for {object_name}. Raw response: {t.text}")
        sys.exit(99)

    run_id = test_json.get('runId')
    if not run_id:
        print(f"ERROR: 'runId' not found in test start response for {object_name}. Response: {test_json}")
        sys.exit(99)

    PARAMS = f"?taskId={task_id}&runId={run_id}"  # <-- PATCHED LINE

    STATE = 0
    test_retry_count = 0
    MAX_TEST_RETRIES = 10 # Max retries for individual test status checks

    while STATE == 0 and test_retry_count < MAX_TEST_RETRIES:
        time.sleep(60)
        print(f"Checking activity log for runId: {run_id} (Task: {object_name})...")
        print(f"DEBUG: Fetching activity log from: {URL + '/api/v2/activity/activityLog' + PARAMS}")  # <-- NEW DEBUG LINE
        a = requests.get(URL + "/api/v2/activity/activityLog" + PARAMS, headers = HEADERS_V2)

        if a.status_code != 200:
            print(f"Exception caught when getting activity log for {object_name}: Status Code {a.status_code}, Response: {a.text}")
            sys.exit(99)

        try:
            activity_log = a.json()
            print(f"DEBUG: Raw Activity Log JSON for {object_name}: {activity_log}") # Crucial debug print
        except json.JSONDecodeError:
            print(f"ERROR: Failed to decode JSON from activity log response for {object_name}. Raw response: {a.text}")
            sys.exit(99)

        # Check if activity_log is an empty list or doesn't have the expected structure
        if not isinstance(activity_log, list) or not activity_log:
            print(f"WARNING: Activity log for {object_name} is empty or not a list. Retrying...")
            STATE = 0 # Ensure loop continues if empty
        elif 'state' not in activity_log[0]:
            print(f"WARNING: 'state' key not found in first activity log entry for {object_name}. Full entry: {activity_log[0]}")
            STATE = 0 # Ensure loop continues if key is missing
        else:
            STATE = activity_log[0]['state']
            print(f"DEBUG: Current STATE for {object_name}: {STATE}")

        test_retry_count += 1

    if STATE != 1:
        if activity_log and isinstance(activity_log, list) and activity_log[0] and 'objectName' in activity_log[0]:
            print(f"Mapping task: {activity_log[0]['objectName']} failed. Final state: {STATE}")
        else:
            print(f"Mapping task: {object_name} failed or status could not be retrieved. Final state: {STATE}")
        sys.exit(99)
    else:
        print(f"Mapping task: {object_name} completed successfully. ")

requests.post(URL + "/public/core/v3/logout", headers = HEADERS)
print("Logged out from Informatica.")
