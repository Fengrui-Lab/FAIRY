"""旧 Oracle 函数导入路径的兼容导出；正式场景使用各自文件中的实现。"""
from .scenario_multi_crop_full_season_mixed import run_full_season_oracle

__all__ = ["run_full_season_oracle"]
