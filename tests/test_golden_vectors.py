"""已知向量测试 — 用协议文档中的示例验证编解码正确性

测试流程:
1. 根据 msg_abbr 找到 MessageDef
2. encode: 物理量 → 数据域 Hex, 与文档示例比对
3. decode: 数据域 Hex → 物理量, 与文档示例比对

编码测试验证 "代码输出 == 文档预期" (绝对正确性)
解码测试验证 "代码输出 == 文档预期" (绝对正确性)
"""

import pytest

from models.protocol import MessageDef


# ── 工具函数 ──

def _get_msg(protocol, abbr: str) -> MessageDef:
    """按缩写查找报文, 找不到直接 fail"""
    msg = next((m for m in protocol.messages if m.abbr == abbr), None)
    if msg is None:
        pytest.fail(f"未找到报文: {abbr}")
    return msg


def _parse_hex(hex_str: str) -> bytes:
    """ "68 10 DE 0D 02" → b'\x68\x10\xde\x0d\x02' """
    return bytes.fromhex(hex_str.replace(" ", ""))


def _assert_decode_matches(result: dict, expected: dict, context: str):
    """逐字段比对解码结果"""
    mismatches = []
    for key, exp_val in expected.items():
        actual = result.get(key)
        if isinstance(exp_val, dict):
            # 枚举: {"value": 2, "label": "恒流充电"}
            if not isinstance(actual, dict):
                mismatches.append(f"  {key}: expected dict, got {type(actual).__name__}({actual})")
            elif actual.get("value") != exp_val.get("value"):
                mismatches.append(
                    f"  {key}: value mismatch — expected {exp_val['value']}, got {actual.get('value')}"
                )
            elif actual.get("label") != exp_val.get("label"):
                mismatches.append(
                    f"  {key}: label mismatch — expected '{exp_val['label']}', got '{actual.get('label')}'"
                )
        elif isinstance(exp_val, float):
            if not isinstance(actual, (int, float)):
                mismatches.append(f"  {key}: expected float, got {type(actual).__name__}({actual})")
            elif abs(actual - exp_val) > 1e-6:
                mismatches.append(f"  {key}: {actual} != {exp_val}")
        else:
            if actual != exp_val:
                mismatches.append(f"  {key}: {actual} != {exp_val}")
    if mismatches:
        pytest.fail(f"{context}\n" + "\n".join(mismatches))


# ═══════════════════════════════════════════════
#  GB/T 27930
# ═══════════════════════════════════════════════

class TestGoldenGB27930:
    """GB/T 27930 已知向量"""

    @pytest.fixture(autouse=True)
    def _setup(self, gbt27930_engine):
        self.query, self.codec = gbt27930_engine
        self.protocol = self.query.protocol

    def _encode_test(self, abbr, params, expected_hex):
        msg = _get_msg(self.protocol, abbr)
        result = self.codec.encode(msg, params)
        actual = result["data_hex"].replace(" ", "").upper()
        expected = expected_hex.replace(" ", "").upper()
        assert actual == expected, (
            f"[{abbr}] 编码不匹配:\n"
            f"  参数: {params}\n"
            f"  期望: {expected_hex}\n"
            f"  实际: {result['data_hex']}"
        )

    def _decode_test(self, abbr, data_hex, expected):
        msg = _get_msg(self.protocol, abbr)
        data = _parse_hex(data_hex)
        result = self.codec.decode(msg, data)
        _assert_decode_matches(result, expected, f"[{abbr}] 解码不匹配 (data={data_hex})")

    @pytest.mark.parametrize("abbr,params,expected_hex", [
        ("BCL", {"车辆接口充电电压需求": 420.0, "车辆接口充电电流需求": -45.0, "充电模式": "恒流充电"}, "68 10 DE 0D 02"),
        # BHM: 365.1/0.1 有浮点精度问题, 直接用原始整数值 3651 → LE: 43 0E
        ("BHM", {"绝缘监测允许总电压": 365.1}, "43 0E"),
        ("CHM", {"充电机通信协议版本号": 257}, "01 01 00"),
        ("BRO", {"车辆充电准备好": "准备好(0xAA)"}, "AA"),
        ("CRO", {"充电机充电准备好": "完成准备(0xAA)"}, "AA"),
    ])
    def test_encode(self, abbr, params, expected_hex):
        self._encode_test(abbr, params, expected_hex)

    @pytest.mark.parametrize("abbr,data_hex,expected", [
        ("BCL", "68 10 DE 0D 02", {
            "车辆接口充电电压需求": 420.0,
            "车辆接口充电电流需求": -45.0,
            "充电模式": {"value": 2, "label": "恒流充电"},
        }),
        ("BHM", "43 0E", {"绝缘监测允许总电压": 365.1}),
        ("CHM", "01 01 00", {"充电机通信协议版本号": 257}),
        ("BRO", "AA", {"车辆充电准备好": {"value": 170, "label": "准备好(0xAA)"}}),
        ("CRO", "AA", {"充电机充电准备好": {"value": 170, "label": "完成准备(0xAA)"}}),
        ("CCS", "68 10 DE 0D 0F 00 01", {
            "车辆接口当前电压测量值": 420.0,
            "车辆接口当前电流测量值": -45.0,
            "累计充电时间": 15,
            "充电允许": {"value": 1, "label": "允许"},
        }),
    ])
    def test_decode(self, abbr, data_hex, expected):
        self._decode_test(abbr, data_hex, expected)


