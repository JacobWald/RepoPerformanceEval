# analytics/views.py

from django.shortcuts import render, redirect
from django.contrib import messages
from urllib.parse import urlparse

from .forms import SupaSignupForm, SupaLoginForm
from core.supa import get_supabase


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
    return render(request, "home.html", {"user": user})


# --------------------------- ANALYZE REPO (protected) ---------------------------
@require_supabase_login
def analyze_repo(request):
    if request.method != "POST":
        return redirect("home")

    repo_url = request.POST.get("repo_url", "").strip()
    name = repo_url

    # Pretty name like "owner/repo" if possible
    try:
        path = urlparse(repo_url).path.strip("/")
        if path.count("/") >= 1:
            owner, repo = path.split("/")[:2]
            name = f"{owner}/{repo}"
    except Exception:
        pass

    # Next steps (later): upsert repo in Supabase + upload JSON to Storage
    messages.success(request, f"Repo received: {name}")
    return redirect("home")
