from django.contrib import admin

from agent.models import Finding, Repository, ResearchSession, ToolCall


@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "url", "last_analyzed_at", "updated_at")
    search_fields = ("name", "url")


@admin.register(ResearchSession)
class ResearchSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "repository", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("question",)


@admin.register(ToolCall)
class ToolCallAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "tool_name", "created_at")
    list_filter = ("tool_name",)


@admin.register(Finding)
class FindingAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "file_path", "created_at")
