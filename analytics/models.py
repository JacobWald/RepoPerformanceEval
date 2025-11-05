from django.db import models
from django.contrib.auth.models import User

class Repository(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="repositories")
    name = models.CharField(max_length=255)
    url = models.URLField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("owner", "name")

    def __str__(self):
        return f"{self.owner.username}/{self.name}"
