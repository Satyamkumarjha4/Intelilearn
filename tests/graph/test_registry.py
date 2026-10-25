"""Unit under test: `graph.registry.GraphRegistry`, the map from a `GraphRun.graph` name to its builder.

Why: the runner picks the graph to execute from a name stored in the database. An unknown or misspelt name must fail
loudly with the known names, not run the wrong graph.

Use cases:
- looks up the builder for a registered graph name
- reports the known names for an unknown graph
- builders can be replaced, so tests and later phases add graphs without editing the registry
"""

import pytest

from graph.builders import FlowGraphBuilder
from graph.registry import GraphRegistry, UnknownGraph


def test_looks_up_the_builder_for_a_registered_graph():
    assert isinstance(GraphRegistry().builder("flow"), FlowGraphBuilder)


def test_an_unknown_graph_names_the_known_ones():
    with pytest.raises(UnknownGraph, match="nope.*flow"):
        GraphRegistry().builder("nope")


def test_builders_can_be_supplied():
    custom = FlowGraphBuilder(segments=[])

    assert GraphRegistry({"flow": custom}).builder("flow") is custom
