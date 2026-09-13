# -*- coding: utf-8 -*-
"""
02_georef.py — 给裁切成果赋坐标, 生成 GeoTIFF + 金字塔

依据 config 中的 grid 规则, 从文件名解析出列号 C / 行号 R, 换算成经纬度矩形,
再把 ./work/01_crop 里的 <name>_inner.png 写成带坐标的 GeoTIFF。

只依赖 rasterio(自带 GDAL), 不需要单独安装 GDAL。

用法
  python scripts/02_georef.py
  python scripts/02_georef.py -c my.yaml --dry-run   # 只打印换算结果, 不写文件
"""
import argparse
import csv
import math
import os
import re
import sys
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

try:
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_bounds
except ImportError:
    sys.exit("缺少 rasterio。安装: pip install rasterio")


# --------------------------------------------------------------------------- #
#  图号 → 经纬度
# --------------------------------------------------------------------------- #
def build_geobox(c, r, g):
    """按配置的规则把 (C, R) 换算为 (west, south, east, north)。"""
    rule = g.get("rule", "CCRR")
    if rule != "CCRR":
        raise SystemExit("暂不支持的 grid.rule: %s (当前内置 CCRR)" % rule)
    p = g["ccrr"]
    west = p["origin_lon"] - p["step_lon"] * c
    south = p["origin_lat"] - p["step_lat"] * r
    return west, south, west + p["step_lon"], south + p["step_lat"]


def apply_shift(west, south, east, north, shift_m, mpd):
    """整体东移。注意偏移量依赖中心纬度, 纬度一变就得重算,
    否则同一幅图在矢量与栅格之间会悄悄错开(实测可达 10 米量级)。"""
    if not shift_m:
        return west, south, east, north
    latc = (south + north) / 2.0
    dlon = shift_m / (mpd * math.cos(math.radians(latc)))
    return west + dlon, south, east + dlon, north


