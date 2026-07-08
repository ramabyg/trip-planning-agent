import os
import logging

import dotenv

dotenv.load_dotenv()  # local dev reads passwords/keys from .env; prod from Secret Manager

from google.adk.cli.fast_api import get_fast_api_app
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse

import auth
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


# The ADK dev-ui (web=True) is for local development only; the deployed
# service sets SERVE_DEV_UI=0 and serves just the custom UI at /ui.
SERVE_DEV_UI = os.getenv("SERVE_DEV_UI", "1") != "0"

# auto_create_session=True is CRITICAL for custom UIs that generate random session IDs.
app = get_fast_api_app(
    agents_dir=".",
    agent_loader=CustomAgentLoader("."),
    web=SERVE_DEV_UI,
    auto_create_session=True
)

# Initialize OpenTelemetry instrumentation for Google GenAI SDK to collect local traces.
# This MUST run after get_fast_api_app, which configures the global TracerProvider.
try:
    from opentelemetry.instrumentation.google_genai import GoogleGenAiSdkInstrumentor
    GoogleGenAiSdkInstrumentor().instrument()
except ImportError:
    logging.getLogger("main").warning("GoogleGenAiSdkInstrumentor could not be imported; traces will be disabled.")


script_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(script_dir, "static")
os.makedirs(static_dir, exist_ok=True)

tmp_dir = os.path.join(script_dir, "tmp")
os.makedirs(tmp_dir, exist_ok=True)


# --- Family login gate (specs/06-deployment.md) ---
# Everything except /login and /healthz requires the signed family cookie:
# /run_sse, ADK session APIs, /api/*, /ui, /tmp, and the dev-ui when enabled.

@app.middleware("http")
async def family_login_gate(request: Request, call_next):
    path = request.url.path
    if not auth.auth_enabled() or auth.is_public_path(path):
        return await call_next(request)
    family = auth.request_family(request)
    if family is None:
        wants_html = "text/html" in request.headers.get("accept", "")
        if request.method == "GET" and wants_html:
            return RedirectResponse(url="/login", status_code=302)
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    request.state.family = family
    return await call_next(request)


@app.get("/login")
async def login_page():
    return FileResponse(os.path.join(static_dir, "login.html"))


@app.post("/login")
async def login(request: Request):
    body = await request.json()
    password = str(body.get("password", ""))
    family = auth.check_password(password)
    if family is None:
        return JSONResponse({"detail": "Wrong password"}, status_code=401)
    response = JSONResponse({"family": family, "label": auth.FAMILY_LABELS[family]})
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.make_cookie_value(family),
        max_age=auth.COOKIE_MAX_AGE_S,
        httponly=True,
        secure=os.getenv("COOKIE_INSECURE", "0") != "1",  # =1 only for plain-http local testing
        samesite="lax",
    )
    return response


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/me")
async def whoami(request: Request):
    family = auth.request_family(request)
    if family is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"family": family, "label": auth.FAMILY_LABELS[family]}


@app.get("/")
async def root_redirect():
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
    try:
        return tools._parse_context()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

app.mount("/ui", StaticFiles(directory=static_dir), name="ui")
app.mount("/tmp", StaticFiles(directory=tmp_dir), name="tmp")

print("FastAPI application with ADK Orchestrator initialized.")
