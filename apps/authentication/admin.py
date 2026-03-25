from django.contrib import admin

from apps.authentication.models import (
    AntiAbuseSettings,
    BlockedIPAddress,
    RegistrationAttempt,
)


@admin.register(AntiAbuseSettings)
class AntiAbuseSettingsAdmin(admin.ModelAdmin):
    list_display = (
        '__str__',
        'master_enable',
        'oauth_signup_antiabuse_enabled',
        'updated_at',
    )

    def has_add_permission(self, request):
        return not AntiAbuseSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BlockedIPAddress)
class BlockedIPAddressAdmin(admin.ModelAdmin):
    list_display = ('ip_address', 'is_active', 'blocked_automatically', 'expires_at', 'created_at')
    list_filter = ('is_active', 'blocked_automatically')
    search_fields = ('ip_address', 'reason')


@admin.register(RegistrationAttempt)
class RegistrationAttemptAdmin(admin.ModelAdmin):
    list_display = (
        'created_at',
        'outcome',
        'device_class',
        'ip_address',
        'email_input',
        'username_input',
        'email_domain',
        'detail',
    )
    list_filter = ('outcome', 'device_class')
    search_fields = ('ip_address', 'email_domain', 'email_input', 'username_input', 'detail', 'fingerprint_hash')
    readonly_fields = (
        'created_at',
        'ip_address',
        'fingerprint_hash',
        'fingerprint_preview',
        'email_domain',
        'email_input',
        'username_input',
        'user_agent',
        'device_class',
        'browser_family',
        'os_family',
        'outcome',
        'detail',
        'user',
    )
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
