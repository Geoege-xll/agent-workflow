"""支持 python -m native_config；与工作流插件及中央安装记录独立。"""

from .cli import main

raise SystemExit(main())
