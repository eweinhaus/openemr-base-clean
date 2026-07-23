"""LangGraph agent assembly for the Clinical Co-Pilot sidecar."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

from .gateway_client import GatewayClient
from .nodes.draft import draft_node
from .nodes.emit import emit_node
from .nodes.refuse import refuse_node
from .nodes.route import route_node
from .nodes.synthesize import synthesize_node
from .nodes.tools import make_tools_node
from .nodes.verify import make_verify_node
from .state import GraphState

AfterRefuse = Literal["route", "emit", "tools"]
AfterRoute = Literal["tools", "emit"]
AfterTools = Literal["draft", "emit"]
AfterDraft = Literal["verify", "emit"]
AfterVerify = Literal["synthesize", "emit"]


def _after_refuse(state: GraphState) -> AfterRefuse:
    if state.get("error") or state.get("clinical_text"):
        return "emit"
    if state.get("prefetch") and state.get("route") == "brief":
        return "tools"
    return "route"


def _after_route(state: GraphState) -> AfterRoute:
    if state.get("error"):
        return "emit"
    return "tools"


def _after_tools(state: GraphState) -> AfterTools:
    if state.get("error"):
        return "emit"
    return "draft"


def _after_draft(state: GraphState) -> AfterDraft:
    if state.get("error"):
        return "emit"
    return "verify"


def _after_verify(state: GraphState) -> AfterVerify:
    if state.get("error"):
        return "emit"
    if state.get("route") in ("brief", "labs", "meds") and state.get("verified_claims"):
        return "synthesize"
    return "emit"


def build_graph(gateway: GatewayClient):
    """Compile refuse → route → tools → draft → verify → synthesize? → emit."""
    graph = StateGraph(GraphState)

    graph.add_node("refuse", refuse_node)
    graph.add_node("route", route_node)
    graph.add_node("tools", make_tools_node(gateway))
    graph.add_node("draft", draft_node)
    graph.add_node("verify", make_verify_node(gateway))
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("emit", emit_node)

    graph.add_edge(START, "refuse")
    graph.add_conditional_edges(
        "refuse",
        _after_refuse,
        {"route": "route", "emit": "emit", "tools": "tools"},
    )
    graph.add_conditional_edges("route", _after_route, {"tools": "tools", "emit": "emit"})
    graph.add_conditional_edges("tools", _after_tools, {"draft": "draft", "emit": "emit"})
    graph.add_conditional_edges("draft", _after_draft, {"verify": "verify", "emit": "emit"})
    graph.add_conditional_edges(
        "verify",
        _after_verify,
        {"synthesize": "synthesize", "emit": "emit"},
    )
    graph.add_edge("synthesize", "emit")
    graph.add_edge("emit", END)

    return graph.compile()
