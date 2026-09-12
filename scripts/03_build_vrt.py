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


def write_vrt_xml(vrt_path, items, srs="EPSG:4326", nodata=255):
    """手写 VRT。items: [(tif_path, (w,s,e,n,W,H)), ...]"""
    west = min(i[1][0] for i in items)
    east = max(i[1][2] for i in items)
    south = min(i[1][1] for i in items)
    north = max(i[1][3] for i in items)
    px = (items[0][1][2] - items[0][1][0]) / items[0][1][4]
    py = (items[0][1][3] - items[0][1][1]) / items[0][1][5]

    W = int(round((east - west) / px))
    H = int(round((north - south) / py))
    vdir = os.path.dirname(os.path.abspath(vrt_path))

    L = ['<VRTDataset rasterXSize="%d" rasterYSize="%d">' % (W, H),
         '  <SRS>%s</SRS>' % srs,
         '  <GeoTransform>%.10f, %.10f, 0, %.10f, 0, %.10f</GeoTransform>'
         % (west, px, north, -py),
         '  <VRTRasterBand dataType="Byte" band="1">',
         '    <NoDataValue>%s</NoDataValue>' % nodata,
         '    <ColorInterp>Gray</ColorInterp>']
    for p, (w, s, e, n, sw, sh) in items:
        rel = os.path.relpath(os.path.abspath(p), vdir).replace("\\", "/")
        xo = int(round((w - west) / px))
        yo = int(round((north - n) / py))
        L += ['    <SimpleSource>',
              '      <SourceFilename relativeToVRT="1">%s</SourceFilename>' % rel,
              '      <SourceBand>1</SourceBand>',
              '      <SourceProperties RasterXSize="%d" RasterYSize="%d" DataType="Byte"/>'
              % (sw, sh),
              '      <SrcRect xOff="0" yOff="0" xSize="%d" ySize="%d"/>' % (sw, sh),
              '      <DstRect xOff="%d" yOff="%d" xSize="%d" ySize="%d"/>'
              % (xo, yo, sw, sh),
              '    </SimpleSource>']
    L += ['  </VRTRasterBand>', '</VRTDataset>', '']

    with open(vrt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return W, H


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
        W, H = d.RasterXSize, d.RasterYSize
        d = None
    else:
        items = [(t, read_geotiff_bounds(t)) for t in tifs]
        W, H = write_vrt_xml(vrt, items, srs, nodata)

    print("VRT 完成: %s" % vrt)
    print("  源图幅 %d   总尺寸 %d x %d" % (len(tifs), W, H))
    print("  可在 QGIS / ArcGIS 中直接打开该 VRT 查看拼接结果")
    return 0


if __name__ == "__main__":
    sys.exit(main())
