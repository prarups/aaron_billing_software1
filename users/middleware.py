from django.utils import timezone
from django.http import HttpResponseForbidden
from django.middleware.csrf import get_token
from .security import decrypt_credentials_payload, BruteForceLimiter, get_client_ip

class UserActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            if hasattr(request, 'user') and request.user.is_authenticated:
                now = timezone.now()
                last_activity = getattr(request.user, 'last_activity', None)
                if not last_activity or (now - last_activity).total_seconds() > 60:
                    request.user.last_activity = now
                    request.user.save(update_fields=['last_activity'])
        except Exception:
            pass
        
        response = self.get_response(request)
        
        if hasattr(response, 'has_header') and response.has_header('Content-Type') and 'text/html' in response.get('Content-Type', ''):
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
            
        return response


class SecurityPayloadAndHSTSMiddleware:
    """
    Middleware that:
    1. Intercepts encrypted POST credentials payload on login and decrypts it into request.POST.
    2. Checks brute-force IP lockouts on login endpoint.
    3. Enforces HSTS and strict security headers across all responses.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Process encrypted POST payload for login
        if request.method == 'POST' and request.path.endswith('/login/'):
            ip = get_client_ip(request)
            is_locked, ttl = BruteForceLimiter.is_locked_out(ip)
            if is_locked:
                return HttpResponseForbidden(
                    f"Too many failed login attempts. Your IP has been temporarily locked out. Please try again in {ttl // 60 + 1} minutes."
                )

            encrypted_payload = request.POST.get('encrypted_credentials')
            if encrypted_payload:
                csrf_token = request.POST.get('csrfmiddlewaretoken') or get_token(request)
                decrypted = decrypt_credentials_payload(encrypted_payload, csrf_token)
                if decrypted and isinstance(decrypted, dict):
                    # Inject decrypted credentials into request.POST QueryDict
                    post_data = request.POST.copy()
                    if 'username' in decrypted:
                        post_data['username'] = str(decrypted['username'])
                    if 'password' in decrypted:
                        post_data['password'] = str(decrypted['password'])
                    request.POST = post_data

        response = self.get_response(request)

        # Enforce HSTS (Strict-Transport-Security) header
        response['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
        
        # Enforce modern security response headers
        if not response.has_header('X-Content-Type-Options'):
            response['X-Content-Type-Options'] = 'nosniff'
        if not response.has_header('X-Frame-Options'):
            response['X-Frame-Options'] = 'DENY'
        if not response.has_header('Referrer-Policy'):
            response['Referrer-Policy'] = 'strict-origin-when-cross-origin'

        return response

