import os
import time
import requests
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

GITHUB_API = "https://api.github.com"


# -----------------------------
# Helpers
# -----------------------------
def owner_from_url(url: str) -> str:
    """
    Extract the GitHub owner/org from a repo URL.
    e.g., https://github.com/tensorflow/tensorflow -> 'tensorflow'
    """
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    if len(parts) < 2:
        raise ValueError(f"Cannot parse owner/repo from URL: {url}")
    return parts[0]


def _headers():
    token = os.getenv("GITHUB_TOKEN")
    h = {"Accept": "application/vnd.github+json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _sleep_until_reset(resp) -> bool:
    """
    If truly rate-limited, sleep until GitHub says to reset.
    Returns True if we slept (and caller should retry), else False.
    """
    try:
        remaining = int(resp.headers.get("X-RateLimit-Remaining", "1"))
        reset_unix = int(resp.headers.get("X-RateLimit-Reset", "0"))
    except ValueError:
        return False

    now = int(time.time())
    if remaining <= 0 and reset_unix > now:
        sleep_s = max(0, reset_unix - now) + 1
        print(f"⏳ Rate limit reached. Sleeping {sleep_s}s until reset…")
        time.sleep(sleep_s)
        return True
    return False


def _get(url, params=None, max_retries=4, base_sleep=2, timeout=30):
    """
    GET with simple retry, 403 rate-limit handling, and 5xx backoff.
    """
    for i in range(max_retries):
        r = requests.get(url, headers=_headers(), params=params, timeout=timeout)
        # Explicit rate-limit handling
        if r.status_code == 403:
            if _sleep_until_reset(r):
                continue
            time.sleep(base_sleep * (i + 1))
            continue
        # Retry transient 5xx
        if 500 <= r.status_code < 600:
            time.sleep(base_sleep * (i + 1))
            continue

        r.raise_for_status()
        # If near limit, this may sleep a bit to avoid immediate next-failure
        _sleep_until_reset(r)
        return r
    r.raise_for_status()


# -----------------------------
# Actions Workflow Runs (dynamic coverage)
# -----------------------------
def fetch_workflow_runs_covering(
    owner: str,
    repo: str,
    cutoff_dt: datetime,
    target_shas: set,
    hard_page_cap: int = 100,
    on_page=None,
    event: Optional[str] = None,
    branch: Optional[str] = None,  
):
    # ... cutoff setup ...

    all_runs = []
    covered = set()
    page = 1
    repo_full = f"{owner}/{repo}"

    while page <= hard_page_cap:
        params = {"per_page": 100, "page": page}
        if event:  params["event"] = event     # e.g., "push"
        if branch: params["branch"] = branch   # e.g., "main"

        r = _get(f"{GITHUB_API}/repos/{owner}/{repo}/actions/runs", params=params)
        data = r.json()

        runs = data.get("workflow_runs", [])
        if not runs:
            if on_page:
                on_page(page, 0, len(all_runs), len(covered))
            break

        all_runs.extend(runs)

        oldest = None
        for run in runs:
            # Skip fork PR runs unless they’re for this repo
            head_repo = (run.get("head_repository") or {}).get("full_name")
            if head_repo and head_repo != repo_full:
                continue

            sha = run.get("head_sha")
            if sha in target_shas:
                covered.add(sha)

            ts = run.get("updated_at") or run.get("created_at")
            if ts:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
                if oldest is None or dt < oldest:
                    oldest = dt

        if on_page:
            on_page(page, len(runs), len(all_runs), len(covered))

        if covered.issuperset(target_shas):
            print(f"  ✓ Covered all target SHAs using {page} page(s).")
            break
        if oldest and oldest < cutoff_dt:
            print(f"  ✓ Encountered runs older than cutoff on page {page}. Stopping.")
            break

        page += 1

    return all_runs, covered


def summarize_runs_by_sha(workflow_runs):
    """
    Collapse multiple workflow runs by head_sha → one summary per commit SHA.
    Keeps a 'latest_run' (most recently updated/created) and tallies conclusions.
    """
    by_sha = {}
    for run in workflow_runs:
        sha = run.get("head_sha")
        if not sha:
            continue

        d = by_sha.setdefault(
            sha,
            {
                "has_actions_runs": True,
                "runs_count": 0,
                "latest_run": None,
                "conclusions_tally": {
                    "success": 0,
                    "failure": 0,
                    "cancelled": 0,
                    "timed_out": 0,
                    "skipped": 0,
                    "neutral": 0,
                    "action_required": 0,
                },
            },
        )
        d["runs_count"] += 1

        concl = (run.get("conclusion") or "").lower()
        if concl in d["conclusions_tally"]:
            d["conclusions_tally"][concl] += 1

        # pick the most recent run as "latest"
        latest = d["latest_run"]
        old_ts = latest.get("updated_at") if latest else None
        new_ts = run.get("updated_at") or run.get("created_at")
        is_newer = (old_ts is None) or (new_ts and old_ts and new_ts > old_ts)

        if is_newer:
            d["latest_run"] = {
                "id": run.get("id"),
                "name": run.get("name"),
                "event": run.get("event"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "created_at": run.get("created_at"),
                "updated_at": run.get("updated_at"),
                "html_url": run.get("html_url"),
                "head_branch": run.get("head_branch"),
                "workflow_id": run.get("workflow_id"),
            }

    return by_sha
