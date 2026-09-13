# -*- coding: utf-8 -*-
"""
03_build_vrt.py — 生成总镶嵌 VRT (虚拟镶嵌, 不产生新数据, 秒级完成)

VRT 本身只是 XML 索引: 一份文件指向全部 GeoTIFF 并给出各自在图幅网格中的
位置。在 QGIS / ArcGIS 里打开它即可看到整片拼接结果, 磁盘占用几乎为零。

本脚本手写 VRT XML(符合 GDAL VRT 规范), 因此不依赖 GDAL python 绑定;
若检测到已安装 osgeo, 则改用官方 gdal.BuildVRT 以求最稳妥。

用法
  python scripts/03_build_vrt.py
  python scripts/03_build_vrt.py -c my.yaml
"""
import argparse
import csv
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

try:
    from osgeo import gdal          # 可选: 装了就用官方实现
    HAS_GDAL = True
except ImportError:
    HAS_GDAL = False


def read_geotiff_bounds(path):
    """取 GeoTIFF 的 (west, south, east, north, width, height)。优先 rasterio。"""
    try:
        import rasterio
        with rasterio.open(path) as d:
            b = d.bounds
            return b.left, b.bottom, b.right, b.top, d.width, d.height
    except Exception:
        pass
    from osgeo import gdal
    d = gdal.Open(path)
    gt = d.GetGeoTransform()
    w, h = d.RasterXSize, d.RasterYSize
    return (gt[0], gt[3] + gt[5] * h,
            gt[0] + gt[1] * w, gt[3], w, h)


def read_geotiff_info(path):
    """取 GeoTIFF 的 (west, south, east, north, width, height, bands)。"""
    try:
        import rasterio
        with rasterio.open(path) as d:
            b = d.bounds
            return b.left, b.bottom, b.right, b.top, d.width, d.height, d.count
    except Exception:
        pass
    from osgeo import gdal
    d = gdal.Open(path)
    gt = d.GetGeoTransform()
    w, h = d.RasterXSize, d.RasterYSize
    return (gt[0], gt[3] + gt[5] * h,
            gt[0] + gt[1] * w, gt[3], w, h, d.RasterCount)


def write_vrt_xml(vrt_path, items, srs="EPSG:4326", nodata=255):
    """手写 VRT。items: [(tif_path, (w,s,e,n,W,H,bands)), ...]

    ⚠ 必须按源图的波段数生成 —— 早期版本固定只写 1 个 VRTRasterBand,
      结果混进彩色图时**颜色会被静默丢掉**（只取第 1 波段, 不报错）。
      规则:
        - 全灰 -> 单波段 VRT
        - 有彩色 -> 三波段 VRT; 灰度源在 R/G/B 三处都引用它自己的第 1 波段,
          相当于灰度转 RGB, 不会被丢掉
    """
    west = min(i[1][0] for i in items)
    east = max(i[1][2] for i in items)
    south = min(i[1][1] for i in items)
    north = max(i[1][3] for i in items)
    px = (items[0][1][2] - items[0][1][0]) / items[0][1][4]
    py = (items[0][1][3] - items[0][1][1]) / items[0][1][5]

    W = int(round((east - west) / px))
    H = int(round((north - south) / py))
    vdir = os.path.dirname(os.path.abspath(vrt_path))
    n_bands = 3 if any(i[1][6] > 1 for i in items) else 1

    root = ET.Element("VRTDataset", rasterXSize=str(W), rasterYSize=str(H))
    ET.SubElement(root, "SRS").text = str(srs)
    ET.SubElement(root, "GeoTransform").text = (
        "%.10f, %.10f, 0, %.10f, 0, %.10f" % (west, px, north, -py)
    )

    bands = []
    for bi in range(1, n_bands + 1):
        band = ET.SubElement(root, "VRTRasterBand", dataType="Byte", band=str(bi))
        ET.SubElement(band, "NoDataValue").text = str(nodata)
        ET.SubElement(band, "ColorInterp").text = (
            "Gray" if n_bands == 1 else ("Red", "Green", "Blue")[bi - 1])
        bands.append(band)

    for p, info in items:
        w, s, e, n, sw, sh, sb = info
        rel = os.path.relpath(os.path.abspath(p), vdir).replace("\\", "/")
        xo = int(round((w - west) / px))
        yo = int(round((north - n) / py))
        for bi, band in enumerate(bands, 1):
            # 灰度源(sb==1)在彩色 VRT 的每个波段都取自己的第 1 波段;
            # 彩色源按波段一一对应。
            src_band = 1 if sb == 1 else min(bi, sb)
            src = ET.SubElement(band, "SimpleSource")
            ET.SubElement(src, "SourceFilename", relativeToVRT="1").text = rel
            ET.SubElement(src, "SourceBand").text = str(src_band)
            ET.SubElement(src, "SourceProperties", RasterXSize=str(sw),
                          RasterYSize=str(sh), DataType="Byte")
            ET.SubElement(src, "SrcRect", xOff="0", yOff="0",
                          xSize=str(sw), ySize=str(sh))
            ET.SubElement(src, "DstRect", xOff=str(xo), yOff=str(yo),
                          xSize=str(sw), ySize=str(sh))

    ET.indent(root, space="  ")
    ET.ElementTree(root).write(vrt_path, encoding="utf-8", xml_declaration=True)
    return W, H, n_bands


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="config.yaml")
    a = ap.parse_args()

    cfgp = Path(a.config)
    if not cfgp.exists():
        sys.exit("找不到 %s, 请先复制 config.example.yaml" % cfgp)
    cfg = yaml.safe_load(open(cfgp, encoding="utf-8"))
    geo = (cfgp.parent / cfg["paths"]["geo"]).resolve()
    vname = cfg["georef"].get("vrt_name", "mosaic.vrt")
    nodata = cfg["georef"].get("nodata", 255)
    srs = "EPSG:%s" % cfg["georef"].get("epsg", 4326)

    tifs = sorted(str(p) for p in Path(geo).glob("*_geo.tif"))
    if not tifs:
        sys.exit("配准目录里没有 *_geo.tif: %s" % geo)

    vrt = os.path.join(geo, vname)
    if HAS_GDAL:
        print("检测到 osgeo, 使用官方 gdal.BuildVRT")
        gdal.BuildVRT(vrt, tifs, options=gdal.BuildVRTOptions(VRTNodata=nodata))
        d = gdal.Open(vrt)
        W, H, nb = d.RasterXSize, d.RasterYSize, d.RasterCount
        d = None
    else:
        items = [(t, read_geotiff_info(t)) for t in tifs]
        W, H, nb = write_vrt_xml(vrt, items, srs, nodata)

    print("VRT 完成: %s" % vrt)
    print("  源图幅 %d   总尺寸 %d x %d   波段 %d" % (len(tifs), W, H, nb))
    if nb > 1:
        print("  （检测到彩色源，已生成三波段 VRT；灰度源在三个波段复用自身，不会丢）")
    print("  可在 QGIS / ArcGIS 中直接打开该 VRT 查看拼接结果")
    return 0


if __name__ == "__main__":
    sys.exit(main())
