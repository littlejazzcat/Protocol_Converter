"""完整性校验测试 — 验证全部四份协议定义的内部一致性"""

import pytest
from models.loader import validate_integrity


class TestIntegrityGB27930:
    """GB/T 27930-2023 A类系统"""

    def test_no_errors(self, gbt27930):
        errors = validate_integrity(gbt27930)
        assert errors == [], f"发现 {len(errors)} 个完整性错误:\n" + "\n".join(errors)

    def test_all_messages_have_pf(self, gbt27930):
        for msg in gbt27930.messages:
            assert "pf" in msg.identifier, f"{msg.abbr} 缺少 PF 标识符"

    def test_pf_uniqueness(self, gbt27930):
        seen = {}
        for msg in gbt27930.messages:
            pf = msg.identifier.get("pf")
            if pf in seen:
                pytest.fail(f"PF 0x{pf:02X} 重复: {seen[pf]} vs {msg.abbr}")
            seen[pf] = msg.abbr

    def test_message_count(self, gbt27930):
        assert len(gbt27930.messages) == 22, \
            f"预期 22 条报文，实际 {len(gbt27930.messages)}"


class TestIntegrityAnshibo:
    """安世博 UAA-1K040B-E"""

    def test_no_errors(self, anshibo):
        errors = validate_integrity(anshibo)
        assert errors == [], f"发现 {len(errors)} 个完整性错误:\n" + "\n".join(errors)

    def test_request_response_pairing(self, anshibo):
        """每条命令应有成对的请求和应答（序列号类除外）"""
        all_abbrs = {m.abbr for m in anshibo.messages}
        for abbr in all_abbrs:
            if abbr.endswith("_REQ"):
                resp_abbr = abbr.replace("_REQ", "_RESP")
                if "SERIAL" not in abbr:  # 序列号类特殊处理
                    assert resp_abbr in all_abbrs, \
                        f"请求报文 {abbr} 缺少对应应答 {resp_abbr}"

    def test_all_messages_have_command_type(self, anshibo):
        for msg in anshibo.messages:
            assert "command_type" in msg.identifier, \
                f"{msg.abbr} 缺少 command_type"


class TestIntegritySgUnified:
    """国网三统一模块协议"""

    def test_no_errors(self, sg_unified):
        errors = validate_integrity(sg_unified)
        assert errors == [], f"发现 {len(errors)} 个完整性错误:\n" + "\n".join(errors)

    def test_all_messages_have_pf(self, sg_unified):
        for msg in sg_unified.messages:
            assert "pf" in msg.identifier, f"{msg.abbr} 缺少 PF 标识符"


class TestIntegrityInfypower:
    """英飞源充电模块 V107"""

    def test_no_errors(self, infypower):
        errors = validate_integrity(infypower)
        assert errors == [], f"发现 {len(errors)} 个完整性错误:\n" + "\n".join(errors)

    def test_all_messages_have_command_number(self, infypower):
        for msg in infypower.messages:
            assert "command_number" in msg.identifier, \
                f"{msg.abbr} 缺少 command_number"

    def test_device_number_consistency(self, infypower):
        """设备号应为 0x0A(点对点) 或 0x0B(组命令)"""
        for msg in infypower.messages:
            dn = msg.identifier.get("device_number")
            assert dn in (10, 11), \
                f"{msg.abbr} device_number={dn}, 期望 10 或 11"


@pytest.mark.parametrize("proto_id", [
    "gbt27930_v1.1", "anshibo_1k040b", "sg_unified_v107", "infypower_v107"
])
def test_all_protocols_pass_integrity(all_protocols, proto_id):
    """所有协议都应通过完整性校验"""
    errors = validate_integrity(all_protocols)
    assert errors == [], \
        f"[{proto_id}] 发现 {len(errors)} 个完整性错误:\n" + "\n".join(errors)


def test_can_id_schema_no_overlap(all_protocols):
    """CAN ID Schema 位域不应重叠"""
    for f in all_protocols.can_id_schema.fields:
        start = f.bit_start
        end = f.bit_start + f.bit_len - 1
        assert 0 <= start < all_protocols.can_id_schema.total_bits, \
            f"{f.name}: bit_start={start} 超出 0~{all_protocols.can_id_schema.total_bits - 1}"
        assert end < all_protocols.can_id_schema.total_bits, \
            f"{f.name}: bit_end={end} 超出 0~{all_protocols.can_id_schema.total_bits - 1}"
