from django.contrib import admin
from .models import DIDDocument, DIDDocumentVersion, DocumentVerificationMethod

class VerificationMethodInline(admin.TabularInline):
    model = DocumentVerificationMethod
    extra = 0

class VersionInline(admin.TabularInline):
    model = DIDDocumentVersion
    extra = 0
    readonly_fields = ("version_number", "published_at", "created_at")

@admin.register(DIDDocument)
class DIDDocumentAdmin(admin.ModelAdmin):
    list_display = ("label", "organization", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("label", "organization__name")
    inlines = [VerificationMethodInline, VersionInline]

@admin.register(DIDDocumentVersion)
class DIDDocumentVersionAdmin(admin.ModelAdmin):
    list_display = ("document", "version_number", "published_at", "created_at")

@admin.register(DocumentVerificationMethod)
class DocumentVerificationMethodAdmin(admin.ModelAdmin):
    list_display = ("document", "certificate", "method_id_fragment", "method_type", "is_active")
    list_filter = ("is_active", "method_type")