from django.contrib import admin
from .models import AuditLog

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "resource_type", "actor_email", "organization", "created_at")
    list_filter = ("action", "resource_type")
    search_fields = ("actor_email", "description")
    readonly_fields = ("id", "actor", "actor_email", "organization", "action", "resource_type", "resource_id", "description", "metadata", "ip_address", "created_at")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False