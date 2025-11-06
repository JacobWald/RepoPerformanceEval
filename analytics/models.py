from django.db import models
import uuid

class Repository(models.Model):
    # Supabase Auth user id (UUID)
    owner_id = models.UUIDField()  # stored from request.session["sb_user"]["id"]

    name = models.CharField(max_length=255)
    url = models.URLField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("owner_id", "name")

    def __str__(self):
        return f"{self.owner_id}/{self.name}"
    
class Analysis(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.UUIDField()  # Supabase Auth user id (UUID)
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name="analyses")

    mined_at = models.DateTimeField(auto_now_add=True)
    json_url = models.URLField()  # Public URL or Supabase storage path
    summary = models.JSONField(null=True, blank=True)  # Optional: quick stats

    def __str__(self):
        return f"{self.repository.name} analysis by {self.user_id} at {self.mined_at}"

