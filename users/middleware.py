from django.utils import timezone

class UserActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if hasattr(request, 'user') and request.user.is_authenticated:
            try:
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
