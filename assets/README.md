# Assets

该目录用于放置 README 使用的截图、导出的示例图或课程报告中需要引用的静态资源。

推荐流程：

1. 运行 `python src/medmap_china/render.py --config config/example_china_map.yaml`。
2. 从 `output/` 中挑选稳定版本复制到 `assets/`。
3. 在 README 中用相对路径引用，例如 `![示例地图](assets/china_province_choropleth.png)`。
