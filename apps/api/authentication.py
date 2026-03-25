# apps/api/authentication.py
import hashlib
import secrets

from django.utils import timezone
from rest_framework import authentication
from rest_framework import exceptions

from apps.authentication.models import APIKey


def extract_api_key_header(request):
    """Support X-API-Key and Authorization: Bearer <key>."""
    raw = request.headers.get('X-API-Key')
    if raw:
        return raw.strip()
    auth = request.headers.get('Authorization') or ''
    if auth.lower().startswith('bearer '):
        return auth[7:].strip()
    return None


class APIKeyAuthentication(authentication.BaseAuthentication):
    """Authenticate with API key (header)."""

    def authenticate(self, request):
        api_key = extract_api_key_header(request)
        if not api_key:
            return None

        try:
            all_keys = APIKey.objects.filter(is_active=True).select_related('user')
            key_obj = None
            for key in all_keys:
                is_valid, _ = key.validate_key(api_key)
                if is_valid:
                    key_obj = key
                    break

            if not key_obj:
                raise exceptions.AuthenticationFailed('Invalid API key')

            if getattr(key_obj.user, 'is_blocked', False):
                u = key_obj.user
                reason = (getattr(u, 'blocked_reason', None) or '').strip()
                if reason:
                    detail = (
                        'API access is disabled because this account is suspended. '
                        f'Reason: {reason}'
                    )
                else:
                    detail = (
                        'API access is disabled because this account is suspended. '
                        'Contact support if you need help.'
                    )
                raise exceptions.AuthenticationFailed(detail)

            if key_obj.expires_at and key_obj.expires_at < timezone.now():
                raise exceptions.AuthenticationFailed('API key has expired')

            return (key_obj.user, key_obj)

        except exceptions.AuthenticationFailed:
            raise
        except Exception as e:
            raise exceptions.AuthenticationFailed(str(e)) from e
