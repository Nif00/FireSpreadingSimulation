"""A lightweight QUIC-URB-inspired diagnostic urban wind field.

This is intentionally not a reimplementation of the proprietary QUIC-URB
solver.  It rasterizes the available OSM building massing onto a regular grid,
then applies local speed reduction and obstacle-aware steering to a prescribed
background wind.  The field is useful as a first coupling between the 3D OSM
scene and the graph fire-front model while the full fluid solver remains out
of scope.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


def _point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    """Return whether a point is inside a polygon using ray casting."""
    inside = False
    previous_x, previous_y = polygon[-1]
    for current_x, current_y in polygon:
        crosses = (current_y > y) != (previous_y > y)
        if crosses:
            intersection_x = (previous_x - current_x) * (y - current_y) / (
                previous_y - current_y
            ) + current_x
            if x < intersection_x:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside


def _effective_height(building: Mapping[str, Any], unknown_height_m: float) -> float:
    height = max(
        float(building.get("height_m") or 0.0),
        float(building.get("min_height_m") or 0.0),
    )
    return height if height > 0.0 else unknown_height_m


@dataclass(frozen=True, slots=True)
class WindSample:
    """Local wind values used by the fire propagation heuristic."""

    speed_mps: float
    direction_deg: float
    obstruction: float
    building_height_m: float


@dataclass(frozen=True, slots=True)
class UrbanWindField:
    """Regular-grid urban wind approximation over the OSM building layer."""

    origin_x: float
    origin_y: float
    cell_size_m: float
    width: int
    height: int
    heights: tuple[float, ...]
    base_wind_speed_mps: float
    base_wind_direction_deg: float
    unknown_height_m: float
    obstacle_cells: int

    @classmethod
    def from_buildings(
        cls,
        buildings: Iterable[Mapping[str, Any]],
        bounds: tuple[float, float, float, float],
        *,
        wind_speed_mps: float,
        wind_direction_deg: float,
        cell_size_m: float = 100.0,
        unknown_height_m: float = 3.0,
    ) -> "UrbanWindField":
        """Build an obstacle grid from ``(min_x, max_x, min_y, max_y)``."""
        if cell_size_m <= 0:
            raise ValueError("cell_size_m must be positive")
        if wind_speed_mps < 0:
            raise ValueError("wind_speed_mps must not be negative")
        if not 0 <= wind_direction_deg < 360:
            raise ValueError("wind_direction_deg must be in [0, 360)")
        if unknown_height_m < 0:
            raise ValueError("unknown_height_m must not be negative")

        min_x, max_x, min_y, max_y = bounds
        origin_x = math.floor(min_x / cell_size_m) * cell_size_m - cell_size_m
        origin_y = math.floor(min_y / cell_size_m) * cell_size_m - cell_size_m
        width = max(1, math.ceil((max_x - origin_x) / cell_size_m) + 1)
        height = max(1, math.ceil((max_y - origin_y) / cell_size_m) + 1)
        grid = [0.0] * (width * height)

        obstacle_count = 0
        for building in buildings:
            raw_polygon = building.get("polygon", [])
            if not isinstance(raw_polygon, list):
                continue
            polygon = [
                (float(point[0]), float(point[1]))
                for point in raw_polygon
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ]
            if len(polygon) < 3:
                continue
            height_m = _effective_height(building, unknown_height_m)
            polygon_min_x = min(point[0] for point in polygon)
            polygon_max_x = max(point[0] for point in polygon)
            polygon_min_y = min(point[1] for point in polygon)
            polygon_max_y = max(point[1] for point in polygon)
            min_cell_x = max(0, math.floor((polygon_min_x - origin_x) / cell_size_m))
            max_cell_x = min(width - 1, math.floor((polygon_max_x - origin_x) / cell_size_m))
            min_cell_y = max(0, math.floor((polygon_min_y - origin_y) / cell_size_m))
            max_cell_y = min(height - 1, math.floor((polygon_max_y - origin_y) / cell_size_m))

            touched: set[int] = set()
            for cell_y in range(min_cell_y, max_cell_y + 1):
                center_y = origin_y + (cell_y + 0.5) * cell_size_m
                for cell_x in range(min_cell_x, max_cell_x + 1):
                    center_x = origin_x + (cell_x + 0.5) * cell_size_m
                    if _point_in_polygon(center_x, center_y, polygon):
                        touched.add(cell_y * width + cell_x)
            # Small footprints can fall between cell centres; retain their
            # centroid cell so they still influence the local wind field.
            centroid_x = sum(point[0] for point in polygon) / len(polygon)
            centroid_y = sum(point[1] for point in polygon) / len(polygon)
            centroid_cell_x = math.floor((centroid_x - origin_x) / cell_size_m)
            centroid_cell_y = math.floor((centroid_y - origin_y) / cell_size_m)
            if 0 <= centroid_cell_x < width and 0 <= centroid_cell_y < height:
                touched.add(centroid_cell_y * width + centroid_cell_x)
            for index in touched:
                if grid[index] == 0.0:
                    obstacle_count += 1
                grid[index] = max(grid[index], height_m)

        return cls(
            origin_x=origin_x,
            origin_y=origin_y,
            cell_size_m=cell_size_m,
            width=width,
            height=height,
            heights=tuple(grid),
            base_wind_speed_mps=wind_speed_mps,
            base_wind_direction_deg=wind_direction_deg,
            unknown_height_m=unknown_height_m,
            obstacle_cells=obstacle_count,
        )

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "name": "QUIC-URB-inspired diagnostic urban wind",
            "cell_size_m": self.cell_size_m,
            "grid": {"width": self.width, "height": self.height},
            "obstacle_cells": self.obstacle_cells,
            "base_wind_speed_mps": self.base_wind_speed_mps,
            "base_wind_direction_deg": self.base_wind_direction_deg,
            "unknown_height_m": self.unknown_height_m,
            "note": "Heuristic building blockage and steering; not the QUIC-URB solver.",
        }

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        return (
            max(0, min(self.width - 1, math.floor((x - self.origin_x) / self.cell_size_m))),
            max(0, min(self.height - 1, math.floor((y - self.origin_y) / self.cell_size_m))),
        )

    def _height_at_cell(self, cell_x: int, cell_y: int) -> float:
        cell_x = max(0, min(self.width - 1, cell_x))
        cell_y = max(0, min(self.height - 1, cell_y))
        return self.heights[cell_y * self.width + cell_x]

    def sample(self, x: float, y: float) -> WindSample:
        """Sample speed and direction at a local projected coordinate."""
        cell_x, cell_y = self._cell(x, y)
        center_height = self._height_at_cell(cell_x, cell_y)
        west = self._height_at_cell(cell_x - 1, cell_y)
        east = self._height_at_cell(cell_x + 1, cell_y)
        south = self._height_at_cell(cell_x, cell_y - 1)
        north = self._height_at_cell(cell_x, cell_y + 1)
        gradient_x = (east - west) / (2.0 * self.cell_size_m)
        gradient_y = (north - south) / (2.0 * self.cell_size_m)
        gradient_length = math.hypot(gradient_x, gradient_y)
        neighbor_height = max(west, east, south, north)
        obstruction = min(
            1.0,
            max(center_height / 18.0, neighbor_height / 28.0),
        )

        direction_radians = math.radians(self.base_wind_direction_deg)
        base_x = math.cos(direction_radians)
        base_y = math.sin(direction_radians)
        adjusted_x, adjusted_y = base_x, base_y
        if gradient_length > 1e-9:
            gradient_x /= gradient_length
            gradient_y /= gradient_length
            incoming = max(0.0, base_x * gradient_x + base_y * gradient_y)
            # Remove the component entering a building wall and add a small
            # lateral component to represent flow being diverted around it.
            adjusted_x -= 0.85 * incoming * gradient_x
            adjusted_y -= 0.85 * incoming * gradient_y
            side = -1.0 if base_x * gradient_y - base_y * gradient_x > 0 else 1.0
            adjusted_x += side * 0.30 * incoming * (-gradient_y)
            adjusted_y += side * 0.30 * incoming * gradient_x
        adjusted_length = math.hypot(adjusted_x, adjusted_y)
        if adjusted_length > 1e-9:
            adjusted_x /= adjusted_length
            adjusted_y /= adjusted_length
        speed_factor = max(0.25, 1.0 - 0.50 * obstruction)
        return WindSample(
            speed_mps=self.base_wind_speed_mps * speed_factor,
            direction_deg=math.degrees(math.atan2(adjusted_y, adjusted_x)) % 360,
            obstruction=obstruction,
            building_height_m=center_height,
        )

    def sample_edge(
        self,
        source_x: float,
        source_y: float,
        target_x: float,
        target_y: float,
    ) -> WindSample:
        """Average three samples along an edge for stable graph coupling."""
        samples = [
            self.sample(source_x, source_y),
            self.sample((source_x + target_x) / 2.0, (source_y + target_y) / 2.0),
            self.sample(target_x, target_y),
        ]
        vector_x = sum(sample.speed_mps * math.cos(math.radians(sample.direction_deg)) for sample in samples) / len(samples)
        vector_y = sum(sample.speed_mps * math.sin(math.radians(sample.direction_deg)) for sample in samples) / len(samples)
        return WindSample(
            speed_mps=math.hypot(vector_x, vector_y),
            direction_deg=math.degrees(math.atan2(vector_y, vector_x)) % 360,
            obstruction=sum(sample.obstruction for sample in samples) / len(samples),
            building_height_m=max(sample.building_height_m for sample in samples),
        )
