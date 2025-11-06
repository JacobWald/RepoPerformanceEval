from django.contrib import admin
from .models import Repository, Analysis

@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ("name", "owner_id", "url", "created_at")
    search_fields = ("name", "url")
    list_filter = ("created_at",)

@admin.register(Analysis)
class AnalysisAdmin(admin.ModelAdmin):
    list_display = ("repository", "user_id", "mined_at", "json_url")
    search_fields = ("repository__name", "json_url")
    list_filter = ("mined_at",)
