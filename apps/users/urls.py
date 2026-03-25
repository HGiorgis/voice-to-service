from django.urls import path
from . import views

app_name = 'users'

urlpatterns = [
    path('oauth/google/start/', views.oauth_google_start, name='oauth-google-start'),
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
]