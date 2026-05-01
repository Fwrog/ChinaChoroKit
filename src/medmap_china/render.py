"""Render a China province choropleth map with the nine-dash line.

The script is intentionally configuration-driven so a GIS student can change
data values, classification breaks, colors, legend size, scale bar length, and
north arrow position without editing the plotting code.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any


def _import_runtime_dependencies() -> tuple[Any, ...]:
    try:
        import geopandas as gpd
        import matplotlib as mpl

        mpl.use("Agg")

        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd
        import yaml
        from matplotlib.patches import Patch, Polygon, Rectangle
    except ImportError as exc:
        missing = exc.name or "required package"
        raise SystemExit(
            f"缺少依赖 `{missing}`。请先执行：pip install -r requirements.txt"
        ) from exc

    return gpd, mpl, plt, np, pd, yaml, Patch, Polygon, Rectangle


(
    gpd,
    mpl,
    plt,
    np,
    pd,
    yaml,
    Patch,
    Polygon,
    Rectangle,
) = _import_runtime_dependencies()


PROVINCE_SUFFIX_REPLACEMENTS = (
    ("特别行政区", ""),
    ("维吾尔自治区", ""),
    ("壮族自治区", ""),
    ("回族自治区", ""),
    ("自治区", ""),
    ("省", ""),
    ("市", ""),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a China province choropleth map with the nine-dash line."
    )
    parser.add_argument(
        "--config",
        default="config/example_china_map.yaml",
        help="Path to a YAML configuration file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load data and print classification summary without writing figures.",
    )
    return parser.parse_args()


def load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    if not isinstance(config, dict):
        raise ValueError("配置文件顶层必须是 YAML object。")
    return config


def resolve_path(path_value: str | Path, base_dir: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def normalize_region_name(name: str) -> str:
    """Normalize common China province names for matching short user input.

    Examples:
    - 四川省 -> 四川
    - 重庆市 -> 重庆
    - 新疆维吾尔自治区 -> 新疆
    """

    normalized = str(name).strip()
    for old, new in PROVINCE_SUFFIX_REPLACEMENTS:
        normalized = normalized.replace(old, new)
    return normalized.strip()


def read_values(config: dict[str, Any], config_dir: Path) -> tuple[dict[str, float], list[str]]:
    data_config = config.get("data", {})
    name_column = data_config.get("name_column", "province")
    value_column = data_config.get("value_column", "value")
    aggregation = data_config.get("aggregation", "sum")
    records: list[tuple[str, float]] = []
    warnings: list[str] = []

    values_path = data_config.get("values_path")
    if values_path:
        path = resolve_path(values_path, config_dir)
        encoding = data_config.get("encoding", "utf-8-sig")
        if not path.exists():
            raise FileNotFoundError(f"找不到数据表：{path}")
        if path.suffix.lower() in {".xlsx", ".xls"}:
            df = pd.read_excel(path)
        else:
            df = pd.read_csv(path, encoding=encoding)
        missing_columns = {name_column, value_column} - set(df.columns)
        if missing_columns:
            raise ValueError(f"数据表缺少字段：{', '.join(sorted(missing_columns))}")
        for _, row in df[[name_column, value_column]].dropna(subset=[name_column]).iterrows():
            value = pd.to_numeric(row[value_column], errors="coerce")
            if pd.isna(value):
                warnings.append(f"跳过非数值记录：{row[name_column]}={row[value_column]}")
                continue
            records.append((str(row[name_column]).strip(), float(value)))

    inline_values = data_config.get("values", {})
    if isinstance(inline_values, dict):
        for name, value in inline_values.items():
            numeric = pd.to_numeric(value, errors="coerce")
            if pd.isna(numeric):
                warnings.append(f"跳过非数值内联记录：{name}={value}")
                continue
            records.append((str(name).strip(), float(numeric)))

    if not records:
        raise ValueError("没有读到任何省份数值，请检查 data.values_path 或 data.values。")

    values: dict[str, float] = {}
    for name, value in records:
        key = normalize_region_name(name)
        if aggregation == "last":
            values[key] = value
        elif aggregation == "sum":
            values[key] = values.get(key, 0.0) + value
        else:
            raise ValueError("data.aggregation 仅支持 sum 或 last。")

    return values, warnings


def load_geometries(config: dict[str, Any], config_dir: Path) -> tuple[Any, Any]:
    geo_config = config.get("geojson", {})
    geojson_path = resolve_path(geo_config.get("path", "中华人民共和国.geojson"), config_dir)
    if not geojson_path.exists():
        raise FileNotFoundError(f"找不到 GeoJSON：{geojson_path}")

    gdf = gpd.read_file(geojson_path)
    source_epsg = int(geo_config.get("source_epsg", 4326))
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=source_epsg)

    adcode_field = geo_config.get("adcode_field", "adcode")
    nine_dash_pattern = str(geo_config.get("nine_dash_pattern", "JD"))
    if adcode_field not in gdf.columns:
        raise ValueError(f"GeoJSON 缺少字段 `{adcode_field}`。")

    nine_mask = gdf[adcode_field].astype(str).str.contains(nine_dash_pattern, na=False)
    provinces = gdf.loc[~nine_mask].copy()
    nine_dash = gdf.loc[nine_mask].copy()
    if provinces.empty:
        raise ValueError("未识别到省级面要素。")
    if nine_dash.empty:
        print("警告：未识别到九段线要素，地图仍会继续生成。")
    return provinces, nine_dash


def attach_values(provinces: Any, values: dict[str, float], config: dict[str, Any]) -> tuple[Any, list[str]]:
    name_field = config.get("geojson", {}).get("name_field", "name")
    if name_field not in provinces.columns:
        raise ValueError(f"GeoJSON 缺少字段 `{name_field}`。")

    matched_keys: set[str] = set()
    mapped_values: list[float | None] = []
    for raw_name in provinces[name_field].astype(str):
        key = normalize_region_name(raw_name)
        if key in values:
            mapped_values.append(values[key])
            matched_keys.add(key)
        else:
            mapped_values.append(None)

    result = provinces.copy()
    result["value"] = mapped_values
    unmatched_input = sorted(set(values) - matched_keys)
    return result, unmatched_input


def jenks_breaks(values: list[float], class_count: int) -> list[float]:
    """Return Jenks natural breaks using dynamic programming.

    This avoids adding mapclassify as a hard dependency while preserving an
    ArcGIS-like classification option for small province-level datasets.
    """

    data = sorted(float(v) for v in values if math.isfinite(float(v)))
    if not data:
        raise ValueError("自然断点分类没有可用数值。")
    unique_count = len(set(data))
    class_count = max(1, min(int(class_count), unique_count))
    if class_count == 1:
        return [min(data), max(data)]

    n_data = len(data)
    lower = [[0] * (class_count + 1) for _ in range(n_data + 1)]
    variance = [[float("inf")] * (class_count + 1) for _ in range(n_data + 1)]

    for i in range(1, class_count + 1):
        lower[1][i] = 1
        variance[1][i] = 0.0
        for j in range(2, n_data + 1):
            variance[j][i] = float("inf")

    for length in range(2, n_data + 1):
        sum_values = 0.0
        sum_squares = 0.0
        weight = 0
        for offset in range(1, length + 1):
            lower_class_limit = length - offset + 1
            value = data[lower_class_limit - 1]
            weight += 1
            sum_values += value
            sum_squares += value * value
            current_variance = sum_squares - (sum_values * sum_values) / weight
            previous_index = lower_class_limit - 1
            if previous_index:
                for class_index in range(2, class_count + 1):
                    candidate = current_variance + variance[previous_index][class_index - 1]
                    if variance[length][class_index] >= candidate:
                        lower[length][class_index] = lower_class_limit
                        variance[length][class_index] = candidate
        lower[length][1] = 1
        variance[length][1] = current_variance

    breaks = [0.0] * (class_count + 1)
    breaks[class_count] = data[-1]
    count = class_count
    k = n_data
    while count > 1:
        idx = int(lower[k][count] - 2)
        breaks[count - 1] = data[idx]
        k = int(lower[k][count] - 1)
        count -= 1
    breaks[0] = data[0]
    return breaks


def generated_breaks(values: Any, class_config: dict[str, Any]) -> list[float]:
    method = class_config.get("method", "manual")
    class_count = int(class_config.get("class_count", 5))
    valid = [float(v) for v in values.dropna().tolist()]
    if not valid:
        raise ValueError("没有可参与分类的数值。")

    if method == "equal_interval":
        return np.linspace(min(valid), max(valid), class_count + 1).tolist()
    if method == "quantile":
        return np.quantile(valid, np.linspace(0, 1, class_count + 1)).tolist()
    if method == "natural_breaks":
        unique_count = len(set(valid))
        class_count = max(1, min(class_count, unique_count))
        try:
            import mapclassify

            classifier = mapclassify.FisherJenks(valid, k=class_count)
            bins = [float(value) for value in classifier.bins]
        except ImportError:
            bins = jenks_breaks(valid, class_count)[1:]

        lower_bound = min(valid)
        if bool(class_config.get("zero_as_no_data", False)) and min(valid) > 0:
            lower_bound = float(class_config.get("positive_floor", 0))
        return [lower_bound] + bins
    if method == "defined_interval":
        interval = float(class_config["interval"])
        start = float(class_config.get("start", min(valid)))
        end = float(class_config.get("end", max(valid)))
        breaks = list(np.arange(start, end + interval, interval))
        if breaks[-1] < max(valid):
            breaks.append(max(valid))
        return breaks

    raise ValueError(
        "classification.method 支持 manual、equal_interval、quantile、natural_breaks、defined_interval。"
    )


def clean_breaks(breaks: list[float]) -> list[float]:
    cleaned: list[float] = []
    for value in breaks:
        numeric = float(value)
        if not cleaned or numeric > cleaned[-1]:
            cleaned.append(numeric)
    if len(cleaned) < 2:
        raise ValueError("分类断点至少需要两个递增数值。")
    return cleaned


def format_number(value: float, precision: int) -> str:
    if precision == 0:
        return str(int(round(value)))
    return f"{value:.{precision}f}"


def make_break_labels(breaks: list[float], class_config: dict[str, Any]) -> list[str]:
    labels = class_config.get("labels")
    if labels:
        if len(labels) != len(breaks) - 1:
            raise ValueError("classification.labels 数量必须等于断点区间数量。")
        return [str(label) for label in labels]

    precision = int(class_config.get("precision", 0))
    unit = str(class_config.get("unit", ""))
    integer_ranges = bool(class_config.get("integer_ranges", False))
    generated_labels: list[str] = []
    for index in range(len(breaks) - 1):
        low = breaks[index]
        high = breaks[index + 1]
        if integer_ranges:
            display_low = int(math.floor(low)) + 1
            display_high = int(math.floor(high))
            if index == 0 and bool(class_config.get("zero_as_no_data", False)):
                display_low = max(1, display_low)
            if display_low == display_high:
                label = f"{display_high}{unit}"
            else:
                label = f"{display_low}-{display_high}{unit}"
        else:
            label = f"{format_number(low, precision)} - {format_number(high, precision)}{unit}"
        generated_labels.append(label)
    return generated_labels


def classify(provinces: Any, config: dict[str, Any]) -> tuple[Any, list[str], list[float]]:
    class_config = config.get("classification", {})
    method = class_config.get("method", "manual")
    values = provinces["value"].copy()

    if bool(class_config.get("zero_as_no_data", True)):
        values = values.where(values > 0)

    if method == "manual":
        breaks = clean_breaks(class_config.get("breaks", []))
    else:
        breaks = clean_breaks(generated_breaks(values, class_config))

    labels = make_break_labels(breaks, class_config)
    include_lowest = bool(class_config.get("include_lowest", False))
    categories = pd.cut(
        values,
        bins=breaks,
        labels=labels,
        include_lowest=include_lowest,
        right=bool(class_config.get("right_closed", True)),
    )

    result = provinces.copy()
    result["cat"] = categories
    result["value_for_classification"] = values
    return result, labels, breaks


def make_color_mapping(labels: list[str], config: dict[str, Any]) -> dict[str, Any]:
    style = config.get("style", {})
    explicit_colors = style.get("class_colors")
    if explicit_colors:
        if len(explicit_colors) != len(labels):
            raise ValueError("style.class_colors 数量必须与分类数量一致。")
        return dict(zip(labels, explicit_colors))

    cmap_name = style.get("colormap", "YlOrRd")
    cmap = plt.get_cmap(cmap_name, len(labels))
    colors = [mpl.colors.to_hex(cmap(i)) for i in range(len(labels))]
    if bool(style.get("reverse_colormap", False)):
        colors = list(reversed(colors))
    return dict(zip(labels, colors))


def configure_fonts(config: dict[str, Any]) -> None:
    font_config = config.get("fonts", {})
    families = font_config.get(
        "sans_serif",
        ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial Unicode MS", "DejaVu Sans"],
    )
    mpl.rcParams["font.sans-serif"] = families
    mpl.rcParams["axes.unicode_minus"] = False


def add_scale_bar(fig: Any, ax: Any, config: dict[str, Any]) -> None:
    bar_config = config.get("scale_bar", {})
    if not bool(bar_config.get("enabled", True)):
        return

    length_km = float(bar_config.get("length_km", 1000))
    segments = int(bar_config.get("segments", 2))
    unit_label = str(bar_config.get("unit_label", " km"))
    text_size = float(bar_config.get("font_size", 11))
    line_color = bar_config.get("color", "#222222")
    fill_color = bar_config.get("alternate_color", "#ffffff")
    style = bar_config.get("style", "alternating_bar")

    if bar_config.get("coordinate_system", "axes") == "figure":
        scale_ax = fig.add_axes(tuple(bar_config.get("box", [0.48, 0.055, 0.20, 0.07])))
        scale_ax.set_axis_off()
        scale_ax.set_xlim(0, length_km)
        scale_ax.set_ylim(0, 1)
        segment_length_km = length_km / segments

        if style == "line_ticks":
            y0 = float(bar_config.get("line_y", 0.42))
            major_ticks = bar_config.get("major_ticks") or [0, length_km / 2, length_km]
            minor_interval = float(bar_config.get("minor_interval_km", 0))
            label_position = bar_config.get("label_position", "above")
            major_tick_height = float(bar_config.get("major_tick_height", 0.18))
            minor_tick_height = float(bar_config.get("minor_tick_height", 0.10))
            linewidth = float(bar_config.get("linewidth", 0.8))

            scale_ax.plot([0, length_km], [y0, y0], color=line_color, linewidth=linewidth)
            if minor_interval > 0:
                tick = 0.0
                while tick <= length_km + 1e-9:
                    scale_ax.plot(
                        [tick, tick],
                        [y0, y0 + minor_tick_height],
                        color=line_color,
                        linewidth=linewidth,
                    )
                    tick += minor_interval

            for index, tick in enumerate(major_ticks):
                tick_value = float(tick)
                scale_ax.plot(
                    [tick_value, tick_value],
                    [y0, y0 + major_tick_height],
                    color=line_color,
                    linewidth=linewidth,
                )
                label = format_number(tick_value, 0)
                if index == len(major_ticks) - 1:
                    label = f"{label}{unit_label}"
                label_y = y0 + major_tick_height + 0.08 if label_position == "above" else y0 - 0.16
                va = "bottom" if label_position == "above" else "top"
                scale_ax.text(
                    tick_value,
                    label_y,
                    label,
                    ha="center",
                    va=va,
                    fontsize=text_size,
                    color=line_color,
                )
            return

        y0 = 0.58
        bar_height = 0.18
        for index in range(segments):
            rect = Rectangle(
                (index * segment_length_km, y0),
                segment_length_km,
                bar_height,
                facecolor=line_color if index % 2 == 0 else fill_color,
                edgecolor=line_color,
                linewidth=float(bar_config.get("linewidth", 0.8)),
            )
            scale_ax.add_patch(rect)

        scale_ax.text(0, 0.26, "0", ha="center", va="top", fontsize=text_size, color=line_color)
        for index in range(1, segments + 1):
            label_value = length_km * index / segments
            suffix = unit_label if index == segments else ""
            scale_ax.text(
                segment_length_km * index,
                0.26,
                f"{format_number(label_value, 0)}{suffix}",
                ha="center",
                va="top",
                fontsize=text_size,
                color=line_color,
            )
        return

    location = bar_config.get("location", [0.08, 0.08])

    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    width = xlim[1] - xlim[0]
    height = ylim[1] - ylim[0]
    x0 = xlim[0] + width * float(location[0])
    y0 = ylim[0] + height * float(location[1])
    total_length = length_km * 1000.0
    segment_length = total_length / segments
    bar_height = height * float(bar_config.get("height_ratio", 0.006))

    for index in range(segments):
        rect = Rectangle(
            (x0 + index * segment_length, y0),
            segment_length,
            bar_height,
            facecolor=line_color if index % 2 == 0 else fill_color,
            edgecolor=line_color,
            linewidth=float(bar_config.get("linewidth", 0.8)),
            zorder=8,
        )
        ax.add_patch(rect)

    label_y = y0 - bar_height * 2.2
    ax.text(x0, label_y, "0", ha="center", va="top", fontsize=text_size, color=line_color)
    for index in range(1, segments + 1):
        label_value = length_km * index / segments
        suffix = unit_label if index == segments else ""
        ax.text(
            x0 + segment_length * index,
            label_y,
            f"{format_number(label_value, 0)}{suffix}",
            ha="center",
            va="top",
            fontsize=text_size,
            color=line_color,
        )


def add_north_arrow(fig: Any, ax: Any, config: dict[str, Any]) -> None:
    arrow_config = config.get("north_arrow", {})
    if not bool(arrow_config.get("enabled", True)):
        return

    color = arrow_config.get("color", "#222222")
    text_size = float(arrow_config.get("font_size", 18))

    if arrow_config.get("coordinate_system", "axes") == "figure":
        arrow_ax = fig.add_axes(tuple(arrow_config.get("box", [0.76, 0.045, 0.07, 0.10])))
        arrow_ax.set_axis_off()
        arrow_ax.set_xlim(0, 1)
        arrow_ax.set_ylim(0, 1)
        if arrow_config.get("style", "arrow") == "compass":
            arrow = Polygon(
                [
                    (0.50, 0.82),
                    (0.25, 0.18),
                    (0.50, 0.34),
                    (0.75, 0.18),
                ],
                closed=True,
                facecolor=color,
                edgecolor=color,
                linewidth=0,
            )
            arrow_ax.add_patch(arrow)
        else:
            arrow_ax.annotate(
                "",
                xy=(0.5, 0.90),
                xytext=(0.5, 0.12),
                xycoords="axes fraction",
                arrowprops=dict(
                    facecolor=color,
                    edgecolor=color,
                    width=float(arrow_config.get("shaft_width", 3)),
                    headwidth=float(arrow_config.get("head_width", 13)),
                    headlength=float(arrow_config.get("head_length", 15)),
                ),
            )
        if bool(arrow_config.get("show_label", True)):
            arrow_ax.text(
                0.5,
                float(arrow_config.get("label_y", 0.88)),
                str(arrow_config.get("label", "N")),
                transform=arrow_ax.transAxes,
                ha="center",
                va="bottom",
                fontsize=text_size,
                color=color,
                fontweight="bold",
            )
        return

    location = arrow_config.get("location", [0.91, 0.86])
    size = float(arrow_config.get("size", 0.10))
    x = float(location[0])
    y = float(location[1])

    ax.annotate(
        "",
        xy=(x, y + size),
        xytext=(x, y),
        xycoords="axes fraction",
        arrowprops=dict(
            facecolor=color,
            edgecolor=color,
            width=float(arrow_config.get("shaft_width", 4)),
            headwidth=float(arrow_config.get("head_width", 16)),
            headlength=float(arrow_config.get("head_length", 18)),
        ),
        zorder=9,
    )
    if bool(arrow_config.get("show_label", True)):
        ax.text(
            x,
            y + size + 0.02,
            str(arrow_config.get("label", "N")),
            transform=ax.transAxes,
            ha="center",
            va="bottom",
            fontsize=text_size,
            color=color,
            fontweight="bold",
            zorder=9,
        )


def add_legend(
    fig: Any,
    ax: Any,
    labels: list[str],
    color_mapping: dict[str, Any],
    provinces: Any,
    config: dict[str, Any],
) -> None:
    legend_config = config.get("legend", {})
    if not bool(legend_config.get("enabled", True)):
        return

    show_empty = bool(legend_config.get("show_empty_classes", True))
    used_labels = set(provinces["cat"].dropna().astype(str))
    legend_labels = labels if show_empty else [label for label in labels if label in used_labels]
    handles = [
        Patch(
            facecolor=color_mapping[label],
            edgecolor=legend_config.get("edgecolor", "#888888"),
            label=label,
        )
        for label in legend_labels
    ]

    if bool(legend_config.get("show_no_data", True)):
        handles.append(
            Patch(
                facecolor=config.get("style", {}).get("no_data_color", "#eeeeee"),
                edgecolor=legend_config.get("edgecolor", "#888888"),
                label=legend_config.get("no_data_label", "无数据 / 0"),
            )
        )

    legend_kwargs = dict(
        handles=handles,
        title=legend_config.get("title", "数值分级"),
        loc=legend_config.get("loc", "lower left"),
        bbox_to_anchor=tuple(legend_config.get("bbox_to_anchor", [0.02, 0.18])),
        frameon=bool(legend_config.get("frameon", True)),
        framealpha=float(legend_config.get("framealpha", 0.92)),
        borderpad=float(legend_config.get("borderpad", 0.8)),
        labelspacing=float(legend_config.get("labelspacing", 0.6)),
        handlelength=float(legend_config.get("handlelength", 1.8)),
        handleheight=float(legend_config.get("handleheight", 1.0)),
        fontsize=float(legend_config.get("font_size", 11)),
        title_fontsize=float(legend_config.get("title_font_size", 13)),
        ncol=int(legend_config.get("ncol", 1)),
        columnspacing=float(legend_config.get("columnspacing", 1.2)),
    )
    if legend_config.get("coordinate_system", "axes") == "figure":
        legend = fig.legend(**legend_kwargs)
    else:
        legend = ax.legend(**legend_kwargs)
    legend.get_frame().set_edgecolor(legend_config.get("frame_edgecolor", "#cccccc"))


def add_province_labels(ax: Any, provinces: Any, config: dict[str, Any]) -> None:
    label_config = config.get("province_labels", {})
    if not bool(label_config.get("enabled", False)):
        return

    name_field = config.get("geojson", {}).get("name_field", "name")
    font_size = float(label_config.get("font_size", 7))
    color = label_config.get("color", "#333333")
    only_with_data = bool(label_config.get("only_with_data", True))

    for _, row in provinces.iterrows():
        if only_with_data and pd.isna(row["value"]):
            continue
        point = row.geometry.representative_point()
        ax.text(
            point.x,
            point.y,
            normalize_region_name(str(row[name_field])),
            ha="center",
            va="center",
            fontsize=font_size,
            color=color,
            zorder=7,
        )


def render_map(config: dict[str, Any], config_dir: Path, dry_run: bool = False) -> dict[str, Any]:
    configure_fonts(config)

    provinces, nine_dash = load_geometries(config, config_dir)
    values, value_warnings = read_values(config, config_dir)
    provinces, unmatched_input = attach_values(provinces, values, config)
    provinces, labels, breaks = classify(provinces, config)
    color_mapping = make_color_mapping(labels, config)

    no_data_color = config.get("style", {}).get("no_data_color", "#eeeeee")
    provinces["plot_color"] = provinces["cat"].astype(str).map(color_mapping)
    provinces.loc[provinces["cat"].isna(), "plot_color"] = no_data_color

    summary = {
        "province_count": int(len(provinces)),
        "nine_dash_count": int(len(nine_dash)),
        "matched_value_count": int(provinces["value"].notna().sum()),
        "unmatched_input": unmatched_input,
        "warnings": value_warnings,
        "labels": labels,
        "breaks": breaks,
    }
    if dry_run:
        return summary

    map_config = config.get("map", {})
    projection_epsg = int(map_config.get("projection_epsg", 3857))
    provinces_proj = provinces.to_crs(epsg=projection_epsg)
    nine_proj = nine_dash.to_crs(epsg=projection_epsg) if not nine_dash.empty else nine_dash

    fig, ax = plt.subplots(
        figsize=tuple(map_config.get("figsize", [11, 8])),
        dpi=int(map_config.get("dpi", 300)),
    )
    if map_config.get("axes_position"):
        ax.set_position(tuple(map_config["axes_position"]))
    fig.patch.set_facecolor(map_config.get("figure_facecolor", "white"))
    ax.set_facecolor(map_config.get("axes_facecolor", "white"))

    provinces_proj.plot(
        ax=ax,
        color=provinces_proj["plot_color"],
        edgecolor=config.get("style", {}).get("province_edgecolor", "#c7c7c7"),
        linewidth=float(config.get("style", {}).get("province_linewidth", 0.6)),
        zorder=2,
    )

    if not nine_proj.empty:
        nine_dash_style = config.get("nine_dash_line", {})
        nine_proj.plot(
            ax=ax,
            facecolor=nine_dash_style.get("facecolor", "#666666"),
            edgecolor=nine_dash_style.get("edgecolor", "#666666"),
            linewidth=float(nine_dash_style.get("linewidth", 0.5)),
            alpha=float(nine_dash_style.get("alpha", 1.0)),
            zorder=4,
        )

    title = map_config.get("title")
    if title:
        ax.set_title(
            title,
            fontsize=float(map_config.get("title_font_size", 18)),
            pad=float(map_config.get("title_pad", 16)),
            fontweight=map_config.get("title_fontweight", "bold"),
        )

    ax.set_axis_off()
    ax.set_aspect("equal")

    padding_ratio = float(map_config.get("padding_ratio", 0.03))
    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    ax.set_xlim(xlim[0] - (xlim[1] - xlim[0]) * padding_ratio, xlim[1] + (xlim[1] - xlim[0]) * padding_ratio)
    ax.set_ylim(ylim[0] - (ylim[1] - ylim[0]) * padding_ratio, ylim[1] + (ylim[1] - ylim[0]) * padding_ratio)

    add_legend(fig, ax, labels, color_mapping, provinces_proj, config)
    add_scale_bar(fig, ax, config)
    add_north_arrow(fig, ax, config)
    add_province_labels(ax, provinces_proj, config)

    note = map_config.get("note")
    if note:
        fig.text(
            float(map_config.get("note_x", 0.5)),
            float(map_config.get("note_y", 0.025)),
            note,
            ha="center",
            va="center",
            fontsize=float(map_config.get("note_font_size", 9)),
            color=map_config.get("note_color", "#555555"),
        )

    outputs = map_config.get("outputs", ["output/china_province_choropleth.png"])
    written: list[str] = []
    for output in outputs:
        output_path = resolve_path(output, config_dir)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        bbox_inches = map_config.get("bbox_inches", "tight")
        fig.savefig(
            output_path,
            dpi=int(map_config.get("dpi", 300)),
            bbox_inches=bbox_inches,
            pad_inches=float(map_config.get("pad_inches", 0.12)),
        )
        written.append(str(output_path))

    plt.close(fig)
    summary["outputs"] = written
    return summary


def print_summary(summary: dict[str, Any]) -> None:
    print("生成摘要")
    print(f"- 省级面数量：{summary['province_count']}")
    print(f"- 九段线要素数量：{summary['nine_dash_count']}")
    print(f"- 匹配到数值的省份数量：{summary['matched_value_count']}")
    print(f"- 分级标签：{', '.join(summary['labels'])}")
    if summary.get("unmatched_input"):
        print(f"- 未匹配输入名称：{', '.join(summary['unmatched_input'])}")
    for warning in summary.get("warnings", []):
        print(f"- 警告：{warning}")
    for output in summary.get("outputs", []):
        print(f"- 输出：{output}")


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    summary = render_map(config, config_path.parent, dry_run=args.dry_run)
    print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
