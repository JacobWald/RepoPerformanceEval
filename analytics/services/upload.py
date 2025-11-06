from core.supa import get_supabase
import os

def upload_json_to_supabase(local_path: str, object_name: str) -> str:
    sb = get_supabase(admin=True)  # service role recommended for server-side
    bucket = os.environ.get("SUPABASE_BUCKET", "commit-data")

    with open(local_path, "rb") as f:
        sb.storage.from_(bucket).upload(
            object_name,
            f,  # or f.read()
            file_options={
                "content-type": "application/json",  # or "contentType"
                "upsert": "true",                    # <-- STRING, not True
                # optional: "cache-control": "3600"
            },
        )

    return sb.storage.from_(bucket).get_public_url(object_name)
