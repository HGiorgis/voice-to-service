from django.urls import path
from django.views.generic import RedirectView
from django.contrib.admin.views.decorators import staff_member_required
from . import admin_views

app_name = 'users'

urlpatterns = [
    # staff_member_required redirects to admin:login when not authenticated; send them to auth login
    path('login/', RedirectView.as_view(pattern_name='auth:login', permanent=False), name='login'),
    path('dashboard/', staff_member_required(admin_views.admin_dashboard), name='dashboard'),
    path('voice/', staff_member_required(admin_views.voice_request_list), name='voice-list'),
    path('voice/<uuid:request_id>/', staff_member_required(admin_views.voice_request_detail), name='voice-detail'),
    path('users/', staff_member_required(admin_views.user_list), name='users'),
    path('users/<uuid:user_id>/', staff_member_required(admin_views.user_detail), name='user-detail'),
    path('users/<uuid:user_id>/revoke-key/', staff_member_required(admin_views.revoke_user_key), name='revoke-key'),
    path('settings/', staff_member_required(admin_views.admin_settings), name='settings'),
    path('security/', staff_member_required(admin_views.security_monitor), name='security-monitor'),
    path('terminal/', staff_member_required(admin_views.terminal_view), name='terminal'),
    path('terminal/run/', staff_member_required(admin_views.terminal_run_command), name='terminal-run'),
]