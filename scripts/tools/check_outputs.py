# -*- coding: utf-8 -*-
"""
check_outputs.py — 成果自查

逐项核对: 清单 / 裁切成果 / 配准成果 三者的图号集合是否一致, 图幅有无重叠,
以及 GeoTIFF 的坐标范围是否与清单吻合。

[!] 图号必须用"文件名前缀"解析后再比对。
  清单里的 sheet_no 是 4 位数字(如 0119), 而成果文件名是 "0119-图名_geo.tif",
  直接拿两者做集合减法会把全部图幅都报成"缺失" —— 这是很容易犯的比对键错误。

用法
  python scripts/tools/check_outputs.py
  python scripts/tools/check_outputs.py -c my.yaml
"""
import argparse
import csv
import os
import sys
from pathlib import Path

import yaml


def sheet_no_of(name):
    """从文件名取图号: '0119-图名_geo.tif' -> '0119'; 取不到则返回原 stem。"""
    b = name
    for suf in ("_geo.tif", "_inner.png", ".tif", ".png", ".jpg", ".jpeg"):
        if b.lower().endswith(suf):
            b = b[: -len(suf)]
            break
    head = b.split("-")[0]
    return head if head.isdigit() else b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="config.yaml")
    a = ap.parse_args()
    cfgp = Path(a.config)
    if not cfgp.exists():
        sys.exit("找不到 %s" % cfgp)
    cfg = yaml.safe_load(open(cfgp, encoding="utf-8"))
    base = cfgp.parent
    crop = (base / cfg["paths"]["crop"]).resolve()
    geo = (base / cfg["paths"]["geo"]).resolve()

    man_p = geo / "sheet_manifest.csv"
    if not man_p.exists():
        sys.exit("找不到清单 %s, 请先跑 02_georef.py" % man_p)
    rows = list(csv.DictReader(open(man_p, encoding="utf-8-sig")))
    man = {r["sheet_no"]: r for r in rows}

    crops = {sheet_no_of(f) for f in os.listdir(crop) if f.endswith("_inner.png")}
    geos = {sheet_no_of(f) for f in os.listdir(geo) if f.endswith("_geo.tif")}

    print("清单 %d  |  裁切 %d  |  配准 %d" % (len(man), len(crops), len(geos)))
    bad = 0
    for tag, s in (("裁切", crops), ("配准", geos)):
        miss, extra = sorted(set(man) - s), sorted(s - set(man))
        print("  %s  清单有它没有: %s" % (tag, miss or "无"))
        print("  %s  它有清单没有: %s" % (tag, extra or "无"))
        bad += len(miss) + len(extra)

    # 同一格重复登记
    key = [(r["C"], r["R"]) for r in rows]
    dup = sorted({k for k in key if key.count(k) > 1})
    print("  同一格重复登记: %s" % (dup or "无"))
    bad += len(dup)

    # 坐标范围与清单是否吻合 + 图幅是否互相重叠
    try:
        import rasterio
        from shapely.geometry import box
        boxes, mismatch = [], 0
        for r in rows:
            p = geo / (os.path.splitext(r["file"])[0] + "_geo.tif")
            if not p.exists():
                continue
            with rasterio.open(p) as d:
                b = d.bounds
            ew, es = float(r["lon_min"]), float(r["lat_min"])
            ee, en = float(r["lon_max"]), float(r["lat_max"])
            if max(abs(b.left - ew), abs(b.right - ee),
                   abs(b.bottom - es), abs(b.top - en)) > 1e-6:
                mismatch += 1
            boxes.append((r["sheet_no"], box(b.left, b.bottom, b.right, b.top)))
        print("  坐标与清单不符: %d 幅" % mismatch)
        bad += mismatch
        ov = 0
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if boxes[i][1].intersects(boxes[j][1]) and \
                        boxes[i][1].intersection(boxes[j][1]).area > 1e-9:
                    ov += 1
                    if ov <= 5:
                        print("     重叠: %s × %s" % (boxes[i][0], boxes[j][0]))
        print("  图幅互相重叠: %d 对" % ov)
        bad += ov
    except ImportError:
        print("  (未安装 rasterio/shapely, 跳过坐标与重叠检查)")

    print("\n%s" % ("全部检查通过" if bad == 0 else "发现 %d 处问题, 见上" % bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
