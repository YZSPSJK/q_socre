from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig


class AccountAdminSite(AdminSite):
    site_header = "QScore 系统管理"
    site_title = "QScore 系统管理"
    index_title = "账号与角色"
    site_url = "/"

    def has_permission(self, request):
        return request.user.is_active and request.user.is_superuser


class AccountAdminConfig(AdminConfig):
    default_site = "qscore.apps.AccountAdminSite"
