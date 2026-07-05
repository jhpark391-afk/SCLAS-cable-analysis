#!/usr/bin/env python3
"""Lightweight Abaqus INP mesh preview parser for the HELIX GUI.

This module intentionally reads only the data needed for visual review:
part nodes, C3D-style element connectivity, and assembly instance z-axis
rotations/translations. It is not a solver or an Abaqus deck validator.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


PART_COLORS = {
    "Core": (0.96, 0.56, 0.20, 0.95),
    "Filler": (0.98, 0.76, 0.24, 0.95),
    "Inner Sheath": (0.40, 0.86, 0.86, 0.95),
    "Bedding": (0.56, 0.74, 0.42, 0.95),
    "Outer Sheath": (0.24, 0.58, 0.96, 0.95),
    "Inner Armour": (0.84, 0.62, 0.96, 0.95),
    "Outer Armour": (0.94, 0.42, 0.56, 0.95),
}


@dataclass
class InpInstance:
    name: str
    part: str
    translation: Tuple[float, float, float]
    angle_deg: float


@dataclass
class InpMeshPreview:
    source_path: str
    preview_mode: str
    part_summaries: List[dict]
    instance_summaries: List[dict]
    segments_by_part: Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]]
    bounds_xy: Tuple[float, float, float, float]


def _numbers(line: str) -> List[float]:
    return [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?", line)]


def _ints(line: str) -> List[int]:
    return [int(float(x)) for x in re.findall(r"[-+]?\d+", line)]


def _keyword_value(line: str, key: str) -> Optional[str]:
    match = re.search(rf"{key}=([^,]+)", line, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip().strip('"')


def parse_inp_parts_and_instances(path: Path) -> Tuple[dict, List[InpInstance]]:
    parts: dict = {}
    instances: List[InpInstance] = []
    current_part: Optional[str] = None
    current_mode: Optional[str] = None
    current_instance: Optional[dict] = None
    pending_instance_lines: List[str] = []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("**"):
                continue
            lower = line.lower()

            if lower.startswith("*part"):
                name = _keyword_value(line, "name")
                if name:
                    current_part = name
                    parts[name] = {"nodes": {}, "elements": []}
                current_mode = None
                continue
            if lower.startswith("*end part"):
                current_part = None
                current_mode = None
                continue
            if current_part and lower.startswith("*node"):
                current_mode = "node"
                continue
            if current_part and lower.startswith("*element"):
                current_mode = "element"
                continue

            if line.startswith("*"):
                current_mode = None
                if lower.startswith("*instance"):
                    current_instance = {
                        "name": _keyword_value(line, "name") or "",
                        "part": _keyword_value(line, "part") or "",
                        "translation": (0.0, 0.0, 0.0),
                        "angle_deg": 0.0,
                    }
                    pending_instance_lines = []
                elif lower.startswith("*end instance") and current_instance:
                    numeric_rows = [_numbers(item) for item in pending_instance_lines if _numbers(item)]
                    if len(numeric_rows) >= 1 and len(numeric_rows[0]) >= 3:
                        current_instance["translation"] = tuple(numeric_rows[0][:3])
                    if len(numeric_rows) >= 2 and len(numeric_rows[1]) >= 7:
                        current_instance["angle_deg"] = numeric_rows[1][-1]
                    instances.append(InpInstance(**current_instance))
                    current_instance = None
                    pending_instance_lines = []
                continue

            if current_instance is not None:
                pending_instance_lines.append(line)
                continue

            if current_part and current_mode == "node":
                values = _numbers(line)
                if len(values) >= 4:
                    parts[current_part]["nodes"][int(values[0])] = (values[1], values[2], values[3])
            elif current_part and current_mode == "element":
                values = _ints(line)
                if len(values) >= 5:
                    parts[current_part]["elements"].append(values[1:])

    return parts, instances


def _rotate_xy(x: float, y: float, angle_deg: float) -> Tuple[float, float]:
    angle = math.radians(angle_deg)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return cos_a * x - sin_a * y, sin_a * x + cos_a * y


def _transformed_nodes(nodes: dict, instance: InpInstance) -> Dict[int, Tuple[float, float, float]]:
    tx, ty, tz = instance.translation
    transformed = {}
    for node_id, (x, y, z) in nodes.items():
        rx, ry = _rotate_xy(x, y, instance.angle_deg)
        transformed[node_id] = (rx + tx, ry + ty, z + tz)
    return transformed


def _element_edges(elements: Iterable[List[int]]) -> List[Tuple[int, int]]:
    edge_pairs = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    edges = set()
    for element in elements:
        if len(element) < 8:
            continue
        for first, second in edge_pairs:
            edges.add(tuple(sorted((element[first], element[second]))))
    return list(edges)


def _section_edges(
    edges: Iterable[Tuple[int, int]],
    nodes: Dict[int, Tuple[float, float, float]],
    z_tolerance: float,
) -> Tuple[List[Tuple[int, int]], float]:
    if not nodes:
        return [], 0.0
    section_z = min(point[2] for point in nodes.values())
    selected = []
    for first, second in edges:
        if first not in nodes or second not in nodes:
            continue
        z_first = nodes[first][2]
        z_second = nodes[second][2]
        if abs(z_first - section_z) <= z_tolerance and abs(z_second - section_z) <= z_tolerance:
            selected.append((first, second))
    return selected, section_z


def build_inp_mesh_preview(
    path: str | Path,
    max_edges_per_part_instance: int = 2500,
    preview_mode: str = "end_section",
    z_tolerance: float = 1.0e-6,
) -> InpMeshPreview:
    source = Path(path)
    parts, instances = parse_inp_parts_and_instances(source)
    instance_counts = defaultdict(int)
    part_summaries = []
    instance_summaries = []
    segments_by_part: Dict[str, List[Tuple[Tuple[float, float], Tuple[float, float]]]] = defaultdict(list)
    bounds = [1.0e30, 1.0e30, -1.0e30, -1.0e30]
    edge_cache: Dict[str, List[Tuple[int, int]]] = {}

    for part_name, part in parts.items():
        part_summaries.append({
            "part": part_name,
            "nodes": len(part["nodes"]),
            "elements": len(part["elements"]),
        })

    for instance in instances:
        if instance.part not in parts:
            continue
        instance_counts[instance.part] += 1
        instance_summaries.append({
            "name": instance.name,
            "part": instance.part,
            "angle_deg": instance.angle_deg,
        })
        part = parts[instance.part]
        nodes = _transformed_nodes(part["nodes"], instance)
        all_edges = edge_cache.setdefault(instance.part, _element_edges(part["elements"]))
        section_z = None
        edges = all_edges
        if preview_mode == "end_section":
            section_edges, section_z = _section_edges(all_edges, nodes, z_tolerance)
            if section_edges:
                edges = section_edges
        stride = max(1, len(edges) // max_edges_per_part_instance)
        for first, second in edges[::stride]:
            if first not in nodes or second not in nodes:
                continue
            start = nodes[first]
            end = nodes[second]
            segments_by_part[instance.part].append(((start[0], start[1]), (end[0], end[1])))
            for x, y, _z in (start, end):
                bounds[0] = min(bounds[0], x)
                bounds[1] = min(bounds[1], y)
                bounds[2] = max(bounds[2], x)
                bounds[3] = max(bounds[3], y)
        if section_z is not None:
            instance_summaries[-1]["section_z_mm"] = section_z

    if bounds[0] == 1.0e30:
        bounds = [-1.0, -1.0, 1.0, 1.0]

    part_summaries.sort(key=lambda item: item["part"])
    for summary in part_summaries:
        summary["instances"] = instance_counts.get(summary["part"], 0)

    return InpMeshPreview(
        source_path=str(source),
        preview_mode=preview_mode,
        part_summaries=part_summaries,
        instance_summaries=instance_summaries,
        segments_by_part=dict(segments_by_part),
        bounds_xy=tuple(bounds),
    )


def format_inp_mesh_summary(preview: InpMeshPreview) -> str:
    total_segments = sum(len(segments) for segments in preview.segments_by_part.values())
    lines = [
        "Abaqus INP mesh imported",
        f"source: {preview.source_path}",
        f"preview_mode: {preview.preview_mode}",
        f"parts: {len(preview.part_summaries)}",
        f"instances: {len(preview.instance_summaries)}",
        f"preview_segments: {total_segments}",
        "",
        "[Parts]",
    ]
    for part in preview.part_summaries:
        lines.append(
            f"- {part['part']}: nodes={part['nodes']}, elements={part['elements']}, "
            f"instances={part['instances']}"
        )
    return "\n".join(lines)
