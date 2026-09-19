# -*- coding: utf-8 -*-
"""文案模板骨架（输出侧文本）。见 `template.py` 的模块说明。"""
from .template import (TextSpec, TextTable, extract_params, render_or, render_via,
                       safe_format, text_of)

__all__ = ["TextSpec", "TextTable", "safe_format", "extract_params",
           "render_or", "render_via", "text_of"]
