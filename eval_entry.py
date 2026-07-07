"""Entry-point shim for ADK's AgentEvaluator (Phase 1b, specs/05-testing.md).

AgentEvaluator resolves an agent by importing a module and reading its
`agent` member (or requires the module name to end in `.agent`). This repo
keeps a flat layout with `agent.py` at the root, so this shim exposes it
under the expected shape: `eval_entry.agent.root_agent`.
"""
import agent  # noqa: F401
