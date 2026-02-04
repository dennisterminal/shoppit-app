from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser

class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Additional Info", {"fields": ("phone", "address", "city", "state")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Additional Info", {"fields": ("phone", "address", "city", "state")}),
    )

    # Show a friendly display name in the list view
    def display_name(self, obj):
        return str(obj)
    display_name.short_description = "Name"

    list_display = (
        "display_name", "username", "email", "phone", "city", "state"
    )
    search_fields = ("username", "email", "first_name", "last_name", "phone", "city")
    list_filter = ("city", "state")

admin.site.register(CustomUser, CustomUserAdmin)

