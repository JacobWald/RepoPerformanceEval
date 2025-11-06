from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing, name='index'),
    path('signup/', views.signup, name='signup'),
    path("login/", views.login_view, name="login"),
    path("home/", views.home, name="home"),
    path("analyze/", views.analyze_repo, name="analyze_repo"),
]
