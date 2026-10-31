"""大阪工業大学 枚方キャンパス周辺の徒歩道路を一度だけ保存するプログラム。"""

from pathlib import Path
import osmnx as ox

# (西の経度, 南の緯度, 東の経度, 北の緯度)
# 大阪工業大学 枚方キャンパスの周辺を、展示用に少し広めに取得する。
BBOX = (135.6990, 34.8350, 135.7130, 34.8460)
OUTPUT_PATH = Path(__file__).with_name("oit_hirakata_walk.graphml")

if OUTPUT_PATH.exists():
    print(f"{OUTPUT_PATH.name} はすでにあります。上書きしません。")
else:
    print("徒歩道路データを取得しています。しばらく待ってください。")
    print("途中でエラーになった場合は、連続実行せず時間を空けてから再実行してください。")

    graph = ox.graph_from_bbox(
        BBOX,
        network_type="walk",
        truncate_by_edge=True,
    )

    ox.save_graphml(graph, OUTPUT_PATH)
    print("保存しました。")
    print("交差点などの地点数：", len(graph.nodes))
    print("道路区間数：", len(graph.edges))
