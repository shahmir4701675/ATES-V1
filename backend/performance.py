"""Transport optimizations; never cache authorization or private HTTP responses."""
from starlette.middleware.gzip import GZipMiddleware
from starlette.datastructures import MutableHeaders


class APITransport:
    def __init__(self, app):
        self.app = app
        self.compressed = GZipMiddleware(app, minimum_size=1024, compresslevel=4)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        async def private_send(message):
            if message['type'] == 'http.response.start':
                headers = MutableHeaders(scope=message)
                if 'no-store' not in headers.get('Cache-Control', '').lower():
                    headers['Cache-Control'] = 'private, no-store'
            await send(message)

        path = scope.get('path', '')
        # Download bodies already have their own format/compression. Keep login
        # tokens and streaming/download responses out of the JSON gzip path.
        target = self.app if '/auth/' in path or path.endswith('/export') else self.compressed
        await target(scope, receive, private_send)
