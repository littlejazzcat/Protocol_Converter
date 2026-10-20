"""数据模型层 — 协议无关的报文/字段定义"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any


@dataclass
class FieldDef:
    """报文中的单个字段定义"""
    name: str                         # 字段名称
    spn: Optional[int] = None         # SPN 编号 (27930 专用, 其他协议可用 param_id)
    byte_start: int = 1               # 起始字节 (1-based)
    length: int = 1                   # 字节长度
    bit_start: Optional[int] = None   # 位域起始位 (0-based, 仅 bit 类型)
    bit_len: Optional[int] = None     # 位域长度
    data_type: str = "int_le"         # int_le | int_be | float_ieee754 | bits | bcd | ascii
    signed: bool = False              # 整数是否有符号 (int_le / int_be)
    resolution: Optional[float] = None
    offset: Optional[float] = None
    unit: Optional[str] = None
    range_min: Optional[float] = None
    range_max: Optional[float] = None
    enum: Optional[Dict[int, str]] = None     # 枚举值 → 描述
    variable: bool = False                    # 长度可变 (占满剩余数据)
    required: bool = True
    editable: bool = True                     # 编码时是否可编辑 (False=锁定的身份字段)
    default_value: Any = None                 # 编码时的默认值 (用于保留字段等)

    def get_enum_label(self, value: int) -> str:
        if self.enum and value in self.enum:
            return self.enum[value]
        return str(value)

    def get_enum_value(self, label: str) -> Optional[int]:
        if self.enum:
            for k, v in self.enum.items():
                if v == label:
                    return k
        return None


@dataclass
class MessageDef:
    """单条报文定义"""
    name: str                         # 报文名称 (中文)
    abbr: str                         # 缩写 (如 BCL, CHM)
    identifier: Dict[str, Any] = field(default_factory=dict)  # 标识符 (如 {"pf": 16})
    can_id_template: Dict[str, Any] = field(default_factory=dict)  # CAN ID 模板
    direction: str = ""               # 收发方向
    cycle_ms: int = 0                 # 发送周期 (ms)
    data_length: Optional[int] = None # 数据长度, None=不定长
    tp: bool = False                  # 是否需要传输协议
    stage: str = ""                   # 所属阶段
    fields: List[FieldDef] = field(default_factory=list)
    description: str = ""

    @property
    def pgn(self) -> Optional[int]:
        """从 identifier 或 can_id_template 中提取 PGN"""
        pf = self.identifier.get("pf") or self.can_id_template.get("pf")
        if pf is not None:
            return pf * 256
        return None

    @property
    def pgn_hex(self) -> str:
        pgn = self.pgn
        if pgn is not None:
            return f"0x{pgn:08X}"
        return "N/A"

    @property
    def can_id_hex(self) -> str:
        """从模板计算 CAN ID（27930 格式, 其他协议返回模板 ID）"""
        t = self.can_id_template
        # 尝试 27930 格式
        if "pf" in t:
            p = t.get("priority", 0)
            pf = t.get("pf", 0)
            ps = t.get("ps", 0) if isinstance(t.get("ps"), int) else 0
            sa = t.get("sa", 0) if isinstance(t.get("sa"), int) else 0
            can_id = (p << 26) | (pf << 16) | (ps << 8) | sa
            return f"0x{can_id:08X}"
        # 其他协议：返回模板占位
        return f"(模板: {t})"


@dataclass
class CanIdField:
    """CAN ID 位域定义"""
    name: str
    bit_start: int
    bit_len: int
    description: str = ""
    fixed_value: Optional[int] = None
    enum: Optional[Dict[int, str]] = None  # 枚举值 → 描述


@dataclass
class CanIdSchema:
    """CAN ID 结构描述"""
    total_bits: int = 29
    fields: List[CanIdField] = field(default_factory=list)
    message_identifier: str = "pf"   # pf | command_number | data_field
    identifier_field: str = "pf"


@dataclass
class MessageMatcher:
    """报文匹配策略"""
    type: str = "pf_based"           # pf_based | command_number | data_field
    match_field: str = "pf"
    match_byte: Optional[int] = None  # data_field 模式下的匹配字节 (1-based)
    aux_field: Optional[str] = None   # 辅助匹配字段
    aux_byte: Optional[int] = None    # 辅助字段所在字节 (1-based)
    aux_nibble: Optional[str] = None  # 辅助字段半字节位置: "low" | "high"


@dataclass
class ProtocolDefinition:
    """完整协议定义"""
    meta: Dict[str, Any] = field(default_factory=dict)
    can_id_schema: CanIdSchema = field(default_factory=CanIdSchema)
    addresses: Dict[str, Dict] = field(default_factory=dict)
    encoding_rules: Dict[str, Any] = field(default_factory=dict)
    message_matcher: MessageMatcher = field(default_factory=MessageMatcher)
    message_groups: List[Dict] = field(default_factory=list)
    messages: List[MessageDef] = field(default_factory=list)
    transport: Dict[str, Any] = field(default_factory=dict)

    def get_message_by_abbr(self, abbr: str) -> Optional[MessageDef]:
        for m in self.messages:
            if m.abbr.upper() == abbr.upper():
                return m
        return None

    def get_message_by_pf(self, pf: int) -> Optional[MessageDef]:
        for m in self.messages:
            if m.identifier.get("pf") == pf:
                return m
        return None


def resolve_address_name(addresses: Dict[str, Dict], value: int) -> str:
    """按地址表解析地址名。

    匹配顺序:
      1. 精确 value 命中 (如 0x9F 广播、0xA0 功控默认地址)
      2. range 区间回退 (如 "0xA0~0xAE"、"0x20~0x9E")

    未命中返回空串。
    """
    if not addresses:
        return ""
    for k, v in addresses.items():
        if v.get("value") == value:
            return v.get("name", k)
    for k, v in addresses.items():
        rng = v.get("range")
        if not rng or "~" not in str(rng):
            continue
        try:
            lo_s, hi_s = str(rng).split("~")
            lo, hi = int(lo_s.strip(), 16), int(hi_s.strip(), 16)
        except (ValueError, AttributeError):
            continue
        if lo <= value <= hi:
            return v.get("name", k)
    return ""
