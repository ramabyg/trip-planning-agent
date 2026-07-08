"""Compact real-time flow log for the dev server terminal.

One line per hop — agent run start/finish, LLM call, tool/MCP call and result
— so you can watch root_agent -> sub-agent -> tool traffic live while using
the dev UI. Purely observational: every callback returns None and never
alters agent behavior. Disable with FLOW_LOG=0.

Wired onto every LlmAgent in agent.py; maps_client.py logs its REST fan-out
to the same "flow" logger so the deterministic planner's Maps calls are
visible too.
"""
import logging
import os
import sys

ENABLED = os.getenv("FLOW_LOG", "1") != "0"
_MAX_CHARS = 160

flow_logger = logging.getLogger("flow")
if ENABLED and not flow_logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    flow_logger.addHandler(_handler)
    flow_logger.setLevel(logging.INFO)
    flow_logger.propagate = False


def _fmt(value) -> str:
    text = repr(value)
    return text if len(text) <= _MAX_CHARS else text[:_MAX_CHARS] + "..."


def _emit(line: str) -> None:
    if ENABLED:
        # Tool results may contain emoji etc.; Windows consoles are often
        # cp1252 — degrade unencodable characters instead of crashing the
        # logging handler.
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        line = line.encode(encoding, errors="replace").decode(encoding, errors="replace")
        flow_logger.info(line)


def before_agent_callback(callback_context=None, **_):
    _emit(f">> [{callback_context.agent_name}] run started")


def after_agent_callback(callback_context=None, **_):
    _emit(f"<< [{callback_context.agent_name}] run finished")


def before_model_callback(callback_context=None, llm_request=None, **_):
    model = getattr(llm_request, "model", None) or "?"
    contents = getattr(llm_request, "contents", None) or []
    _emit(f"   [{callback_context.agent_name}] LLM call ({model}, {len(contents)} contents)")


def before_tool_callback(tool=None, args=None, tool_context=None, **_):
    _emit(f"   [{tool_context.agent_name}] -> tool {tool.name}({_fmt(args)})")


def after_tool_callback(tool=None, args=None, tool_context=None, tool_response=None, **_):
    if isinstance(tool_response, dict):
        if "error" in tool_response:
            summary = f"ERROR {_fmt(tool_response['error'])}"
        elif tool_response:
            summary = f"ok, keys: {', '.join(list(tool_response)[:6])}"
        else:
            summary = "ok, {}"
    else:
        summary = _fmt(tool_response)
    _emit(f"   [{tool_context.agent_name}] <- {tool.name} ({summary})")
