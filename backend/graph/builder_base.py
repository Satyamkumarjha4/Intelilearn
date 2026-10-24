"""The two abstractions graphs are assembled from: a `GraphBuilder` (nodes and edges, then compile) and a `Segment`
(one slice of the lesson flow). They live apart from the concrete builders so a node module can use `GraphBuilder`
for a subgraph without importing the builders, which import the nodes."""

from abc import ABC, abstractmethod

from langgraph.graph import StateGraph

from .context import FlowContext
from .state import FlowState


class GraphBuilder(ABC):
    state_schema: type = FlowState

    def build(self, checkpointer=None):
        graph = StateGraph(self.state_schema, context_schema=FlowContext)
        self.add_nodes(graph)
        self.add_edges(graph)
        return graph.compile(checkpointer=checkpointer)

    @abstractmethod
    def add_nodes(self, graph: StateGraph) -> None: ...

    @abstractmethod
    def add_edges(self, graph: StateGraph) -> None: ...


class Segment(ABC):
    """One slice of the flow graph."""

    #: Nodes a retry may resume at (the ones that give up with `failed_node` set).
    retry_targets: tuple[str, ...] = ()
    #: Entry points this segment offers to the others: exit name → node. The author segment provides `lesson`.
    provides: dict[str, str] = {}

    @abstractmethod
    def add_nodes(self, graph: StateGraph) -> None: ...

    @abstractmethod
    def add_edges(self, graph: StateGraph, exits: dict[str, str]) -> None:
        """`exits` maps exit names (`lesson`, `mastery`, `failed`) to the node each leads to."""
