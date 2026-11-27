"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import award_package, resource

# 送审材料包路由注册在通用资源路由之前，避免动态路径抢先匹配
ROUTERS = [award_package, resource]
