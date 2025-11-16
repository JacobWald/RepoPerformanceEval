import sys
import git
import os
import json
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter
from urllib.parse import urlparse
from dotenv import load_dotenv
load_dotenv()

from pydriller import Repository
from tqdm import tqdm

# GitHub CI service
from github_ci import (
    owner_from_url,
    fetch_workflow_runs_covering,
    summarize_runs_by_sha,
)

import sys, io
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

performanceData = {}

# -----------------------------
# Helpers
# -----------------------------
def repo_name_from_url(url: str) -> str:
    path = urlparse(url).path
    name = path.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    performanceData["repo_name"] = name
    return name

def ensure_repo_fresh(dest):
    """
    If repo already exists, fetch latest refs so PyDriller sees
    all recent commits (no checkout/reset needed).
    """
    try:
        repo = git.Repo(dest)
        # fetch + prune removes stale remote refs
        repo.git.fetch("--all", "--prune")
        # optional: fetch tags too
        repo.git.fetch("--tags", "--prune")
        print("↪ Updated existing clone (fetch --all --prune).")
    except Exception as e:
        print(f"⚠ Failed to update existing repo: {e}")

def weekday_name(dt):
    return dt.strftime("%A")  # e.g., 'Monday'

def iso_week_bucket(dt):
    iso = dt.isocalendar()  # (year, week, weekday)
    year = iso[0]
    week = iso[1]
    return f"{year}-W{week:02d}"

def date_str(dt):
    return dt.strftime("%Y-%m-%d")

def compute_average_streak(unique_dates_sorted):
    """
    Streak = consecutive calendar days with >=1 commit.
    Returns average streak length across all streaks (at least 1 per isolated day).
    """
    if not unique_dates_sorted:
        return 0.0
    streaks = []
    current_streak = 1
    for i in range(1, len(unique_dates_sorted)):
        if unique_dates_sorted[i] == unique_dates_sorted[i - 1] + timedelta(days=1):
            current_streak += 1
        else:
            streaks.append(current_streak)
            current_streak = 1
    streaks.append(current_streak)
    return sum(streaks) / len(streaks)