# ═══════════════════════════════════════════════
#  安世博
# ═══════════════════════════════════════════════

class TestGoldenAnshibo:
    """安世博 已知向量"""

    @pytest.fixture(autouse=True)
    def _setup(self, anshibo_engine):
        self.query, self.codec = anshibo_engine
        self.protocol = self.query.protocol

    @pytest.mark.parametrize("abbr,data_hex,expected", [
        ("CMD_00_RESP", "13 00 00 00 00 07 41 9E", {
            "模块输出电压": 475550,
        }),
        ("CMD_02_REQ", "10 02 00 00 00 07 41 9E", {
            "输出电压设定值": 475550,
        }),
        ("CMD_04_REQ", "10 04 00 00 00 00 00 00", {
            "开关机": {"value": 0, "label": "开机"},
        }),
        ("CMD_04_REQ", "10 04 00 00 00 00 00 01", {
            "开关机": {"value": 1, "label": "关机"},
        }),
        ("CMD_04_REQ", "10 04 00 00 00 00 00 11", {
            "开关机": {"value": 17, "label": "线性关机"},
        }),
    ])
    def test_decode(self, abbr, data_hex, expected):
        msg = _get_msg(self.protocol, abbr)
        data = _parse_hex(data_hex)
        result = self.codec.decode(msg, data)
        _assert_decode_matches(result, expected, f"[{abbr}] 解码不匹配 (data={data_hex})")


# ═══════════════════════════════════════════════
#  国网三统一
# ═══════════════════════════════════════════════

