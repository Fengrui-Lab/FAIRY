"""旧验收函数导入路径的兼容导出；正式场景使用各自文件中的实现。"""
from .scenario_multi_crop_full_season_mixed import validate_full_season

__all__ = ["validate_full_season"]
