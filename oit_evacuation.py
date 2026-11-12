"""大阪工業大学を避難所とした周辺4地区からの通常経路と迂回経路を比較するアプリ"""

from pathlib import Path
import math

import folium
import osmnx as ox
import streamlit as st
from streamlit_folium import st_folium


GRAPH_PATH = Path(__file__).with_name("oit_hirakata_walk.graphml")
CAMPUS = [34.84136, 135.70505]
MAP_BOUNDS = [[34.83600, 135.69980], [34.84500, 135.71180]]
MAJOR_ROADS = ("primary", "secondary", "tertiary")


def rectangle(south, west, north, east):
    """南西端と北東端から長方形の座標を作る"""
    return [[south, west], [north, west], [north, east], [south, east]]


# 各地域の色、出発地点、表示範囲
ZONES = {
    "北西地域": {
        "color": "#7c3aed",
        "start": [34.84290, 135.70260],
        "polygon": rectangle(34.84140, 135.69980, 34.84500, 135.70500),
    },
    "北東地域": {
        "color": "#0284c7",
        "start": [34.84290, 135.70930],
        "polygon": rectangle(34.84140, 135.70500, 34.84500, 135.71180),
    },
    "南西地域": {
        "color": "#16a34a",
        "start": [34.83740, 135.70260],
        "polygon": rectangle(34.83600, 135.69980, 34.84140, 135.70500),
    },
    "南東地域": {
        "color": "#ea580c",
        "start": [34.83740, 135.70930],
        "polygon": rectangle(34.83600, 135.70500, 34.84140, 135.71180),
    },
}


@st.cache_resource
def load_graph():
    """保存済みの道路ネットワークを読み込む"""
    return ox.load_graphml(GRAPH_PATH)


def nearest_node(graph, point):
    """指定座標に最も近い道路上のノードを返す"""
    latitude, longitude = point
    return min(
        graph.nodes,
        key=lambda node: (
            (graph.nodes[node]["y"] - latitude) ** 2
            + (graph.nodes[node]["x"] - longitude) ** 2
        ),
    )


def route_edges(route):
    """経路を、隣り合うノードの組に分ける"""
    return zip(route, route[1:])


def edge_data(graph, u, v):
    """2地点間に複数の道路がある場合、最も短い道路を返す"""
    return min(
        graph.get_edge_data(u, v).values(),
        key=lambda data: data.get("length", float("inf")),
    )


def route_length(graph, route):
    """経路の合計距離をメートルで求める"""
    return sum(
        edge_data(graph, u, v).get("length", 0)
        for u, v in route_edges(route)
    )


def route_points(graph, route):
    """経路をFoliumで描画できる座標列に変換する"""
    points = []

    for u, v in route_edges(route):
        geometry = edge_data(graph, u, v).get("geometry")

        if geometry is None:
            segment = [
                [graph.nodes[u]["y"], graph.nodes[u]["x"]],
                [graph.nodes[v]["y"], graph.nodes[v]["x"]],
            ]
        else:
            # geometryは(経度, 緯度)、Foliumは(緯度, 経度)の順番
            segment = [[lat, lon] for lon, lat in geometry.coords]

        points.extend(segment if not points else segment[1:])

    return points


def is_major_road(data):
    """OpenStreetMapの道路種別から大通りかを判定する"""
    highway = str(data.get("highway", ""))
    return any(road_type in highway for road_type in MAJOR_ROADS)


def close_road(graph, u, v):
    """指定した道路区間を両方向とも削除したコピーを返す"""
    changed_graph = graph.copy()

    for start, end in [(u, v), (v, u)]:
        if changed_graph.has_edge(start, end):
            keys = list(changed_graph[start][end].keys())
            changed_graph.remove_edges_from((start, end, key) for key in keys)

    return changed_graph


def find_reroute(graph, normal_route, start_node, goal_node):
    """通常経路上から、迂回が最も分かりやすい大通りを1区間選ぶ"""
    normal_distance = route_length(graph, normal_route)
    best_result = None

    for u, v in route_edges(normal_route):
        if not is_major_road(edge_data(graph, u, v)):
            continue

        changed_graph = close_road(graph, u, v)

        # OSMnxのshortest_pathは、道路の長さを重みにして
        # ダイクストラ法で最短経路を探索する
        reroute = ox.shortest_path(
            changed_graph,
            start_node,
            goal_node,
            weight="length",
        )

        if reroute is None:
            continue

        extra_distance = route_length(changed_graph, reroute) - normal_distance
        candidate = (extra_distance, (u, v), changed_graph, reroute)

        if best_result is None or extra_distance > best_result[0]:
            best_result = candidate

    return best_result


