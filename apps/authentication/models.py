from django.db import models
from django.conf import settings
from django.utils import timezone
import secrets
import hashlib
from datetime import timedelta

class APIKey(models.Model):
    """API key for Voice To Service and related HTTP APIs."""
    
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        related_name='api_key',
        limit_choices_to={'is_active': True}
    )
    
    name = models.CharField(max_length=100, help_text="Name for this API key")
    key = models.CharField(max_length=64, unique=True, editable=False)
    key_preview = models.CharField(max_length=16, editable=False)
    key_hash = models.CharField(max_length=128, editable=False)  # Store hash for verification
    
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    # Usage tracking
    last_used_at = models.DateTimeField(null=True, blank=True)
    total_requests = models.IntegerField(default=0)
    
    # Rate limiting
    requests_today = models.IntegerField(default=0)
    last_request_date = models.DateField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        if not self.key:
            # Generate API key
            self.key = secrets.token_urlsafe(32)
            self.key_preview = self.key[:8] + '...'
            # Store hash for secure verification
            self.key_hash = hashlib.sha256(self.key.encode()).hexdigest()
            
            # Set expiry to 1 year from now
            if not self.expires_at:
                self.expires_at = timezone.now() + timedelta(days=365)
        
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.user.email} - {self.key_preview}"
        
    def validate_key(self, provided_key):
        """Validate provided API key"""
        if not self.is_active:
            return False, "API key is inactive"
        
        if self.expires_at and self.expires_at < timezone.now():
            return False, "API key has expired"
        
        # Secure comparison using hash
        provided_hash = hashlib.sha256(provided_key.encode()).hexdigest()
        if not secrets.compare_digest(self.key_hash, provided_hash):
            return False, "Invalid API key"
        
        return True, "Valid"
    
    def record_usage(self):
        """Record API usage"""
        self.total_requests += 1
        self.last_used_at = timezone.now()
        
        # Reset daily counter if new day
        today = timezone.now().date()
        if self.last_request_date != today:
            self.requests_today = 1
            self.last_request_date = today
        else:
            self.requests_today += 1
        
        self.save(update_fields=['total_requests', 'last_used_at', 
                                'requests_today', 'last_request_date'])


class AntiAbuseSettings(models.Model):
    """
    Singleton (pk=1): toggles and thresholds for registration abuse defenses.
    Admins can enable/disable each mechanism independently.
    """

    master_enable = models.BooleanField(
        default=True,
        help_text='Master switch for server-side registration checks (except hard admin block).',
    )

    enforce_admin_block = models.BooleanField(
        default=True,
        help_text='When off, is_blocked users may still use the site (not recommended).',
    )

    block_disposable_email = models.BooleanField(
        default=True,
        help_text='Reject signups whose email domain is on the disposable/temp list.',
    )

    require_gmail_domain_for_password_signup = models.BooleanField(
        default=False,
        help_text='If enabled, password registration only allows @gmail.com / @googlemail.com.',
    )

    oauth_signup_antiabuse_enabled = models.BooleanField(
        default=True,
        help_text='When on, new Google OAuth sign-ups use the same registration limits (IP, fingerprint, disposable email, rapid window, device cookie). Existing Google users are unaffected.',
    )

    block_same_ip_registration = models.BooleanField(default=True)
    same_ip_lookback_hours = models.PositiveIntegerField(default=24)
    max_accounts_per_ip_in_lookback = models.PositiveIntegerField(
        default=1,
        help_text='Block new password signups when this many accounts already used the same IP in the lookback window.',
    )

    block_same_fingerprint = models.BooleanField(default=True)
    fingerprint_lookback_hours = models.PositiveIntegerField(default=168)

    block_rapid_registration_window = models.BooleanField(
        default=True,
        help_text='Block when several registrations occur from the same IP or fingerprint within a short window.',
    )
    rapid_registration_window_minutes = models.PositiveIntegerField(default=10)
    max_registrations_per_ip_in_rapid_window = models.PositiveIntegerField(default=1)
    max_registrations_per_fingerprint_in_rapid_window = models.PositiveIntegerField(default=1)

    device_tracker_cookie_enabled = models.BooleanField(
        default=True,
        help_text='Long-lived HttpOnly cookie: block a second account from the same browser profile.',
    )
    device_tracker_cookie_max_age_days = models.PositiveIntegerField(default=400)

    auto_block_ip_on_burst = models.BooleanField(default=True)
    suspicious_burst_registration_count = models.PositiveIntegerField(default=3)
    suspicious_burst_window_minutes = models.PositiveIntegerField(default=60)
    auto_blocked_ip_duration_days = models.PositiveIntegerField(default=7)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Anti-abuse settings'
        verbose_name_plural = 'Anti-abuse settings'

    def __str__(self):
        return 'Anti-abuse settings'

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={})
        return obj


class BlockedIPAddress(models.Model):
    """Manual or automatic IP (or /32) block."""

    ip_address = models.CharField(max_length=45, db_index=True)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Empty = use default duration from anti-abuse settings at creation time.',
    )
    blocked_automatically = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Blocked IP address'
        verbose_name_plural = 'Blocked IP addresses'

    def __str__(self):
        return f'{self.ip_address} (active={self.is_active})'


class RegistrationAttempt(models.Model):
    """Audit trail for signup attempts (success and failure)."""

    class Outcome(models.TextChoices):
        BLOCKED = 'blocked', 'Blocked'
        SUCCESS = 'success', 'Success'
        FAILED_VALIDATION = 'failed_validation', 'Failed validation'
        PENDING_VERIFICATION = 'pending_verification', 'Pending email verification'

    ip_address = models.CharField(max_length=45, db_index=True)
    fingerprint_hash = models.CharField(max_length=64, blank=True, db_index=True)
    fingerprint_preview = models.CharField(
        max_length=220,
        blank=True,
        help_text='Short fingerprint label for dashboards (not the password).',
    )
    email_domain = models.CharField(max_length=255, blank=True)
    email_input = models.CharField(
        max_length=254,
        blank=True,
        help_text='Email entered on the form (staff-only audit).',
    )
    username_input = models.CharField(max_length=150, blank=True)
    user_agent = models.TextField(blank=True)
    device_class = models.CharField(max_length=32, blank=True, db_index=True)
    browser_family = models.CharField(max_length=64, blank=True)
    os_family = models.CharField(max_length=64, blank=True)

    outcome = models.CharField(max_length=32, choices=Outcome.choices, db_index=True)
    detail = models.CharField(max_length=500, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='registration_attempt_rows',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['ip_address', '-created_at']),
            models.Index(fields=['fingerprint_hash', '-created_at']),
            models.Index(fields=['device_class', '-created_at']),
        ]

    @classmethod
    def for_abuse_monitor(cls):
        """
        Rows staff anti-abuse dashboards should show: blocked, validation failures,
        and completed signups (success). Excludes OTP-sent / pre-login state — those
        users are not active yet and should not appear as abuse signals.
        """
        return cls.objects.exclude(outcome=cls.Outcome.PENDING_VERIFICATION)


class APIKeyLog(models.Model):
    """Log all API requests"""
    api_key = models.ForeignKey(APIKey, on_delete=models.CASCADE, related_name='logs')
    endpoint = models.CharField(max_length=255)
    method = models.CharField(max_length=10)
    status_code = models.IntegerField()
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    response_time = models.FloatField(help_text="Response time in seconds")
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['api_key', '-timestamp']),
        ]