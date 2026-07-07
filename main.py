import os
import logging
from google.adk.cli.fast_api import get_fast_api_app
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
import tools

# Configure logging to print agent execution details to the terminal
logging.basicConfig(level=logging.INFO)
logging.getLogger("google_adk").setLevel(logging.INFO)

from google.adk.cli.utils.agent_loader import AgentLoader


class CustomAgentLoader(AgentLoader):
    def __init__(self, agents_dir: str):
        super().__init__(agents_dir)
        self._is_single_agent = True
        self._single_agent_name = "agent"
        self.agents_dir = os.path.dirname(os.path.abspath(__file__))

    def _set_single_agent_mode(self, name: str, agents_dir: str) -> None:
        # Prevent the framework from overriding our custom 'agent' name back to the hyphenated folder name
        pass


# Create the standard ADK app with the developer web playground enabled (web=True)
# auto_create_session=True is CRITICAL for custom UIs that generate random session IDs.
app = get_fast_api_app(
    agents_dir=".",
    agent_loader=CustomAgentLoader("."),
    web=True,
    auto_create_session=True
)

# Initialize OpenTelemetry instrumentation for Google GenAI SDK to collect local traces.
# This MUST run after get_fast_api_app, which configures the global TracerProvider.
try:
    from opentelemetry.instrumentation.google_genai import GoogleGenAiSdkInstrumentor
    GoogleGenAiSdkInstrumentor().instrument()
except ImportError:
    logging.getLogger("main").warning("GoogleGenAiSdkInstrumentor could not be imported; traces will be disabled.")



# Mount custom static files
script_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(script_dir, "static")
os.makedirs(static_dir, exist_ok=True)

tmp_dir = os.path.join(script_dir, "tmp")
os.makedirs(tmp_dir, exist_ok=True)


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
