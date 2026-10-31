"""Deterministic SVG layout for the dependency graph on the impact page.

The layout only draws relationships the analysis actually asserts: the source
field feeds every hop-1 asset and every discovered SQL module. Later hops are
joined through a shared bus so the picture never invents a parent for a node.
"""

from __future__ import annotations

from dataclasses import dataclass, field

NODE_W = 188
NODE_H = 62
COL_GAP = 92
ROW_GAP = 20
LANE_GAP = 70
PAD = 24


@dataclass(frozen=True)
class GraphNode:
    id: str
    x: float
    y: float
    kind: str
    label: str
    sub: str
    badge: str
    w: int = NODE_W
    h: int = NODE_H

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass(frozen=True)
class GraphEdge:
    path: str
    kind: str
    label: str = ""
    lx: float = 0
    ly: float = 0


@dataclass
class LineageGraph:
    width: float
    height: float
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    buses: list[tuple[float, float, float]] = field(default_factory=list)
    lane_y: float = 0
    columns: list[tuple[float, str]] = field(default_factory=list)


def _trim(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _curve(x1: float, y1: float, x2: float, y2: float) -> str:
    mid = (x1 + x2) / 2
    return f"M{x1:.1f},{y1:.1f} C{mid:.1f},{y1:.1f} {mid:.1f},{y2:.1f} {x2:.1f},{y2:.1f}"


def build_lineage_graph(analysis) -> LineageGraph:
    assets = list(analysis.impact.impacted_assets)
    modules = list(analysis.sql_dependencies)
    hops = sorted({asset.hop for asset in assets}) or []
    by_hop = {hop: [asset for asset in assets if asset.hop == hop] for hop in hops}
    tallest = max([1, *(len(items) for items in by_hop.values())])
    lane_h = tallest * NODE_H + (tallest - 1) * ROW_GAP

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    buses: list[tuple[float, float, float]] = []
    columns: list[tuple[float, str]] = []

    col_x = lambda index: PAD + index * (NODE_W + COL_GAP)  # noqa: E731
    top = PAD + 26
    source = GraphNode(
        id="source",
        x=col_x(0),
        y=top + (lane_h - NODE_H) / 2,
        kind="source",
        label=_trim(analysis.source_label, 26),
        sub=_trim(analysis.source_owner, 30),
        badge="SOURCE",
    )
    nodes.append(source)
    columns.append((source.cx, "Source field"))

    previous: list[GraphNode] = [source]
    for index, hop in enumerate(hops, start=1):
        items = by_hop[hop]
        block_h = len(items) * NODE_H + (len(items) - 1) * ROW_GAP
        start_y = top + (lane_h - block_h) / 2
        current: list[GraphNode] = []
        for row, asset in enumerate(items):
            node = GraphNode(
                id=f"asset-{index}-{row}",
                x=col_x(index),
                y=start_y + row * (NODE_H + ROW_GAP),
                kind="critical" if asset.critical else "dataset",
                label=_trim(asset.name, 26),
                sub=_trim(asset.owners[0] if asset.owners else asset.entity_type, 30),
                badge="CRITICAL" if asset.critical else asset.entity_type.upper()[:12],
            )
            nodes.append(node)
            current.append(node)
        columns.append((col_x(index) + NODE_W / 2, f"Hop {hop}"))
        if index == 1:
            for node in current:
                path = _curve(source.x + NODE_W, source.cy, node.x, node.cy)
                edges.append(GraphEdge(path=path, kind="lineage"))
        else:
            bus_x = col_x(index) - COL_GAP / 2
            ys = [node.cy for node in previous + current]
            buses.append((bus_x, min(ys), max(ys)))
            for node in previous:
                path = f"M{node.x + NODE_W:.1f},{node.cy:.1f} L{bus_x:.1f},{node.cy:.1f}"
                edges.append(GraphEdge(path=path, kind="bus"))
            for node in current:
                path = f"M{bus_x:.1f},{node.cy:.1f} L{node.x:.1f},{node.cy:.1f}"
                edges.append(GraphEdge(path=path, kind="bus-arrow"))
        previous = current

    lane_y = top + lane_h + LANE_GAP
    if modules:
        for index, module in enumerate(modules):
            node = GraphNode(
                id=f"sql-{index}",
                x=col_x(1) + index * (NODE_W + 18),
                y=lane_y,
                kind="sql-review" if module.manual_review_reason else "sql",
                label=_trim(f"{module.schema_name}.{module.object_name}", 26),
                sub=_trim(", ".join(module.regions) if module.regions else "region unknown", 30),
                badge=module.match_kind.value.upper(),
            )
            nodes.append(node)
            edges.append(
                GraphEdge(
                    path=_curve(source.x + NODE_W, source.cy + 10, node.x, node.cy),
                    kind="hidden",
                    label=module.match_kind.value.upper(),
                    lx=(source.x + NODE_W + node.x) / 2,
                    ly=(source.cy + node.cy) / 2 - 4,
                )
            )
    width = max(node.x + node.w for node in nodes) + PAD
    height = max(node.y + node.h for node in nodes) + PAD + (26 if modules else 0)
    return LineageGraph(width=width, height=height, nodes=nodes, edges=edges, buses=buses, lane_y=lane_y, columns=columns)
