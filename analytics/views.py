# analytics/views.py
import os, sys, uuid, threading, queue, subprocess, shlex, json

from django.shortcuts import render, redirect
from django.contrib import messages
from urllib.parse import urlparse

from .forms import SupaSignupForm, SupaLoginForm
from core.supa import get_supabase

from pathlib import Path
from django.http import StreamingHttpResponse, JsonResponse, HttpResponseRedirect
from .services.upload import upload_json_to_supabase

from django.utils import timezone

from .models import Repository, Analysis
from core.supa import get_supabase
from subprocess import PIPE, STDOUT


BASE_DIR = Path(__file__).resolve().parents[1]
MINER_PATH = BASE_DIR / "analytics" / "services" / "miner.py"
assert MINER_PATH.exists(), f"miner.py not found at {MINER_PATH}"

JOBS = {}


# -------- helper: require Supabase login (checks session token) --------
def require_supabase_login(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.session.get("sb_access_token"):
            return redirect("login")
        return view_func(request, *args, **kwargs)
    return wrapper


# --------------------------- SIGN UP ---------------------------
def signup(request):
    # If already logged in (Supabase), skip signup page
    if request.session.get("sb_access_token"):
        return redirect("home")

    if request.method == "POST":
        form = SupaSignupForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"]
            email = form.cleaned_data["email"]
            password = form.cleaned_data["password1"]

            sb = get_supabase()
            try:
                # Save username in user_metadata
                resp = sb.auth.sign_up({
                    "email": email,
                    "password": password,
                    "options": {"data": {"username": username}},
                })
                # On error, the client raises; no resp.error
            except Exception as e:
                messages.error(request, f"Sign up failed: {e}")
                return render(request, "registration/signup.html", {"form": form})

            messages.success(request, "Sign up successful. Please log in.")
            return redirect("login")
    else:
        form = SupaSignupForm()

    return render(request, "registration/signup.html", {"form": form})


# --------------------------- LOGIN ---------------------------
def login_view(request):
    if request.session.get("sb_access_token"):
        return redirect("home")

    if request.method == "POST":
        form = SupaLoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            password = form.cleaned_data["password"]

            sb = get_supabase()
            try:
                resp = sb.auth.sign_in_with_password({"email": email, "password": password})
            except Exception as e:
                messages.error(request, f"Login failed: {e}")
                return render(request, "registration/login.html", {"form": form})

            session = getattr(resp, "session", None)
            user = getattr(resp, "user", None)
            if not session or not user:
                messages.error(
                    request,
                    "Login succeeded but no session returned. If email confirmation is enabled, verify your email first."
                )
                return render(request, "registration/login.html", {"form": form})

            # Build a SAFE, SERIALIZABLE dict (strings only)
            # Avoid model_dump(); pick only what you need.
            user_dict = {
                "id": str(getattr(user, "id", "")),
                "email": getattr(user, "email", None),
                "user_metadata": getattr(user, "user_metadata", {}) or {},
            }

            # Tokens are strings; do not store entire session model
            request.session["sb_access_token"] = getattr(session, "access_token", "")
            request.session["sb_refresh_token"] = getattr(session, "refresh_token", "")
            request.session["sb_user"] = user_dict

            return redirect("home")
    else:
        form = SupaLoginForm()

    return render(request, "registration/login.html", {"form": form})


# --------------------------- LOGOUT ---------------------------
def logout_view(request):
    # Optionally you can also call sb.auth.sign_out() here
    for k in ("sb_access_token", "sb_refresh_token", "sb_user"):
        request.session.pop(k, None)
    return redirect("login")


# --------------------------- HOME (protected) ---------------------------
@require_supabase_login
def home(request):
    user = request.session.get("sb_user")  # {'id': <uuid>, 'email': ..., 'user_metadata': {...}}
    return render(request, "analytics/home.html", {"user": user})

def _repo_name_from_url(repo_url: str) -> str:
    # https://github.com/owner/repo(.git) -> "repo"
    path = urlparse(repo_url).path.strip("/")
    parts = path.split("/")
    if len(parts) < 2:
        raise ValueError("Invalid GitHub URL")
    name = parts[1]
    if name.endswith(".git"):
        name = name[:-4]
    return name

def _uuid_from_session(sb_user) -> uuid.UUID:
    # request.session["sb_user"]["id"] is a string UUID from Supabase
    return uuid.UUID(str(sb_user.get("id")))


# --------------------------- ANALYZE REPO (protected) ---------------------------
def _enqueue(job_id, line):
    JOBS[job_id]["q"].put(line.rstrip())

def _start_background_job(repo: Repository, sb_user_uuid: uuid.UUID) -> str:
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "q": queue.Queue(),     # <-- Queue, not list
        "done": False,
        "ok": None,
        "public_url": None,
    }
    t = threading.Thread(
        target=_run_miner_and_upload,
        args=(job_id, repo, sb_user_uuid),
        daemon=True
    )
    t.start()
    return job_id


