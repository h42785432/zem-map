"""文化祭向け：4地域から大学へ向かう避難経路を表示するアプリ。"""

from pathlib import Path
import math

import folium
import osmnx as ox
import streamlit as st
from folium.features import DivIcon
from streamlit_folium import st_folium


st.set_page_config(page_title="大学周辺 迂回ルートマップ", layout="wide")

# download_oit_map.py で作成する、徒歩道路の保存ファイル。
GRAPH_PATH = Path(__file__).with_name("oit_hirakata_walk.graphml")

# 大阪工業大学 枚方キャンパスを、展示用シミュレーションの避難先とする。
# 実際の災害時には、自治体・大学の避難情報に従う。
CAMPUS = [34.84136, 135.70505]

# 大学の周囲を4地域に分ける。範囲と出発地点は展示用に決めた仮の設定。
# 座標の順番は [緯度, 経度]。
ZONES = {
    "北西地域": {
        "color": "#7c3aed",
        "start": [34.84290, 135.70260],
        "polygon": [
            [34.84140, 135.69980],
            [34.84500, 135.69980],
            [34.84500, 135.70500],
            [34.84140, 135.70500],
        ],
    },
    "北東地域": {
        "color": "#0284c7",
        "start": [34.84290, 135.70930],
        "polygon": [
            [34.84140, 135.70500],
            [34.84500, 135.70500],
            [34.84500, 135.71180],
            [34.84140, 135.71180],
        ],
    },
    "南西地域": {
        "color": "#16a34a",
        "start": [34.83740, 135.70260],
        "polygon": [
            [34.83600, 135.69980],
            [34.84140, 135.69980],
            [34.84140, 135.70500],
            [34.83600, 135.70500],
        ],
    },
    "南東地域": {
        "color": "#ea580c",
        "start": [34.83740, 135.70930],
        "polygon": [
            [34.83600, 135.70500],
            [34.84140, 135.70500],
            [34.84140, 135.71180],
            [34.83600, 135.71180],
        ],
    },
}

# OpenStreetMap の道路種別のうち、今回「大通り」として扱うもの。
MAJOR_ROAD_TYPES = ("primary", "secondary", "tertiary")

@st.cache_resource
def load_graph(path):
    """保存済みの道路ネットワークを読み込む。"""
    return ox.load_graphml(path)


def nearest_node(graph, point):
    """地図上の場所に最も近い道路ネットワーク上の地点を探す。"""
    latitude, longitude = point
    return min(
        graph.nodes,
        key=lambda node: (
            (graph.nodes[node]["y"] - latitude) ** 2
            + (graph.nodes[node]["x"] - longitude) ** 2
        ),
    )


def shortest_edge_data(graph, u, v):
    """同じ2地点を結ぶ道路が複数ある場合、短い道路を選ぶ。"""
    return min(
        graph.get_edge_data(u, v).values(),
        key=lambda data: data.get("length", float("inf")),
    )


def route_length_m(graph, route):
    """経路の合計距離を m で求める。"""
    return sum(
        shortest_edge_data(graph, u, v).get("length", 0)
        for u, v in zip(route, route[1:])
    )


def route_coordinates(graph, route):
    """経路を Folium 用の [緯度, 経度] の並びに変換する。"""
    coordinates = []

    for u, v in zip(route, route[1:]):
        edge = shortest_edge_data(graph, u, v)
        geometry = edge.get("geometry")

        if geometry is None:
            segment = [
                [graph.nodes[u]["y"], graph.nodes[u]["x"]],
                [graph.nodes[v]["y"], graph.nodes[v]["x"]],
            ]
        else:
            # Shapely は (経度, 緯度) なので、Folium 用に順番を入れ替える。
            segment = [[latitude, longitude] for longitude, latitude in geometry.coords]

        coordinates.extend(segment if not coordinates else segment[1:])

    return coordinates


def is_major_road(edge):
    """道路種別を見て、今回の展示で大通りに分類するかを決める。"""
    highway = str(edge.get("highway", ""))
    return any(road_type in highway for road_type in MAJOR_ROAD_TYPES)


