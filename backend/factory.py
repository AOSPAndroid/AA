"""Supported Uvicorn factory: prepare the writable workspace before loading routes."""

def create_app():
    from runtime_paths import prepare_runtime_database
    prepare_runtime_database()
    from backend.main import app
    app.state.managed_runtime=True
    return app
