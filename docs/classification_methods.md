# Classification Methods

本项目的分级设色逻辑参考 ArcGIS Pro 中常见的 graduated colors 工作流：先明确无数据或 0 值如何表达，再决定正值数据如何分级。

## 当前推荐方案

当前示例使用：

```yaml
classification:
  method: "natural_breaks"
  class_count: 5
  include_lowest: true
  zero_as_no_data: true
  positive_floor: 0
  integer_ranges: true
```

含义是：

1. `0` 或没有输入值的省份不参与自然断点计算，统一显示为灰色，图例标为 `0`。
2. 剩余正值使用 Fisher-Jenks Natural Breaks 分成 5 类。
3. 最终图例是 6 类：`0` 类 + 5 个正值分级。

当前样例数据的正值自然断点结果是 `1-10`、`11-38`、`39-76`、`77-92`、`93-3821`，再加上单独的 `0` 类。这个结果是由 CSV 数据自动计算得到的，不是硬编码断点。

这和 ArcGIS 中常见的处理方式一致：如果 0 表示“无病例、无记录或未观测”，通常应作为背景类或单独符号类；如果 0 是真实测量值，才应该进入连续分级。

## 方法对比

| 方法 | ArcGIS 对应思路 | 优点 | 风险 |
|---|---|---|---|
| `manual` | Manual Interval | 断点可解释、适合课程或报告固定口径 | 断点依赖人工判断，换数据后可能不适配 |
| `equal_interval` | Equal Interval | 简单直观，每组宽度一致 | 极端值会压缩低值差异 |
| `quantile` | Quantile | 每组要素数量接近，地图颜色更均衡 | 相近数值可能被硬切到不同组 |
| `natural_breaks` | Natural Breaks (Jenks) | 尽量降低组内差异、突出自然聚类 | 小样本和极端值会显著影响断点 |
| `defined_interval` | Defined Interval | 每隔固定数值分一组，口径稳定 | 分组数量随数据范围变化 |

## 对当前数据的判断

当前数据中四川为 `3821`，明显高于其他省份；其余正值集中在 `10-92`。如果使用等距分级，大部分省份会落入最低一两档，地图层次不足。自然断点法更适合这种“一个高值 + 多个低中值”的分布。

需要注意：样例正值只有 9 条，分成 5 组时每组包含的省份可能较少。课程作业中这是可以解释的，但正式研究建议同时报告原始数据表或分级断点，避免读者误以为每个颜色等级代表相同数量或相同宽度。

实现上优先使用 `mapclassify.FisherJenks`。如果某台机器没有安装 `mapclassify`，脚本会降级到内置 Jenks 实现，但建议按 `requirements.txt` 或 `environment.yml` 安装完整依赖，以获得更稳定的自然断点结果。
