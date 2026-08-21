import asyncio
from django.utils import timezone
from asgiref.sync import sync_to_async

class UserActivityMiddleware:
    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self._is_async = asyncio.iscoroutinefunction(get_response)

    def __call__(self, request):
        if self._is_async:
            return self.__acall__(request)

        if request.user.is_authenticated:
            now = timezone.now()
            last_activity = request.user.last_activity
            # Update last_activity at most once per 60 seconds to avoid excessive DB writes
            if not last_activity or (now - last_activity).total_seconds() > 60:
                request.user.last_activity = now
                request.user.save(update_fields=['last_activity'])
        
        response = self.get_response(request)
        
        # Prevent browsers from caching dynamic HTML pages (fixes refresh issues on login/logout)
        if response and response.has_header('Content-Type') and 'text/html' in response['Content-Type']:
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
            
        return response

    async def __acall__(self, request):
        if request.user.is_authenticated:
            now = timezone.now()
            last_activity = request.user.last_activity
            if not last_activity or (now - last_activity).total_seconds() > 60:
                request.user.last_activity = now
                await sync_to_async(request.user.save)(update_fields=['last_activity'])
        
        response = await self.get_response(request)
        
        if response and response.has_header('Content-Type') and 'text/html' in response['Content-Type']:
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
            
        return response