def _run_miner_and_upload(job_id: str, repo: Repository, sb_user_uuid: uuid.UUID):
    _enqueue(job_id, f"Starting analysis for {repo.url} …")

    cmd = [sys.executable, "-u", str(MINER_PATH), repo.url]

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    proc = subprocess.Popen(
        cmd,
        cwd=str(BASE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,                  # same as universal_newlines=True
        encoding="utf-8",           # <-- force UTF-8 decode
        errors="replace",           # <-- never crash on odd bytes
        shell=False,
        env=env,
    )

    for line in proc.stdout:
        _enqueue(job_id, line)
    code = proc.wait()

    if code != 0:
        _enqueue(job_id, f"Miner exited with code {code}")
        JOBS[job_id].update(done=True, ok=False)
        return

    # Find the generated analytics.json (your miner writes to cloned_repos/<repo_name>/analytics.json)
    clones = BASE_DIR / "cloned_repos"
    candidate1 = clones / repo.name / "analytics.json"
    # (Optionally search more paths if your miner nests further.)

    if not candidate1.exists():
        _enqueue(job_id, "analytics.json not found.")
        JOBS[job_id].update(done=True, ok=False)
        return

    # Upload to Supabase Storage under user namespace
    object_name = f"{sb_user_uuid}/{repo.name}/analytics.json"
    try:
        public_url = upload_json_to_supabase(str(candidate1), object_name)
        _enqueue(job_id, f"Uploaded to Supabase → {public_url}")
        JOBS[job_id].update(public_url=public_url, ok=True)
    except Exception as e:
        _enqueue(job_id, f"Upload failed: {e}")
        JOBS[job_id].update(done=True, ok=False)
        return

    # Create an Analysis row for this run
    Analysis.objects.create(
        user_id=sb_user_uuid,
        repository=repo,
        mined_at=timezone.now(),
        json_url=public_url,
        # Optionally: parse candidate1 to compute quick summary stats:
        # summary={"ci": {"success": X, "failure": Y, ...}, "total_commits": N}
    )

    JOBS[job_id]["done"] = True
    _enqueue(job_id, "DONE")

@require_supabase_login
def analyze_repo(request):
    if request.method != "POST":
        return redirect("home")

    sb_user = request.session.get("sb_user") or {}
    try:
        sb_user_uuid = _uuid_from_session(sb_user)
    except Exception:
        messages.error(request, "Invalid Supabase session.")
        return redirect("login")

    repo_url = request.POST.get("repo_url", "").strip()
    if not repo_url:
        messages.error(request, "Please enter a repository URL.")
        return redirect("home")

    try:
        repo_name = _repo_name_from_url(repo_url)
    except Exception:
        messages.error(request, "Invalid GitHub URL. Expected https://github.com/<owner>/<repo>")
        return redirect("home")

    # Upsert repo per user (unique_together = owner_id + name)
    repo, created = Repository.objects.get_or_create(
        owner_id=sb_user_uuid,
        name=repo_name,
        defaults={"url": repo_url},
    )
    if not created:
        # keep URL fresh if they pasted a different canonical URL
        if repo.url != repo_url:
            repo.url = repo_url
            repo.save(update_fields=["url", "updated_at"] if hasattr(repo, "updated_at") else ["url"])

    # Kick off background worker and redirect to progress view
    job_id = _start_background_job(repo, sb_user_uuid)
    return redirect("progress", job_id=job_id)


@require_supabase_login
def stream_progress(request, job_id: str):
    if job_id not in JOBS:
        return JsonResponse({"error": "unknown job"}, status=404)

    q = JOBS[job_id]["q"]

    def gen():
        yield "retry: 1000\n\n"
        while True:
            try:
                line = q.get(timeout=1)
                yield f"data: {line}\n\n"
            except queue.Empty:
                if JOBS[job_id]["done"]:
                    payload = {
                        "ok": JOBS[job_id]["ok"],
                        "public_url": JOBS[job_id]["public_url"],
                    }
                    yield "event: finished\n"
                    yield f"data: {json.dumps(payload)}\n\n"
                    break

    resp = StreamingHttpResponse(gen(), content_type="text/event-stream; charset=utf-8")
    resp["Cache-Control"] = "no-cache"
    return resp

@require_supabase_login
def progress_page(request, job_id: str):
    if job_id not in JOBS:
        return redirect("home")
    return render(request, "analytics/progress.html", {"job_id": job_id})

@require_supabase_login
def my_analyses(request):
    sb_user = request.session.get("sb_user") or {}
    sb_user_uuid = uuid.UUID(str(sb_user.get("id")))
    rows = (
        Analysis.objects
        .filter(user_id=sb_user_uuid)
        .select_related("repository")
        .order_by("-mined_at")
    )
    return render(request, "analytics/my_analyses.html", {"analyses": rows})
