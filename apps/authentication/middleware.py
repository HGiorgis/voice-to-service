from django.http import JsonResponse
from django.utils import timezone

from apps.api.authentication import extract_api_key_header
from apps.authentication.models import APIKey


class RateLimitMiddleware:
    """Optional rate limits for API (voice endpoint enforces its own daily cap in the view)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith('/api/'):
            return self.get_response(request)

        # Voice To Service: daily voice cap is enforced in ProcessAudioView (after file validation).
        if 'process-audio' in request.path:
            return self.get_response(request)

        api_key_raw = extract_api_key_header(request)
        if not api_key_raw:
            return self.get_response(request)

        key_obj = None
        for key in APIKey.objects.filter(is_active=True).select_related('user'):
            is_valid, _ = key.validate_key(api_key_raw)
            if is_valid:
                key_obj = key
                break

        if not key_obj:
            return self.get_response(request)

        can_proceed, message = key_obj.user.check_rate_limit()
        if not can_proceed:
            return JsonResponse(
                {'error': message, 'code': 'rate_limit_exceeded'},
                status=429,
            )

        return self.get_response(request)
