def supabase_auth(request):
    return {
        "sb_authenticated": bool(request.session.get("sb_access_token")),
        "sb_user": request.session.get("sb_user"),
    }