def create_map(zone_name, graph, normal_route, active_graph, active_route, blocked_edge):
    """地域、経路、通行止め区間をFolium地図に描画する。"""
    route_map = folium.Map(location=CAMPUS, tiles="OpenStreetMap")
    route_map.fit_bounds(MAP_BOUNDS, padding=(30, 30))

    folium.Rectangle(
        bounds=MAP_BOUNDS,
        color="#44403c",
        weight=3,
        fill=False,
        dash_array="7 5",
        tooltip="経路探索の対象範囲",
    ).add_to(route_map)

    for name, zone in ZONES.items():
        selected = name == zone_name
        folium.Polygon(
            locations=zone["polygon"],
            color=zone["color"],
            weight=4 if selected else 1,
            fill=True,
            fill_color=zone["color"],
            fill_opacity=0.17 if selected else 0.04,
            tooltip=f"{name}{'（選択中）' if selected else ''}",
        ).add_to(route_map)

    if blocked_edge is not None:
        folium.PolyLine(
            route_points(graph, normal_route),
            color="#64748b",
            weight=4,
            dash_array="8 8",
            tooltip="通常時の最短経路",
        ).add_to(route_map)
        folium.PolyLine(
            route_points(graph, blocked_edge),
            color="#dc2626",
            weight=10,
            tooltip="通行止め区間",
        ).add_to(route_map)

    active_points = route_points(active_graph, active_route)
    folium.PolyLine(active_points, color="white", weight=11).add_to(route_map)
    folium.PolyLine(
        active_points,
        color="#2563eb",
        weight=7,
        tooltip="現在の経路",
    ).add_to(route_map)

    folium.Marker(
        ZONES[zone_name]["start"],
        tooltip=f"出発地：{zone_name}",
        icon=folium.Icon(color="green", icon="play"),
    ).add_to(route_map)
    folium.Marker(
        CAMPUS,
        tooltip="目的地：大阪工業大学 枚方キャンパス",
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(route_map)

    return route_map


def main():
    st.set_page_config(page_title="大学周辺 迂回ルートマップ", layout="wide")
    st.title("大阪工業大学周辺　迂回ルートマップ")
    st.caption("通常時の最短経路と、大通りが通れない場合の迂回経路を比較します")

    if not GRAPH_PATH.exists():
        st.error("道路データがありません。先に download_oit_map.py を実行してください")
        st.stop()

    with st.sidebar:
        st.header("条件を選ぶ")
        zone_name = st.selectbox("出発地域", list(ZONES))
        use_roadblock = st.radio(
            "道路の状況",
            ["すべての道が使える", "大通りの一部が通行止め"],
        ) == "大通りの一部が通行止め"
        st.divider()
        st.caption("大通りはOpenStreetMapの道路種別をもとに分類しています")

    graph = load_graph()
    start_node = nearest_node(graph, ZONES[zone_name]["start"])
    goal_node = nearest_node(graph, CAMPUS)

    # 通常時の最短経路を計算する
    normal_route = ox.shortest_path(graph, start_node, goal_node, weight="length")
    if normal_route is None:
        st.error("経路を計算できませんでした")
        st.stop()

    normal_distance = route_length(graph, normal_route)
    active_graph = graph
    active_route = normal_route
    blocked_edge = None

    if use_roadblock:
        result = find_reroute(graph, normal_route, start_node, goal_node)
        if result is None:
            st.warning("迂回できる大通りが見つからないため、通常経路を表示します")
        else:
            _, blocked_edge, active_graph, active_route = result

    active_distance = route_length(active_graph, active_route)
    walking_minutes = math.ceil(active_distance / 80)

    st.subheader("検索結果")
    distance_col, time_col, change_col = st.columns(3)
    distance_col.metric("避難距離", f"{active_distance / 1000:.2f} km")
    time_col.metric("推定時間", f"約 {walking_minutes} 分")

    if blocked_edge is None:
        change_col.metric("道路状況", "通常時")
        st.info("青：現在の最短経路")
    else:
        extra_distance = active_distance - normal_distance
        change_col.metric("通常時から増えた距離", f"+{extra_distance:.0f} m")
        st.warning("赤：通行止め　灰色の破線：通常経路　青：迂回経路")

    route_map = create_map(
        zone_name,
        graph,
        normal_route,
        active_graph,
        active_route,
        blocked_edge,
    )

    st.subheader("避難ルート地図")
    st_folium(route_map, width=None, height=680, key="evacuation_map")
    st.caption(
        "注意：これは経路探索を学ぶための展示用シミュレーションです"
        "実際の避難では、自治体や大学などの公式情報に従ってください"
    )

if __name__ == "__main__":
    main()
