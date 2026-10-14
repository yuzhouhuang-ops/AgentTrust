"""pytest 公共配置。

这个文件的作用：让测试代码能够 import 到 app/main.py 里的应用。

为什么需要它？
    pytest 运行时，Python 的模块搜索路径不一定包含项目根目录，
    所以直接写 `from app.main import app` 有可能报 ModuleNotFoundError。
    这里显式把项目根目录加到 sys.path 最前面，保证任何一台电脑上都能跑通。

文件名 conftest.py 是 pytest 的约定：它会被自动加载，不需要手动 import。
"""
import sys
from pathlib import Path

# __file__ 是 tests/conftest.py，.parent 是 tests/，再 .parent 就是项目根目录
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