# -----------------------------
# Main
# -----------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <repo_url>")
        sys.exit(1)

    days_env = os.getenv("MINER_DAYS", "90")
    try:
        DAYS = max(1, int(days_env))
    except ValueError:
        DAYS = 90

    repoLink = sys.argv[1].strip()
    repo_dir = repo_name_from_url(repoLink)
    dest = os.path.join(".", "cloned_repos", repo_dir)
    os.makedirs(dest, exist_ok=True)

    print(f"Cloning repo {repoLink} into {dest}...")
    git_dir = os.path.join(dest, ".git")

    if os.path.isdir(git_dir):
        print(f"↪ Already exists at {dest}, skipping clone.\n")
        ensure_repo_fresh(dest)
        print()
    else:
        try:
            git.Repo.clone_from(repoLink, dest)
            print(f"✓ Cloned {repoLink} successfully.\n")
        except Exception as e:
            if os.path.isdir(git_dir):
                print("⚠ Clone reported an error but .git exists; accepting repo.\n")
            else:
                print(f"✗ Error cloning {repoLink}: {e}\n")

    print(f"Commencing commit checks in {dest}.\n")

    # Top-level structure
    results = {
        "repo_name": repo_dir,
        "project_path": os.path.abspath(dest),
        "mined_at": datetime.now(timezone.utc).isoformat(),
        "mining_params": {
            "source": "PyDriller",
            "in_main_branch_only": False,
            "days_window": DAYS,
        },
        "authors": []
    }

    # Author aggregator keyed by (name, email)
    authors = {}

    # Repo-level aggregates (Project Overview)
    days_of_week = [
        "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday"
    ]
    repo_total_insertions = 0
    repo_total_deletions = 0
    repo_weekday_commits = Counter({d: 0 for d in days_of_week})
    repo_weekday_insertions = Counter({d: 0 for d in days_of_week})
    repo_weekday_deletions = Counter({d: 0 for d in days_of_week})
    repo_daily_commits = defaultdict(int)  # YYYY-MM-DD -> commit count

    # -----------------------------
    # First pass: gather SHAs within window (naive/UTC-naive for PyDriller filter)
    # -----------------------------
    since_for_repo = datetime.now() - timedelta(days=DAYS)

    target_shas = set()
    earliest = None
    latest = None
    total_commits = 0

    repo_pass1 = Repository(dest, since=since_for_repo)
    for c in repo_pass1.traverse_commits():
        total_commits += 1
        target_shas.add(c.hash)
        ad = c.author_date
        if earliest is None or ad < earliest:
            earliest = ad
        if latest is None or ad > latest:
            latest = ad

    if total_commits == 0:
        print("No commits found in the specified window. Exiting.")
        out_path = os.path.join(dest, "analytics.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"✓ Wrote empty analytics to: {out_path}")
        return

    # Normalize earliest to timezone-aware UTC for CI paging cutoff
    if earliest.tzinfo is None:
        cutoff_dt = earliest.replace(tzinfo=timezone.utc)
    else:
        cutoff_dt = earliest.astimezone(timezone.utc)

    # -----------------------------
    # Prefetch CI runs until coverage or cutoff
    # -----------------------------
    owner = owner_from_url(repoLink)
    HARD_PAGE_CAP = int(os.getenv("CI_HARD_PAGE_CAP", "100"))  # tune as needed for huge repos

    print("\n🔍 Fetching workflow runs from GitHub (dynamic coverage)…")
    print(f"  Repo: {owner}/{repo_dir}")
    print(f"  Targeting last {DAYS} days of commits (~{len(target_shas)} SHAs)")
    print(f"  Page cap: {HARD_PAGE_CAP}\n")

    ci_runs, covered = [], set()
    pbar = tqdm(desc="CI pages", unit="page")
    current_event = None

    def _on_ci_page(page, page_runs, total_runs, covered_count):
        pbar.update(1)
        pbar.set_postfix_str(
            f"event={current_event}  page={page}  "
            f"new_runs={page_runs}  total={total_runs}  "
            f"covered={covered_count}/{len(target_shas)}"
        )

    # -----------------------------
    # Fetch both push and PR CI runs
    # -----------------------------
    ci_runs, covered = [], set()

    # Push events
    current_event = "push"
    print(f"  • Fetching event={current_event} …")
    push_runs, push_covered = fetch_workflow_runs_covering(
        owner=owner,
        repo=repo_dir,
        cutoff_dt=cutoff_dt,
        target_shas=target_shas,
        hard_page_cap=HARD_PAGE_CAP,
        on_page=_on_ci_page,
        event="push",
    )

    # PR events
    current_event = "pull_request"
    print(f"\n  • Fetching event={current_event} …")
    pr_runs, pr_covered = fetch_workflow_runs_covering(
        owner=owner,
        repo=repo_dir,
        cutoff_dt=cutoff_dt,
        target_shas=target_shas,
        hard_page_cap=HARD_PAGE_CAP,
        on_page=_on_ci_page,
        event="pull_request",
    )

    # Merge results (already filtered to main repo in github_ci)
    ci_runs = push_runs + pr_runs
    covered = push_covered | pr_covered

    pbar.close()

    print(f"\n✅ Completed CI fetch: {len(ci_runs)} total runs covering {len(covered)} / {len(target_shas)} SHAs.\n")

    ci_index = summarize_runs_by_sha(ci_runs)

    # -----------------------------
    # CI coverage metrics (commit-level)
    # -----------------------------
    # SHAs that have at least one Actions run (from ci_index)
    shas_with_ci = set(ci_index.keys())
    # Limit to commits in our analysis window
    covered_commits_set = shas_with_ci & target_shas
    ci_covered_commits = len(covered_commits_set)

    if total_commits > 0:
        ci_coverage_ratio = ci_covered_commits / total_commits
    else:
        ci_coverage_ratio = 0.0

    # -----------------------------
    # Second pass: traverse commits and build records with CI info
    # -----------------------------
    repo_pass2 = Repository(dest, since=since_for_repo)
    for commit in tqdm(
        repo_pass2.traverse_commits(),
        total=total_commits,
        desc="Analyzing commits",
        unit="commit"
    ):
        ad = commit.author_date
        author_name = commit.author.name if commit.author and commit.author.name else "Unknown"
        author_email = commit.author.email if commit.author and commit.author.email else "unknown@example.com"
        key = (author_name, author_email)

        # Initialize author bucket
        if key not in authors:
            authors[key] = {
                "name": author_name,
                "email": author_email,
                "commits": [],
                # Aggregations
                "weekly_frequency": defaultdict(int),   # YYYY-Www -> count
                "weekday_frequency": Counter(
                    {day: 0 for day in days_of_week}
                ),
                "daily_frequency": defaultdict(int),    # YYYY-MM-DD -> count
                "total_insertions": 0,
                "total_deletions": 0,
                "total_files_changed": 0,
                "commit_dates_set": set(),              # for streaks
                # New per-dev aggregates
                "weekday_insertions": Counter({day: 0 for day in days_of_week}),
                "weekday_deletions": Counter({day: 0 for day in days_of_week}),
                "ci_conclusions_totals": Counter(),    # success/failure/skipped/etc across runs
                # For PR count: distinct PR head SHAs
                "pr_head_shas": set(),
            }

        # Core commit metadata + temporal features
        author_hour = ad.hour
        author_weekday = weekday_name(ad)
        week_bucket = iso_week_bucket(ad)
        day_key = date_str(ad)
        files_changed = len(commit.modified_files)

        insertions = commit.insertions or 0
        deletions = commit.deletions or 0

        # CI attachment (from runs index)
        ci = None
        if commit.hash in ci_index:
            ci = ci_index[commit.hash]

        latest_conclusion = None
        latest_url = None
        latest_event = None
        if ci and ci.get("latest_run"):
            latest_conclusion = (ci["latest_run"].get("conclusion") or "").lower()
            latest_url = ci["latest_run"].get("html_url")
            latest_event = ci["latest_run"].get("event")

        commit_record = {
            "hash": commit.hash,
            "msg": commit.msg or "",
            "author": {
                "name": author_name,
                "email": author_email,
            },
            "committer": {
                "name": commit.committer.name if commit.committer else None,
                "email": commit.committer.email if commit.committer else None,
            },
            "author_date": commit.author_date.isoformat(),
            "committer_date": commit.committer_date.isoformat() if commit.committer_date else None,
            "in_main_branch": bool(commit.in_main_branch),
            "is_merge": bool(commit.merge),
            "insertions": insertions,
            "deletions": deletions,
            "files_changed": files_changed,
            "author_hour": author_hour,                 # 0-23
            "author_weekday": author_weekday,          # Monday..Sunday
            # CI summary for this commit
            "ci": ci or {"has_actions_runs": False},
            # Convenience fields for your dashboard
            "ci_result": latest_conclusion,            # e.g., "success", "failure", ...
            "ci_url": latest_url,                      # link to latest Actions run if any
        }

        authors[key]["commits"].append(commit_record)

        # -------------------------
        # Author-level aggregations
        # -------------------------
        authors[key]["weekly_frequency"][week_bucket] += 1
        authors[key]["weekday_frequency"][author_weekday] += 1
        authors[key]["daily_frequency"][day_key] += 1
        authors[key]["total_insertions"] += insertions
        authors[key]["total_deletions"] += deletions
        authors[key]["total_files_changed"] += files_changed
        authors[key]["commit_dates_set"].add(day_key)

        # Per-dev lines added/deleted per weekday (Mon-Sun)
        authors[key]["weekday_insertions"][author_weekday] += insertions
        authors[key]["weekday_deletions"][author_weekday] += deletions

        # Per-dev CI totals (success/failure/skipped/etc. across runs)
        if ci and ci.get("has_actions_runs"):
            for status, cnt in ci.get("conclusions_tally", {}).items():
                if cnt:
                    authors[key]["ci_conclusions_totals"][status] += cnt

        # Per-dev PR count (distinct PR head SHAs in this window)
        if latest_event == "pull_request":
            authors[key]["pr_head_shas"].add(commit.hash)

        # -------------------------
        # Repo-level aggregations
        # -------------------------
        repo_total_insertions += insertions
        repo_total_deletions += deletions
        repo_weekday_commits[author_weekday] += 1
        repo_weekday_insertions[author_weekday] += insertions
        repo_weekday_deletions[author_weekday] += deletions
        repo_daily_commits[day_key] += 1

    # -----------------------------
    # CI repo-level aggregates
    # -----------------------------
    ci_status_totals = Counter()               # success/failure/etc across all runs
    ci_weekly_success_failure = defaultdict(
        lambda: {"success": 0, "failure": 0}
    )                                          # week -> {success, failure}
    failure_day_commit_counts = {}             # YYYY-MM-DD -> commit count on days with failing runs

    for run in ci_runs:
        concl = (run.get("conclusion") or "").lower()
        if concl:
            ci_status_totals[concl] += 1

        ts = run.get("updated_at") or run.get("created_at")
        if ts:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            week_bucket = iso_week_bucket(dt)
            if concl in ("success", "failure"):
                ci_weekly_success_failure[week_bucket][concl] += 1

            if concl == "failure":
                day_key = date_str(dt)
                # "How many commits were on the day of a failure?"
                failure_day_commit_counts[day_key] = repo_daily_commits.get(day_key, 0)

    # -----------------------------
    # Finalize author aggregates
    # -----------------------------
    finalized_authors = []
    for (_name, _email), data in authors.items():
        # Average streak days
        unique_dates = sorted(
            datetime.strptime(d, "%Y-%m-%d").date() for d in data["commit_dates_set"]
        )
        avg_streak = compute_average_streak(unique_dates)

        finalized_authors.append({
            "name": data["name"],
            "email": data["email"],
            "commit_count": len(data["commits"]),
            "total_insertions": data["total_insertions"],
            "total_deletions": data["total_deletions"],
            "total_files_changed": data["total_files_changed"],
            "weekly_frequency": dict(sorted(data["weekly_frequency"].items())),  # sort by key for readability
            # Commits per weekday (Mon-Sun)
            "weekday_frequency": dict(data["weekday_frequency"]),
            # Lines added/deleted per weekday (Mon-Sun)
            "weekday_insertions": dict(data["weekday_insertions"]),
            "weekday_deletions": dict(data["weekday_deletions"]),
            # Daily commit counts (YYYY-MM-DD)
            "daily_frequency": dict(sorted(data["daily_frequency"].items())),
            # Average streak length
            "average_streak_days": avg_streak,
            # CI totals per dev (success/failure/skipped/etc)
            "ci_conclusions_totals": dict(data["ci_conclusions_totals"]),
            # PR count per dev (distinct PR head SHAs in this window)
            "pr_count": len(data["pr_head_shas"]),
            # Full commit list
            "commits": data["commits"],
        })

    results["authors"] = finalized_authors

    all_pr_head_shas = set()
    for data in authors.values():
        all_pr_head_shas.update(data["pr_head_shas"])
    total_prs = len(all_pr_head_shas)

    # -----------------------------
    # Finalize repo summary (Project Overview)
    # -----------------------------
    # Average commits per "active" day (days with >=1 commit)
    active_days = len(repo_daily_commits)
    if active_days > 0:
        avg_commits_per_active_day = total_commits / active_days
    else:
        avg_commits_per_active_day = 0.0

    results["repo_summary"] = {
        # Total commits for repo
        "total_commits": total_commits,
        # Total lines added & deleted for repo
        "total_insertions": repo_total_insertions,
        "total_deletions": repo_total_deletions,
        # Time bounds
        "min_author_date": earliest.isoformat() if earliest else None,
        "max_author_date": latest.isoformat() if latest else None,
        # CI-level aggregates
        "total_ci_runs": len(ci_runs),
        "ci_status_totals": dict(ci_status_totals),  # totals for each CI status
        "ci_covered_commits": ci_covered_commits,       
        "ci_coverage_ratio": ci_coverage_ratio, 
        # Commits per day-of-week (Mon-Sun)
        "weekday_commits": dict(repo_weekday_commits),
        # Lines added & deleted per day-of-week (Mon-Sun)
        "weekday_insertions": dict(repo_weekday_insertions),
        "weekday_deletions": dict(repo_weekday_deletions),
        # Success & failure counts per week (YYYY-Www)
        "ci_weekly_success_failure": {
            week: data for week, data in sorted(ci_weekly_success_failure.items())
        },
        # Commits per day vs failures per day:
        # - average commits per active day
        # - commit counts on calendar days with failing CI runs
        "avg_commits_per_active_day": avg_commits_per_active_day,
        "failure_day_commit_counts": dict(sorted(failure_day_commit_counts.items())),
        # Total developer count (authors in this window)
        "total_developers": len(finalized_authors),
        "total_prs": total_prs,
    }

    out_path = os.path.join(dest, "analytics.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Mining complete. Wrote JSON to: {out_path}")


if __name__ == "__main__":
    main()
