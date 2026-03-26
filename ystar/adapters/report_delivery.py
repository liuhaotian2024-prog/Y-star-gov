"""
ystar.adapters.report_delivery  —  向后兼容 shim
=================================================
v0.41.0

此文件已迁移至 ystar.products.report_delivery（3-C 架构归位）。
保留此 shim 以维持向后兼容性。

新代码请使用：
    from ystar.products.report_delivery import DeliveryManager, ...
"""
import sys as _sys
import importlib as _il

# 透明转发到新位置
_sys.modules[__name__] = _il.import_module("ystar.products.report_delivery")
