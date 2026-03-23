from django.contrib import admin
from .models import Organization, Membership

# Enregistrez vos modèles ici.

admin.site.register(Organization)
admin.site.register(Membership)