def remove_road_segment(graph, u, v):
    """1つの道路区間を両方向とも通行止めにしたネットワークを返す。"""
    changed_graph = graph.copy()

    if changed_graph.has_edge(u, v):
        changed_graph.remove_edges_from(
            [(u, v, key) for key in list(changed_graph[u][v].keys())]
        )

    if changed_graph.has_edge(v, u):
        changed_graph.remove_edges_from(
            [(v, u, key) for key in list(changed_graph[v][u].keys())]
        )

    return changed_graph


def choose_major_road_to_close(graph, normal_route, start_node, campus_node):
    """通常経路上の大通りから、迂回経路が残る1区間を選ぶ。

    展示で『大通りが通れないと、経路が変わる』ことを見せるための簡単な設定。
    """
    normal_length = route_length_m(graph, normal_route)
    candidates = []

    for u, v in zip(normal_route, normal_route[1:]):
        edge = shortest_edge_data(graph, u, v)
        if not is_major_road(edge):
            continue

        changed_graph = remove_road_segment(graph, u, v)
        reroute = ox.shortest_path(changed_graph, start_node, campus_node, weight="length")

        if reroute is not None:
            extra_distance = route_length_m(changed_graph, reroute) - normal_length
            candidates.append((extra_distance, u, v, changed_graph, reroute))

    if not candidates:
        return None

    # 迂回が一番分かりやすい候補を使う。
    return max(candidates, key=lambda candidate: candidate[0])


st.title("大阪工業大学周辺　迂回ルートマップ")
st.caption(
    "4地域から大阪工業大学 枚方キャンパスへ向かう経路を、道路状況別に比べる展示用シミュレーションです。"
)

if not GRAPH_PATH.exists():
    st.error("道路データがありません。先に download_oit_map.py を実行してください。")
    st.code(r".\.venv\Scripts\python.exe download_oit_map.py")
    st.stop()

graph = load_graph(GRAPH_PATH)

with st.sidebar:
    st.header("条件を選ぶ")
    zone_name = st.selectbox("出発地域", list(ZONES.keys()))
    road_condition = st.radio(
        "道路の状況",
        ["すべての道が使える", "大通りの一部が通行止め"],
    )
    st.divider()
    st.caption("大通りは OpenStreetMap の道路種別をもとに、展示用に分類しています。")

zone = ZONES[zone_name]
start_point = zone["start"]
start_node = nearest_node(graph, start_point)
campus_node = nearest_node(graph, CAMPUS)

normal_route = ox.shortest_path(graph, start_node, campus_node, weight="length")
if normal_route is None:
    st.error("通常時の経路を計算できませんでした。")
    st.stop()

normal_length = route_length_m(graph, normal_route)
active_graph = graph
active_route = normal_route
blocked_edge = None

if road_condition == "大通りの一部が通行止め":
    result = choose_major_road_to_close(graph, normal_route, start_node, campus_node)

    if result is None:
        st.warning("この地域の通常経路には、迂回できる大通りが見つかりませんでした。通常時の経路を表示します。")
    else:
        _, blocked_u, blocked_v, active_graph, active_route = result
        blocked_edge = (blocked_u, blocked_v)

active_length = route_length_m(active_graph, active_route)
normal_points = route_coordinates(graph, normal_route)
active_points = route_coordinates(active_graph, active_route)

# 選択した地域と大学が、地図いっぱいに入るよう表示範囲を求める。
view_points = zone["polygon"] + [CAMPUS]
view_south = min(point[0] for point in view_points) - 0.0003
view_north = max(point[0] for point in view_points) + 0.0003
view_west = min(point[1] for point in view_points) - 0.0003
view_east = max(point[1] for point in view_points) + 0.0003

route_map = folium.Map(
    location=CAMPUS,
    zoom_start=16,
    min_zoom=14,
    tiles="OpenStreetMap",
)
route_map.fit_bounds(
    [[view_south, view_west], [view_north, view_east]],
    padding=(30, 30),
)

# 4地域をまとめた対象範囲を、落ち着いた色の外枠で示す。
folium.Rectangle(
    bounds=[[34.83600, 135.69980], [34.84500, 135.71180]],
    color="#44403c",
    weight=3,
    fill=False,
    dash_array="7 5",
    tooltip="経路探索の対象範囲",
).add_to(route_map)

