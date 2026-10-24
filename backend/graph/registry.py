"""GraphRegistry: `GraphRun.graph` name → the builder that assembles that graph."""

from .builders import FlowGraphBuilder, GraphBuilder, StudyMaterialGraphBuilder


class UnknownGraph(KeyError):
    pass


class GraphRegistry:
    def __init__(self, builders: dict[str, GraphBuilder] | None = None):
        self.builders = (
            builders
            if builders is not None
            else {"flow": FlowGraphBuilder(), "study_material": StudyMaterialGraphBuilder()}
        )

    def builder(self, name: str) -> GraphBuilder:
        try:
            return self.builders[name]
        except KeyError:
            raise UnknownGraph(f"Unknown graph {name!r}; known graphs: {', '.join(sorted(self.builders))}") from None