class TestGoldenSgUnified:
    """国网三统一 已知向量"""

    @pytest.fixture(autouse=True)
    def _setup(self, sg_unified_engine):
        self.query, self.codec = sg_unified_engine
        self.protocol = self.query.protocol

    @pytest.mark.parametrize("abbr,params,expected_hex", [
        ("RC_CMD_FIXED", {
            "操作指令": "快速开机", "输出电压范围": "低压段(200-500V)",
            "功分接触器": "分断", "主接触器": "分断", "分组编码": 0,
            "给定电压": 100.0, "给定电流": 10.0, "电池电压": 200.0,
        }, "01 00 E8 03 E8 03 D0 07"),
        ("RC_CMD_FIXED", {
            "操作指令": "停止充电", "输出电压范围": "高压段(500-950V)",
            "功分接触器": "闭合", "主接触器": "闭合", "分组编码": 1,
            "给定电压": 500.0, "给定电流": 30.0, "电池电压": 480.0,
        }, "72 01 88 13 B8 0B C0 12"),
    ])
    def test_encode(self, abbr, params, expected_hex):
        msg = _get_msg(self.protocol, abbr)
        result = self.codec.encode(msg, params)
        actual = result["data_hex"].replace(" ", "").upper()
        expected = expected_hex.replace(" ", "").upper()
        assert actual == expected, (
            f"[{abbr}] 编码不匹配:\n"
            f"  参数: {params}\n"
            f"  期望: {expected_hex}\n"
            f"  实际: {result['data_hex']}"
        )

    @pytest.mark.parametrize("abbr,data_hex,expected", [
        ("RC_CMD_FIXED", "01 00 E8 03 E8 03 D0 07", {
            "操作指令": {"value": 1, "label": "快速开机"},
            "输出电压范围": {"value": 0, "label": "低压段(200-500V)"},
            "功分接触器": {"value": 0, "label": "分断"},
            "主接触器": {"value": 0, "label": "分断"},
            "分组编码": 0,
            "给定电压": 100.0,
            "给定电流": 10.0,
            "电池电压": 200.0,
        }),
        ("RC_CMD_FIXED", "72 01 88 13 B8 0B C0 12", {
            "操作指令": {"value": 2, "label": "停止充电"},
            "输出电压范围": {"value": 1, "label": "高压段(500-950V)"},
            "功分接触器": {"value": 1, "label": "闭合"},
            "主接触器": {"value": 1, "label": "闭合"},
            "分组编码": 1,
            "给定电压": 500.0,
            "给定电流": 30.0,
            "电池电压": 480.0,
        }),
    ])
    def test_decode(self, abbr, data_hex, expected):
        msg = _get_msg(self.protocol, abbr)
        data = _parse_hex(data_hex)
        result = self.codec.decode(msg, data)
        _assert_decode_matches(result, expected, f"[{abbr}] 解码不匹配 (data={data_hex})")


# ═══════════════════════════════════════════════
#  英飞源
# ═══════════════════════════════════════════════

class TestGoldenInfypower:
    """英飞源 已知向量"""

    @pytest.fixture(autouse=True)
    def _setup(self, infypower_engine):
        self.query, self.codec = infypower_engine
        self.protocol = self.query.protocol

    @pytest.mark.parametrize("abbr,params,expected_hex", [
        ("CMD_08_SYS_INT", {"系统总电压": 500000, "系统总电流": 60000},
         "00 07 A1 20 00 00 EA 60"),
        ("CMD_09_MOD_INT", {"模块N电压": 200000, "模块N电流": 5000},
         "00 03 0D 40 00 00 13 88"),
        ("CMD_1A_POWER", {"开关机": "开机"},
         "00 00 00 00 00 00 00 00"),
        ("CMD_1B_SET_ALL", {"电压": 300000, "总电流": 10000},
         "00 04 93 E0 00 00 27 10"),
    ])
    def test_encode(self, abbr, params, expected_hex):
        msg = _get_msg(self.protocol, abbr)
        result = self.codec.encode(msg, params)
        actual = result["data_hex"].replace(" ", "").upper()
        expected = expected_hex.replace(" ", "").upper()
        assert actual == expected, (
            f"[{abbr}] 编码不匹配:\n"
            f"  参数: {params}\n"
            f"  期望: {expected_hex}\n"
            f"  实际: {result['data_hex']}"
        )

    @pytest.mark.parametrize("abbr,data_hex,expected", [
        ("CMD_08_SYS_INT", "00 07 A1 20 00 00 EA 60",
         {"系统总电压": 500000, "系统总电流": 60000}),
        ("CMD_09_MOD_INT", "00 03 0D 40 00 00 13 88",
         {"模块N电压": 200000, "模块N电流": 5000}),
        ("CMD_01_SYS_FLOAT", "43 FA 00 00 42 48 00 00",
         {"系统电压": 500.0, "系统总电流": 50.0}),
        ("CMD_03_MOD_FLOAT", "43 48 00 00 41 A0 00 00",
         {"模块N电压": 200.0, "模块N电流": 20.0}),
    ])
    def test_decode(self, abbr, data_hex, expected):
        msg = _get_msg(self.protocol, abbr)
        data = _parse_hex(data_hex)
        result = self.codec.decode(msg, data)
        _assert_decode_matches(result, expected, f"[{abbr}] 解码不匹配 (data={data_hex})")
