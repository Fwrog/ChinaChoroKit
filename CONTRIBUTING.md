# Contributing

Thanks for helping improve ChinaChoroKit.

## Development Setup

Recommended:

```bash
uv sync
uv run china-choro --config config/example_china_map.yaml
```

Fallback:

```bash
pip install -r requirements.txt
python src/medmap_china/render.py --config config/example_china_map.yaml
```

## Pull Request Checklist

- Keep rendering behavior configuration-driven when possible.
- Do not hard-code local absolute paths.
- Re-render `output/china_province_choropleth.png` and `output/china_province_choropleth.svg` if map styling changes.
- Update `assets/china_province_choropleth.png` if the README preview should change.
- Document new classification or layout options in `README.md`.

## Data and Licensing

Do not add boundary files or datasets unless their source and redistribution terms are clear.
