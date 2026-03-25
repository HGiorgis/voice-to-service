from django.urls import path
from . import views

app_name = 'users'

urlpatterns = [
    path('oauth/google/start/', views.oauth_google_start, name='oauth-google-start'),
    path('register/', views.register_view, name='register'),
    path('verify-email/', views.verify_email_view, name='verify-email'),
    path(
        'verify-email/resend/',
        views.resend_verification_email_view,
        name='verify-email-resend',
    ),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
]