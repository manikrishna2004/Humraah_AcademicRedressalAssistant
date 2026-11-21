"""
Wires every node from src/nodes into the LangGraph StateGraph described by
the architecture diagram, including the direct "skip Node 1 / skip straight
to Node 3" edges that come out of each clarification checkpoint.

    Student Query
          |
          v
    intent_classifier  --clarify_1--> clarification_1 --------+
          |--web_search--> web_search -----------------------+ |
          |--retrieve---------------------------------------+ | |
                                                              v v v
                                                          retriever
                                                              |
                                                              v
                                                       confidence_gate
                                                     /        |        \\
                                          synthesize    clarify_2    clarify_3
                                              |              |            |
                                              |         clarification_2  clarification_3
                                              |              |            |
                                              +--------------+------------+
                                                              |
                                                              v
                                                          synthesizer  -> END
"""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.nodes.clarification import (
    clarification_1_node,
    clarification_2_node,
    clarification_3_node,
)
from src.nodes.confidence_gate import confidence_gate_node, route_after_gate
from src.nodes.intent_classifier import intent_classifier_node, route_after_intent
from src.nodes.retriever import retriever_node
from src.nodes.synthesizer import synthesizer_node
from src.nodes.web_search import web_search_node
from src.state import RedressalState


def build_graph(checkpointer=None):
    graph = StateGraph(RedressalState)

    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("clarification_1", clarification_1_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("confidence_gate", confidence_gate_node)
    graph.add_node("clarification_2", clarification_2_node)
    graph.add_node("clarification_3", clarification_3_node)
    graph.add_node("synthesizer", synthesizer_node)

    graph.add_edge(START, "intent_classifier")

    # Node 1 fan-out: missing entities / out-of-domain / ready-to-retrieve
    graph.add_conditional_edges(
        "intent_classifier",
        route_after_intent,
        {
            "clarify_1": "clarification_1",
            "web_search": "web_search",
            "retrieve": "retriever",
            "unsupported": "synthesizer",
        },
    )

    # Clarification Point 1 and the gated web search both feed straight into
    # Node 2 -- Node 1 (the LLM classification call) is never re-run.
    graph.add_edge("clarification_1", "retriever")
    graph.add_edge("web_search", "retriever")

    graph.add_edge("retriever", "confidence_gate")

    # Confidence Gate fan-out: single clear path / ambiguous / low confidence
    graph.add_conditional_edges(
        "confidence_gate",
        route_after_gate,
        {
            "synthesize": "synthesizer",
            "clarify_2": "clarification_2",
            "clarify_3": "clarification_3",
        },
    )

    # Both remaining clarification checkpoints resume straight into Node 3
    # without re-running retrieval.
    graph.add_edge("clarification_2", "synthesizer")
    graph.add_edge("clarification_3", "synthesizer")

    graph.add_edge("synthesizer", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())


def build_persistent_graph(sqlite_path: str):
    """Production variant: state survives process restarts via a SQLite
    checkpointer, so a student can resume a clarification days later."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    conn_ctx = SqliteSaver.from_conn_string(sqlite_path)
    checkpointer = conn_ctx.__enter__()  # kept open for the app's lifetime
    return build_graph(checkpointer=checkpointer)
