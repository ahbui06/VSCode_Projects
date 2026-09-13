"""Offline graph for general-rule compilation and scenario comparison."""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .rule_compiler import compile_scenario, compare_compiled


class CompilationState(TypedDict, total=False):
    entries: list
    plans: list
    compilation: list
    comparison: dict


def build_compilation_workflow(scope, usage, excluded_rules=None):
    excluded_rules = excluded_rules or {}

    def compile_node(state):
        plans, rows = [], []
        for entry in state["entries"]:
            record = entry["record"]
            try:
                plan = compile_scenario(record, entry["document"], scope,
                                        excluded_rules.get(record.source_file, {}))
                plans.append(plan)
                rows.append({"source": record.source_file, "status": "compiled_for_scenario",
                             "reason": "Supported fields converted; conditions/exclusions still require review."})
            except ValueError as exc:
                rows.append({"source": record.source_file, "status": "needs_review_or_engine", "reason": str(exc)})
        return {"plans": plans, "compilation": rows}

    def compare_node(state):
        try:
            return {"comparison": compare_compiled(usage, state["plans"])}
        except ValueError as exc:
            return {"comparison": {"status": "comparison_blocked", "results": [], "explanation": str(exc)}}

    graph = StateGraph(CompilationState)
    graph.add_node("compile", compile_node)
    graph.add_node("compare", compare_node)
    graph.add_edge(START, "compile")
    graph.add_edge("compile", "compare")
    graph.add_edge("compare", END)
    return graph.compile()
