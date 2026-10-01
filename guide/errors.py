"""领域错误。所有错误都带稳定的 code, 便于离线端按码处理。"""


class GuideError(Exception):
    code = "guide_error"

    def __init__(self, message: str, **extra):
        super().__init__(message)
        self.extra = extra

    def to_dict(self) -> dict:
        d = {"code": self.code, "message": str(self.detail())}
        d.update(self.extra)
        return d

    def detail(self) -> str:
        return self.args[0] if self.args else self.code


class ExhibitNotFound(GuideError):
    code = "exhibit_not_found"


class NotOnDisplay(GuideError):
    """展品在指定时点不在任何有效展柜(已撤展或处于搬移间隙)。"""
    code = "not_on_display"


class MissingBlockError(GuideError):
    """离线端缺少完成请求所需的数据块。"""
    code = "offline_missing_block"

    def __init__(self, block_id: str, message: str | None = None):
        super().__init__(message or f"离线包缺少数据块: {block_id}",
                         block_id=block_id)


class PackExpired(GuideError):
    """离线包空间数据已过有效期, 不得再据此定位展品/寻路。"""
    code = "offline_pack_expired"

    def __init__(self, block_id: str, expires_at: str):
        super().__init__(
            f"空间块 {block_id} 已于 {expires_at} 过期, 请更新离线包后再使用",
            block_id=block_id, expires_at=expires_at)


class LayoutMismatch(GuideError):
    """资料页内容布局版与地图布局版不一致, 必须先刷新一致后才能联展。"""
    code = "layout_mismatch"

    def __init__(self, page_layout: str, map_layout: str):
        super().__init__(
            f"资料页布局版 {page_layout} 与地图布局版 {map_layout} 不一致",
            page_layout=page_layout, map_layout=map_layout)


class CacheRollback(GuideError):
    """试图应用比当前世代更旧的清单/块, 拒绝缓存倒退。"""
    code = "cache_rollback"

    def __init__(self, current: int, incoming: int):
        super().__init__(
            f"拒绝回退: 当前世代 {current}, 收到旧世代 {incoming}",
            current_generation=current, incoming_generation=incoming)
