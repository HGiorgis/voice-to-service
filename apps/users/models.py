from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
import uuid

class User(AbstractUser):
    """Extended user model"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    is_verified = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Set when the user signs in with Google or completes email verification.',
    )

    # Admin suspension (checked on every session + API key use)
    is_blocked = models.BooleanField(default=False, db_index=True)
    blocked_reason = models.TextField(blank=True)
    blocked_at = models.DateTimeField(null=True, blank=True)

    # Anti–multi-account telemetry (filled on password registration)
    registration_ip = models.CharField(max_length=45, blank=True, db_index=True)
    registration_fingerprint_hash = models.CharField(max_length=64, blank=True, db_index=True)
    registration_device_id = models.UUIDField(null=True, blank=True, db_index=True)
    suspicious_registration_flag = models.BooleanField(
        default=False,
        help_text='Raised when disposable email or abuse heuristics matched.',
    )

    # Google OAuth subject (unique when set)
    google_sub = models.CharField(max_length=255, null=True, blank=True, unique=True)

    # Rate limiting settings (admin controlled)
    daily_request_limit = models.IntegerField(default=1000)
    monthly_request_limit = models.IntegerField(default=30000)
    # Voice To Service: max successful / attempted pipeline runs per day (default 3)
    daily_voice_limit = models.IntegerField(default=3)
    
    # Usage tracking
    total_api_calls = models.IntegerField(default=0)
    last_api_call = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Fix reverse accessor conflicts
    groups = models.ManyToManyField(
        'auth.Group',
        verbose_name='groups',
        blank=True,
        help_text='The groups this user belongs to.',
        related_name="custom_user_set",
        related_query_name="custom_user",
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name="custom_user_set",
        related_query_name="custom_user",
    )
    
    class Meta:
        ordering = ['-date_joined']
    
    def __str__(self):
        return self.email or self.username

    def save(self, *args, **kwargs):
        if self.is_blocked and self.blocked_at is None:
            self.blocked_at = timezone.now()
        if not self.is_blocked:
            self.blocked_at = None
            self.blocked_reason = ''
        super().save(*args, **kwargs)

    def get_api_key(self):
        """Get user's API key if exists"""
        try:
            return self.api_key
        except:
            return None
    
    def check_rate_limit(self):
        """Check if user has exceeded rate limits"""
        from apps.authentication.models import APIKeyLog
        today = timezone.now().date()
        
        # Count today's requests
        today_requests = APIKeyLog.objects.filter(
            api_key__user=self,
            timestamp__date=today
        ).count()
        
        if today_requests >= self.daily_request_limit:
            return False, f"Daily limit of {self.daily_request_limit} exceeded"
        
        # Count this month's requests
        month_start = timezone.now().replace(day=1)
        month_requests = APIKeyLog.objects.filter(
            api_key__user=self,
            timestamp__gte=month_start
        ).count()
        
        if month_requests >= self.monthly_request_limit:
            return False, f"Monthly limit of {self.monthly_request_limit} exceeded"
        
        return True, "OK"

    def voice_requests_today_count(self):
        """How many voice pipeline rows exist for this user today (counts toward daily cap)."""
        from apps.voice.models import VoiceProcessingRequest

        today = timezone.now().date()
        return VoiceProcessingRequest.objects.filter(
            user=self,
            created_at__date=today,
        ).count()

    def check_voice_daily_limit(self):
        """Enforce Voice To Service daily audio cap (separate from general API limits)."""
        limit = max(0, int(self.daily_voice_limit or 0))
        if limit == 0:
            return False, 'Voice processing is disabled for this account (limit 0).'
        n = self.voice_requests_today_count()
        if n >= limit:
            return False, f'Daily voice limit of {limit} audio request(s) exceeded. Try again tomorrow.'
        return True, 'OK'