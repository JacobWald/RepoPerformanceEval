from django.contrib import admin
from .models import Repository

@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "url", "created_at")
    search_fields = ("name", "owner__username", "url")
