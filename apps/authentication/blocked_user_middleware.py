from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect

from apps.authentication.models import AntiAbuseSettings


class BlockedUserMiddleware:
    """Log out blocked users on every request (when enforcement is on)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        cfg = AntiAbuseSettings.get_settings()
        if (
            cfg.enforce_admin_block
            and request.user.is_authenticated
            and getattr(request.user, 'is_blocked', False)
        ):
            reason = (getattr(request.user, 'blocked_reason', None) or '').strip()
            if not reason:
                reason = 'Your account has been suspended. Contact support if you believe this is an error.'
            logout(request)
            messages.error(request, reason)
            return redirect('auth:login')

        return self.get_response(request)
