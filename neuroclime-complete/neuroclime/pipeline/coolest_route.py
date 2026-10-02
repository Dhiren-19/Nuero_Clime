"""
F8 — Coolest Route Planner (P2, PRD 1.3 / User Flow 1 step 7).

"Generates paths that minimize cumulative heat exposure rather than just
distance." Builds a graph where nodes are hex zones and edges connect H3
grid-adjacent hexes (h3.grid_ring distance 1), weighted by the average
current (horizon=0) heat index of the two endpoint hexes — so a shortest-
path search naturally prefers a longer route through parks over a short
route across a fully paved, high-heat-index corridor.

This is a genuine minimize-cumulative-exposure search (via networkx
Dijkstra), not a placeholder — but it operates over hex *centroids*, not a
real pedestrian street network (that would need OSM routing data per TRD
2.3.3's OSM ingestion, wired to a proper routing engine like OSRM/Valhalla,
which is out of scope for this handoff). Treat the returned path as
"which hexes to prefer," not turn-by-turn walking directions.
"""
from __future__ import annotations

import h3
import networkx as nx


def _haversine_km(lon1, lat1, lon2, lat2):
    from math import radians, sin, cos, sqrt, atan2

    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def _nearest_hex(hex_index: dict, lon: float, lat: float) -> str:
    best, best_d = None, float("inf")
    for hex_id, info in hex_index.items():
        d = _haversine_km(lon, lat, info["lon"], info["lat"])
        if d < best_d:
            best, best_d = hex_id, d
    return best


def build_graph(hex_zones: list[dict], predictions_now: list[dict]) -> tuple[nx.Graph, dict]:
    """hex_zones: rows with hex_id + centroid GeoJSON. predictions_now: horizon=0 rows."""
    heat_by_hex = {p["hex_id"]: p["heat_index_c"] for p in predictions_now}
    hex_index = {}
    for hz in hex_zones:
        centroid = hz.get("centroid") or {}
        coords = centroid.get("coordinates")
        if not coords:
            continue
        hex_index[hz["hex_id"]] = {"lon": coords[0], "lat": coords[1]}

    g = nx.Graph()
    for hex_id, info in hex_index.items():
        g.add_node(hex_id, **info, heat_index_c=heat_by_hex.get(hex_id, 35.0))

    for hex_id in hex_index:
        try:
            neighbors = h3.grid_ring(hex_id, 1)
        except Exception:
            continue
        for n in neighbors:
            if n in hex_index:
                w1 = heat_by_hex.get(hex_id, 35.0)
                w2 = heat_by_hex.get(n, 35.0)
                # Weight = average heat index of the two hexes (higher = costlier to cross).
                weight = max(0.1, (w1 + w2) / 2)
                g.add_edge(hex_id, n, weight=weight)

    return g, hex_index


def find_coolest_route(hex_zones: list[dict], predictions_now: list[dict], origin, destination) -> dict:
    """origin/destination: (lon, lat) tuples. Returns the coolest path plus a
    same-hex-count 'shortest' comparison path for context."""
    g, hex_index = build_graph(hex_zones, predictions_now)
    if not hex_index:
        raise ValueError("No hex zones with centroids available to route over.")

    start = _nearest_hex(hex_index, *origin)
    end = _nearest_hex(hex_index, *destination)

    if start == end:
        return {"path_hex_ids": [start], "path_coords": [[hex_index[start]["lon"], hex_index[start]["lat"]]],
                "total_heat_exposure": g.nodes[start]["heat_index_c"], "hex_count": 1}

    try:
        path = nx.dijkstra_path(g, start, end, weight="weight")
    except (nx.NetworkXNoPath, nx.NodeNotFound) as e:
        raise ValueError(f"No route found between origin and destination hexes: {e}")

    total_exposure = sum(g.nodes[h]["heat_index_c"] for h in path)
    coords = [[hex_index[h]["lon"], hex_index[h]["lat"]] for h in path]

    # Comparison: plain shortest hop-count path (ignores heat), to show the trade-off.
    try:
        naive_path = nx.shortest_path(g, start, end)
        naive_exposure = sum(g.nodes[h]["heat_index_c"] for h in naive_path)
    except nx.NetworkXNoPath:
        naive_exposure = None

    return {
        "path_hex_ids": path,
        "path_coords": coords,
        "hex_count": len(path),
        "total_heat_exposure": round(total_exposure, 1),
        "avg_heat_index_c": round(total_exposure / len(path), 2),
        "naive_shortest_path_exposure": round(naive_exposure, 1) if naive_exposure else None,
    }
