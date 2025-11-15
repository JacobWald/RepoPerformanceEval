from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing, name='index'),
    path('signup/', views.signup, name='signup'),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("home/", views.home, name="home"),
    path("analyze/", views.analyze_repo, name="analyze_repo"),
    path("progress/<str:job_id>/", views.progress_page, name="progress"),
    path("progress/<str:job_id>/stream/", views.stream_progress, name="progress_stream"),
    path("analyses/", views.my_analyses, name="my_analyses"),
    
    path("analysis/<uuid:analysis_id>/dashboard/", views.analysis_dashboard, name="analysis_dashboard"),
    path("analysis/<uuid:analysis_id>/dashboard/overall/", views.analysis_dashboard_overall, name="analysis_dashboard_overall"),
    path("analysis/<uuid:analysis_id>/dashboard/developers/", views.analysis_dashboard_developers, name="analysis_dashboard_developers"),
]
