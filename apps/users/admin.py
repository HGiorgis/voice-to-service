from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Custom admin for User model"""
    list_display = (
        'username',
        'email',
        'company_name',
        'is_verified',
        'is_blocked',
        'is_staff',
    )
    list_filter = ('is_verified', 'is_staff', 'is_superuser', 'is_blocked', 'suspicious_registration_flag')
    fieldsets = UserAdmin.fieldsets + (
        ('Suspension', {
            'fields': ('is_blocked', 'blocked_reason', 'blocked_at'),
        }),
        ('Additional Info', {
            'fields': (
                'company_name',
                'phone',
                'is_verified',
                'email_verified_at',
                'google_sub',
                'total_api_calls',
                'last_api_call',
            ),
        }),
        ('Registration telemetry', {
            'classes': ('collapse',),
            'fields': (
                'registration_ip',
                'registration_fingerprint_hash',
                'registration_device_id',
                'suspicious_registration_flag',
            ),
        }),
    )
    readonly_fields = (
        'total_api_calls',
        'last_api_call',
        'created_at',
        'updated_at',
        'google_sub',
        'registration_ip',
        'registration_fingerprint_hash',
        'registration_device_id',
    )