from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from ratings import views


urlpatterns = [
    path("", views.home, name="home"),
    path("login/", LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    path("my/tasks/", views.my_tasks, name="my_tasks"),
    path("my/tasks/<int:task_id>/", views.score_task, name="score_task"),
    path("my/results/", views.my_results, name="my_results"),
    path("my/results/<int:pk>/", views.my_result, name="my_result"),
    path("activities/", views.activities, name="activities"),
    path("activities/new/", views.edit_activity, name="new_activity"),
    path("activities/<int:pk>/", views.activity_detail, name="activity_detail"),
    path("activities/<int:pk>/edit/", views.edit_activity, name="edit_activity"),
    path("activities/<int:pk>/action/", views.activity_action, name="activity_action"),
    path("activities/<int:pk>/relationships/", views.relationships, name="relationships"),
    path("activities/<int:pk>/tasks/<int:task_id>/", views.review_task, name="review_task"),
    path("activities/<int:pk>/tasks/<int:task_id>/action/", views.task_action, name="task_action"),
    path("activities/<int:pk>/progress/", views.progress, name="progress"),
    path("activities/<int:pk>/results/", views.results, name="results"),
    path("templates/", views.templates, name="templates"),
    path("templates/new/", views.edit_template, name="new_template"),
    path("templates/<int:pk>/edit/", views.edit_template, name="edit_template"),
    path("templates/<int:pk>/action/", views.template_action, name="template_action"),
]
