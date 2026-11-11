"""Explicit startup/shutdown ownership for the local app and its background workers."""
from contextlib import asynccontextmanager
import inspect
from fastapi import FastAPI


class Application(FastAPI):
    def __init__(self, **kwargs):
        @asynccontextmanager
        async def lifespan(app):
            completed = []
            try:
                for callback in app.router.on_startup:
                    result = callback()
                    if inspect.isawaitable(result):
                        await result
                    completed.append(callback)
                yield
            finally:
                for callback in reversed(app.router.on_shutdown):
                    result = callback()
                    if inspect.isawaitable(result):
                        await result
        super().__init__(lifespan=lifespan, **kwargs)

    def on_event(self, event_type):
        # Existing feature registration stays small while lifecycle ownership is central.
        def register(callback):
            getattr(self.router, 'on_' + event_type).append(callback)
            return callback
        return register