# 4つの地域を半透明の色で示す。
for name, area in ZONES.items():
    selected = name == zone_name
    folium.Polygon(
        locations=area["polygon"],
        color=area["color"],
        weight=4 if selected else 1,
        fill=True,
        fill_color=area["color"],
        fill_opacity=0.17 if selected else 0.035,
        tooltip=f"{name}{'（選択中）' if selected else ''}",
    ).add_to(route_map)

    folium.Marker(
        area["start"],
        icon=DivIcon(
            html=(
                f'<div style="font-size:12px; color:{area["color"]}; '
                'font-weight:bold; white-space:nowrap;">'
                f'{name}</div>'
            )
        ),
    ).add_to(route_map)

if blocked_edge is not None:
    # 通常時の経路を破線で残し、どこが変わったか比較できるようにする。
    folium.PolyLine(
        normal_points,
        color="#64748b",
        weight=4,
        opacity=0.75,
        dash_array="8 8",
        tooltip="すべての道が使える場合の最短経路",
    ).add_to(route_map)

    folium.PolyLine(
        route_coordinates(graph, list(blocked_edge)),
        color="#dc2626",
        weight=10,
        opacity=0.95,
        tooltip="大通りの通行止め区間",
    ).add_to(route_map)

# 今の条件で選ばれた経路は、白い縁取りと青線で強調する。
folium.PolyLine(active_points, color="white", weight=11, opacity=0.96).add_to(route_map)
folium.PolyLine(
    active_points,
    color="#2563eb",
    weight=7,
    opacity=1,
    tooltip="現在の避難経路",
).add_to(route_map)

folium.Marker(
    start_point,
    tooltip=f"出発地：{zone_name}",
    icon=folium.Icon(color="green", icon="play"),
).add_to(route_map)
folium.Marker(
    CAMPUS,
    tooltip="避難先：大阪工業大学 枚方キャンパス（展示用設定）",
    icon=folium.Icon(color="red", icon="flag"),
).add_to(route_map)

def result_card(label, value, note, accent_color):
    """検索結果を、大きく見やすいカードとして表示する。"""
    return f"""
    <div style="
        background: #faf9f6;
        border: 1px solid #d6d3d1;
        border-top: 5px solid {accent_color};
        border-radius: 6px;
        padding: 17px 20px;
        min-height: 128px;">
        <div style="font-size: 16px; font-weight: 600; color: #57534e;">
            {label}
        </div>
        <div style="font-size: 37px; font-weight: 700; color: #292524; line-height: 1.4;">
            {value}
        </div>
        <div style="font-size: 14px; color: #78716c;">
            {note}
        </div>
    </div>
    """

st.subheader("検索結果")
card_distance, card_time, card_change = st.columns(3)

card_distance.markdown(
    result_card(
        "避難距離",
        f"{active_length / 1000:.2f} km",
        f"出発：{zone_name}",
        "#355b66",
    ),
    unsafe_allow_html=True,
)

card_time.markdown(
    result_card(
        "推定時間",
        f"約 {math.ceil(active_length / 80)} 分",
        "徒歩を1分あたり約80 mとして計算",
        "#556b4f",
    ),
    unsafe_allow_html=True,
)

if blocked_edge is not None:
    increased_distance = active_length - normal_length
    card_change.markdown(
        result_card(
            "通常時から増えた距離",
            f"+{increased_distance:.0f} m",
            f"通常時：{normal_length / 1000:.2f} km",
            "#8a4b3a",
        ),
        unsafe_allow_html=True,
    )
    st.warning("赤：通行止め　灰色の破線：通常時の経路　青：通行止め後の避難経路")
else:
    card_change.markdown(
        result_card(
            "道路状況",
            "通常時",
            "すべての道が使用できます",
            "#68645f",
        ),
        unsafe_allow_html=True,
    )
    st.info("青い線が、すべての道が使える場合の最短経路です。")
st.subheader("避難ルート地図")
st.caption("色付きの範囲：4地域　青：現在の避難経路　赤：通行止め　灰色の破線：通常時の経路")
st_folium(route_map, width=None, height=680, key="four_zone_evacuation_map")

st.caption(
    "注意：これは経路探索を学ぶための展示用シミュレーションです。"
    "実際の避難では、自治体・大学などの公式情報に従ってください。"
)