"""Compress text responses; floor data and scripts shrink to about a fifth."""
from starlette.middleware.gzip import GZipMiddleware

# Already-compressed formats only cost CPU; event streams must not be buffered.
SKIP = ('text/event-stream', 'image/jpeg', 'image/png', 'image/webp', 'application/pdf', 'application/zip')


def compress_responses(app):
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6, exclude_content_types=SKIP)
