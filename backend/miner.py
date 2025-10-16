import sys
import git
import os
import git
import json
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter
from pydriller import Repository
from tqdm import tqdm
from urllib.parse import urlparse

performanceData = {}

def repo_name_from_url(url: str) -> str:
    path = urlparse(url).path         
    name = path.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    performanceData["repo_name"] = name
    return name

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
        if unique_dates_sorted[i] == unique_dates_sorted[i-1] + timedelta(days=1):
            current_streak += 1
        else:
            streaks.append(current_streak)
            current_streak = 1
    streaks.append(current_streak)
    return sum(streaks) / len(streaks)

def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <repo_url_or_textfile_url>")
        sys.exit(1)

    repoLink = sys.argv[1].strip()
    repo_dir = repo_name_from_url(repoLink)
    dest = os.path.join(".", "cloned_repos", repo_dir)

    os.makedirs(dest, exist_ok=True)

    print(f"Cloning repo {repoLink} into {dest}...")
    git_dir = os.path.join(dest, ".git")

    if os.path.isdir(git_dir):
        print(f"↪ Already exists at {dest}, skipping clone.\n")
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
        },
        "authors": []  # will be filled after aggregation
    }

    # Author aggregator keyed by (name, email)
    authors = {}  # (name,email) -> dict

    since = datetime.now() - timedelta(days=365)  # last 10 years
    total_commits = sum(1 for _ in Repository(dest, since=since).traverse_commits())
    repo = Repository(dest, since=since)
    earliest = None
    latest = None

    for commit in tqdm(repo.traverse_commits(), total=total_commits, desc="Analyzing commits", unit="commit"):

        # Track mining time bounds (using author_date by default)
        ad = commit.author_date
        if earliest is None or ad < earliest:
            earliest = ad
        if latest is None or ad > latest:
            latest = ad

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
                "weekday_frequency": Counter({day: 0 for day in
                                              ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]}),
                "daily_frequency": defaultdict(int),    # YYYY-MM-DD -> count
                "total_insertions": 0,
                "total_deletions": 0,
                "total_files_changed": 0,
                "commit_dates_set": set(),              # for streaks
            }

        # Core commit metadata + temporal features
        author_hour = ad.hour
        author_weekday = weekday_name(ad)
        week_bucket = iso_week_bucket(ad)
        day_key = date_str(ad)
        files_changed = len(commit.modified_files)

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
            "insertions": commit.insertions or 0,
            "deletions": commit.deletions or 0,
            "files_changed": files_changed,
            # Temporal features
            "author_hour": author_hour,                 # 0-23
            "author_weekday": author_weekday,          # Monday..Sunday
            # File-level details (diff overview)
        }

        authors[key]["commits"].append(commit_record)

        # Aggregations
        authors[key]["weekly_frequency"][week_bucket] += 1
        authors[key]["weekday_frequency"][author_weekday] += 1
        authors[key]["daily_frequency"][day_key] += 1
        authors[key]["total_insertions"] += (commit.insertions or 0)
        authors[key]["total_deletions"] += (commit.deletions or 0)
        authors[key]["total_files_changed"] += files_changed
        authors[key]["commit_dates_set"].add(day_key)

    # Finalize author aggregates (convert structures & compute average streaks)
    finalized_authors = []
    for (_name, _email), data in authors.items():
        # Average streak days
        unique_dates = sorted(datetime.strptime(d, "%Y-%m-%d").date() for d in data["commit_dates_set"])
        avg_streak = compute_average_streak(unique_dates)

        finalized_authors.append({
            "name": data["name"],
            "email": data["email"],
            "commit_count": len(data["commits"]),
            "total_insertions": data["total_insertions"],
            "total_deletions": data["total_deletions"],
            "total_files_changed": data["total_files_changed"],
            "weekly_frequency": dict(sorted(data["weekly_frequency"].items())),  # sort by key for readability
            "weekday_frequency": dict(data["weekday_frequency"]),
            "daily_frequency": dict(sorted(data["daily_frequency"].items())),
            "average_streak_days": avg_streak,
            "commits": data["commits"],
        })

    results["authors"] = finalized_authors
    results["repo_summary"] = {
        "total_commits": total_commits,
        "min_author_date": earliest.isoformat() if earliest else None,
        "max_author_date": latest.isoformat() if latest else None,
    }

    out_path = os.path.join(dest, "analytics.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Mining complete. Wrote JSON to: {out_path}")

if __name__ == "__main__":
    main()
