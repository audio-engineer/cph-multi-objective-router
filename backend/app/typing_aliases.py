"""Shared typing aliases for graph operations."""

from typing import TYPE_CHECKING

import networkx as nx

if TYPE_CHECKING:
    type MultiDiGraphAny = nx.MultiDiGraph[int]
else:
    MultiDiGraphAny = nx.MultiDiGraph


type EdgeAttributeMap = dict[str, object]
