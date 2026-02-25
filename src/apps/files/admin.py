from django.contrib import admin
from src.apps.files.models import File

@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    list_display = ("original_file_name", "file_type", "file_size", "uploaded_by", "upload_finished_at")
    list_filter = ("file_type",)
    search_fields = ("original_file_name", "file_name")
    readonly_fields = ("file_name", "file_size", "upload_finished_at", "created_at", "updated_at")