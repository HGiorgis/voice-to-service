from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from apps.users.views import landing_page_view, login_view

urlpatterns = [
    # Landing page (public)
    path('', landing_page_view, name='landing'),
    # Root 'login' so reverse('login') works for admin/staff redirects (same view as auth:login)
    path('login/', login_view, name='login'),
    # Authentication URLs (public) - auth:login is /auth/login/
    path('auth/', include(('apps.users.urls', 'users'), namespace='auth')),
    path('oauth/', include('social_django.urls', namespace='social')),
    
    # User Dashboard (requires login) - namespace 'user'
    path('user/', include(('apps.users.user_urls', 'users'), namespace='user')),
    
    # Admin Dashboard (requires staff) - namespace 'admin'
    path('admin/', include(('apps.users.admin_urls', 'users'), namespace='admin')),
    
    # API endpoints (require API key)
    path('api/v1/', include('apps.api.urls')),
]

# Media files: always serve so logos/uploads work in Docker and Render
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