# --------------------------------------------------------------------------- #
def parse_name(stem, rx, overrides):
    """从文件名取 (sheet_no, C, R, name)。overrides 可逐幅强制指定位置。"""
    m = re.match(rx, stem + ".png") or re.match(rx, stem)
    if not m:
        return None
    try:
        c, r, name = int(m.group("c")), int(m.group("r")), m.group("name")
    except (IndexError, ValueError):
        return None
    if stem in overrides:
        c, r = overrides[stem]
    return "%02d%02d" % (c, r), c, r, name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("--dry-run", action="store_true", help="只打印换算, 不写文件")
    ap.add_argument("only", nargs="*",
                    help="只配准这些图幅(文件名不含 _inner.png), 便于单幅返工")
    a = ap.parse_args()

    cfgp = Path(a.config)
    if not cfgp.exists():
        sys.exit("找不到 %s, 请先复制 config.example.yaml" % cfgp)
    cfg = yaml.safe_load(open(cfgp, encoding="utf-8"))
    base = cfgp.parent
    crop_dir = (base / cfg["paths"]["crop"]).resolve()
    geo_dir = (base / cfg["paths"]["geo"]).resolve()
    input_dir = (base / cfg["paths"]["input"]).resolve()

    # 清单的 file 列记录的是"原始扫描件的文件名"。
    # 但这里只看得到裁切产物 *_inner.png, 原始扩展名已经丢了,
    # 所以去 input 目录反查一次; 查不到就退回裁切产物名, 不再硬编码 .jpg。
    RAW_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")

    def raw_filename(stem):
        for ext in RAW_EXT:
            if os.path.exists(os.path.join(input_dir, stem + ext)):
                return stem + ext
        for ext in RAW_EXT:
            if os.path.exists(os.path.join(input_dir, stem + ext.upper())):
                return stem + ext.upper()
        return stem + "_inner.png"

    g, gr = cfg["grid"], cfg["georef"]
    rx = g["filename_regex"]
    overrides = {k: tuple(v) for k, v in (g.get("overrides") or {}).items()}
    shift = float(gr.get("east_shift_m", 0.0))
    mpd = float(gr.get("metres_per_degree", 111320.0))
    nodata = gr.get("nodata", 255)

    srcs = sorted(p for p in Path(crop_dir).glob("*_inner.png"))
    if not srcs:
        sys.exit("裁切目录没有 *_inner.png: %s" % crop_dir)

    # 只配准指定图幅: 单幅返工时不必把几百幅全部重写一遍。
    #   python scripts/02_georef.py 1117-分水嘴
    if a.only:
        want = set(a.only)
        srcs = [p for p in srcs
                if (p.stem[:-len("_inner")] if p.stem.endswith("_inner") else p.stem) in want]
        if not srcs:
            sys.exit("指定的图幅在裁切目录里找不到: %s" % ", ".join(sorted(want)))
        print("只处理指定图幅: %s" % ", ".join(sorted(want)))

    os.makedirs(geo_dir, exist_ok=True)

    rows, skipped = [], []
    for p in srcs:
        stem = p.stem[:-len("_inner")] if p.stem.endswith("_inner") else p.stem
        info = parse_name(stem, rx, overrides)
        if info is None:
            skipped.append(p.name)
            continue
        sheet_no, c, r, name = info
        w, s, e, n = build_geobox(c, r, g)
        w, s, e, n = apply_shift(w, s, e, n, shift, mpd)
        rows.append(dict(sheet_no=sheet_no, C=c, R=r, name=name,
                         lon_min=w, lat_min=s, lon_max=e, lat_max=n,
                         file=raw_filename(stem), src=str(p)))

    if skipped:
        print("[!] 文件名不符合规则, 已跳过 %d 个:" % len(skipped))
        for s in skipped[:10]:
            print("   ", s)
        if len(skipped) > 10:
            print("   ... 其余 %d 个未显示" % (len(skipped) - 10))
        print("[!] 配准未完成：请修正文件名或 grid.filename_regex 后重试")
        return 1

    if not rows:
        sys.exit("没有可配准的图幅：所有文件都不符合 grid.filename_regex")

    print("待配准 %d 幅   经度 %.4f~%.4f  纬度 %.4f~%.4f"
          % (len(rows),
             min(x["lon_min"] for x in rows), max(x["lon_max"] for x in rows),
             min(x["lat_min"] for x in rows), max(x["lat_max"] for x in rows)))
    if shift:
        print("已启用整体东移 %.0f 米" % shift)

    if a.dry_run:
        for x in rows[:10]:
            print("  %s %-10s C=%2d R=%2d  W=%.6f S=%.6f"
                  % (x["sheet_no"], x["name"], x["C"], x["R"], x["lon_min"], x["lat_min"]))
        print("  ... (--dry-run, 未写文件)")
        return 0

    # 同图号重复检查 —— 必须在这里拦住。
    # 清单按 sheet_no 索引(下面 merged[...]), 两个文件解析出同一个图号时
    # 后一个会**静默覆盖**前一个: 清单少一条、VRT 里两幅的 DstRect 完全重叠
    # 也只会显示其中一个, 而全程不报任何错。
    # 实测就是这么丢掉过一幅图 —— 文件名 `2108-甲幅` 与 `2108-彩色测试`
    # 同号, 结果彩色那幅凭空消失, 自查工具也查不出来(它比的是清单,
    # 而清单里已经只剩一条了)。
    dups = {}
    for x in rows:
        dups.setdefault(x["sheet_no"], []).append(x["file"])
    dups = {k: v for k, v in dups.items() if len(v) > 1}
    if dups:
        print("[!] 有 %d 个图号对应多个文件 —— 清单只会保留最后一个，其余会被丢掉:" % len(dups))
        for k in sorted(dups):
            print("    %s : %s" % (k, " , ".join(dups[k])))
        print("    它们在图幅网格上占同一格, 生成的 VRT 里也会互相覆盖。")
        print("    请改掉重复的文件名（或把不需要的移出 input/）后重跑。")
        return 1

    # 清单同样用合并写入 —— 只配准单幅时不能把其余几百条记录冲掉。
    man = os.path.join(geo_dir, "sheet_manifest.csv")
    merged = {}
    if os.path.exists(man):
        try:
            for r in csv.DictReader(open(man, encoding="utf-8-sig")):
                if r.get("sheet_no"):
                    merged[r["sheet_no"]] = r
        except Exception:
            pass
    for x in rows:
        merged[x["sheet_no"]] = {k: x[k] for k in
                                 ["sheet_no", "C", "R", "name", "lon_min",
                                  "lat_min", "lon_max", "lat_max", "file"]}
    with open(man, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=["sheet_no", "C", "R", "name", "lon_min",
                                           "lat_min", "lon_max", "lat_max", "file"])
        wr.writeheader()
        for k in sorted(merged):
            wr.writerow(merged[k])
    print("清单: %s  (累计 %d 条)" % (man, len(merged)))

    prof_common = dict(driver="GTiff", dtype="uint8", crs="EPSG:4326",
                       compress=gr.get("compress", "DEFLATE"), tiled=True,
                       blockxsize=512, blockysize=512, nodata=nodata,
                       BIGTIFF="IF_SAFER")
    ovr = gr.get("overviews", [2, 4, 8, 16, 32])

    written = 0
    n_gray = n_color = 0
    for x in rows:
        # 裁切产物可能是单波段灰度 PNG, 也可能是三波段彩色 PNG
        # （01_crop.py 的 crop.color 决定）。这里按实际波段写 GeoTIFF,
        # 不能一律转灰度 —— 否则交通图、水系图的颜色会被压掉。
        im = Image.open(x["src"])
        if im.mode in ("L", "1", "I;16"):
            arr = np.array(im.convert("L"))
            bands = 1
            n_gray += 1
        else:
            arr = np.array(im.convert("RGB"))
            bands = 3
            n_color += 1
        h, w = arr.shape[:2]
        dst = os.path.join(geo_dir, os.path.splitext(x["file"])[0] + "_geo.tif")
        prof = dict(prof_common, count=bands, height=h, width=w,
                    transform=from_bounds(x["lon_min"], x["lat_min"],
                                          x["lon_max"], x["lat_max"], w, h))
        with rasterio.open(dst, "w", **prof) as d:
            if bands == 1:
                d.write(arr, 1)
            else:
                d.write(np.moveaxis(arr, 2, 0))     # rasterio 要 band-first
            if ovr:
                d.build_overviews(ovr, Resampling.average)
                d.update_tags(ns="rio_overview", resampling="average")
        written += 1
        if written % 25 == 0 or written == len(rows):
            print("  已配准 %d/%d" % (written, len(rows)))

    print("配准完成 %d 幅 -> %s" % (written, geo_dir))
    if n_color:
        print("  其中 灰度 %d 幅 / 彩色 %d 幅（彩色写成三波段 GeoTIFF）" % (n_gray, n_color))
    return 0


if __name__ == "__main__":
    sys.exit(main())
