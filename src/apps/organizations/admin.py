from django.contrib import admin

from .models import Membership, Organization

# Enregistrez vos modèles ici.

admin.site.register(Organization)
admin.site.register(Membership)
