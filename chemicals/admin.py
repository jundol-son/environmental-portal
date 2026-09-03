from django.contrib import admin

from .models import CompletionSubmissionLog, HandlerProfile, TrainingCompletion


@admin.register(HandlerProfile)
class HandlerProfileAdmin(admin.ModelAdmin):
    list_display = ("knoxid", "name", "department", "is_active", "updated_at")
    list_filter = ("is_active", "department")
    search_fields = ("knoxid", "name", "department")


@admin.register(TrainingCompletion)
class TrainingCompletionAdmin(admin.ModelAdmin):
    list_display = (
        "target_year",
        "handler",
        "is_completed",
        "completion_code",
        "completed_at",
    )
    list_filter = ("target_year", "is_completed", "handler__department")
    search_fields = ("handler__knoxid", "handler__name", "completion_code")
    readonly_fields = ("is_completed", "completed_at")


@admin.register(CompletionSubmissionLog)
class CompletionSubmissionLogAdmin(admin.ModelAdmin):
    list_display = ("completion", "completion_code", "submitted_by", "submitted_at")
    search_fields = (
        "completion__handler__knoxid",
        "completion__handler__name",
        "completion_code",
    )
    readonly_fields = ("completion", "completion_code", "submitted_by", "submitted_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
