# core/supa.py
import os
from supabase import create_client

def get_supabase(admin: bool = False):
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY" if admin else "SUPABASE_ANON_KEY"]
    return create_client(url, key)
