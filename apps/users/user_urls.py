from django.urls import path
from django.contrib.auth.decorators import login_required
from . import views

app_name = 'users'

urlpatterns = [
    path('dashboard/', login_required(views.dashboard_view), name='dashboard'),
    path('usage/', login_required(views.usage_view), name='usage'),
    path('profile/', login_required(views.profile_view), name='profile'),
    path('test/', login_required(views.test_voice_view), name='test'),
    path('test/stream/', login_required(views.test_voice_stream_view), name='test_stream'),
    path('test/job/', login_required(views.test_voice_job_start), name='test_job_start'),
    path(
        'test/job/<uuid:job_id>/',
        login_required(views.test_voice_job_status),
        name='test_job_status',
    ),
    path('generate-key/', login_required(views.generate_api_key), name='generate-key'),
    path('revoke-key/', login_required(views.revoke_api_key), name='revoke-key'),
    path('change-password/', login_required(views.change_password), name='change-password'),
]