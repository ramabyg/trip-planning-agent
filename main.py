import os
from google.adk.cli.fast_api import get_fast_api_app
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
import tools

# Create the standard ADK app in headless mode (web=False)
# auto_create_session=True is CRITICAL for custom UIs that generate random session IDs.
app = get_fast_api_app(agents_dir=".", web=False, auto_create_session=True)

# Mount custom static files
script_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(script_dir, "static")
os.makedirs(static_dir, exist_ok=True)

tmp_dir = os.path.join(script_dir, "tmp")
os.makedirs(tmp_dir, exist_ok=True)

@app.get("/")
async def redirect_to_ui():
    return RedirectResponse(url="/ui/")

@app.get("/ui/")
async def get_ui_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="index.html not found")

@app.get("/api/trip-context")
async def get_ui_trip_context():
    """
    Exposes the static trip context directly to the frontend for visualization.
    """
    context = tools.get_trip_context()
    if "error" in context:
        raise HTTPException(status_code=500, detail=context["error"])
    return context

app.mount("/ui", StaticFiles(directory=static_dir), name="ui")
app.mount("/tmp", StaticFiles(directory=tmp_dir), name="tmp")

print("FastAPI application with ADK Orchestrator initialized.")
