from django.contrib import admin
from .models import Certificate, CertificateVersion

class CertificateVersionInline(admin.TabularInline):
    model = CertificateVersion
    extra = 0
    readonly_fields = ("version_number", "fingerprint_sha256", "key_type", "key_curve", "not_valid_before", "not_valid_after", "created_at")

@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display = ("label", "organization", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("label", "organization__name")
    inlines = [CertificateVersionInline]

@admin.register(CertificateVersion)
class CertificateVersionAdmin(admin.ModelAdmin):
    list_display = ("certificate", "version_number", "key_type", "key_curve", "is_current", "created_at")
    list_filter = ("key_type", "is_current")