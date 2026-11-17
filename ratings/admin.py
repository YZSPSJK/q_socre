from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class AccountAdmin(UserAdmin):
    list_display = ("username", "name", "employee_number", "department", "account_role", "is_active")
    list_filter = ("role", "department", "is_active", "is_superuser")
    search_fields = ("username", "first_name", "last_name", "employee_number", "department")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("员工信息", {"fields": ("last_name", "first_name", "employee_number", "department", "position")}),
        ("角色和状态", {"fields": ("role", "is_active", "is_superuser")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": (
            "username", "password1", "password2", "last_name", "first_name", "employee_number",
            "department", "position", "role", "is_active", "is_superuser",
        )}),
    )

    @admin.display(description="姓名")
    def name(self, obj):
        return obj.display_name

    @admin.display(description="角色")
    def account_role(self, obj):
        return "系统管理员" if obj.is_superuser else obj.get_role_display()

    def save_model(self, request, obj, form, change):
        obj.is_staff = obj.is_superuser
        super().save_model(request, obj, form, change)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def has_delete_permission(self, request, obj=None):
        return False
