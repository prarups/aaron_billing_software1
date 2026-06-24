from django.utils import timezone

class UserActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            now = timezone.now()
            last_activity = request.user.last_activity
            # Update last_activity at most once per 60 seconds to avoid excessive DB writes
            if not last_activity or (now - last_activity).total_seconds() > 60:
                request.user.last_activity = now
                request.user.save(update_fields=['last_activity'])
        
        response = self.get_response(request)
        return response
