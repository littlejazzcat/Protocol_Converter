"""查询引擎 — 协议无关的报文查询"""

from typing import Optional, List, Dict, Any

from models.protocol import ProtocolDefinition, MessageDef


class QueryEngine:
    """报文查询引擎，构造时注入协议定义"""

    def __init__(self, protocol: ProtocolDefinition):
        self.protocol = protocol
        self._by_abbr: Dict[str, MessageDef] = {}
        self._by_pf: Dict[int, MessageDef] = {}
        self._by_command: Dict[int, MessageDef] = {}
        self._by_data_cmd: Dict[int, MessageDef] = {}
        self._init_index()

    def _init_index(self):
        matcher = self.protocol.message_matcher
        for msg in self.protocol.messages:
            self._by_abbr[msg.abbr.upper()] = msg

            # PF-based index
            pf = msg.identifier.get("pf")
            if pf is not None:
                self._by_pf[pf] = msg

            # command_number index (英飞源)
            cmd = msg.identifier.get("command_number")
            if cmd is not None:
                self._by_command[cmd] = msg

            # data_field index (安世博: command_type)
            ct = msg.identifier.get("command_type")
            if ct is not None:
                self._by_data_cmd[ct] = msg

    def by_name(self, name: str) -> Optional[MessageDef]:
        for msg in self.protocol.messages:
            if name in msg.name:
                return msg
        return None

    def by_abbr(self, abbr: str) -> Optional[MessageDef]:
        return self._by_abbr.get(abbr.upper())

    def by_pf(self, pf: int) -> Optional[MessageDef]:
        return self._by_pf.get(pf)

    def by_command(self, cmd: int) -> Optional[MessageDef]:
        return self._by_command.get(cmd)

    def by_data_command(self, ct: int) -> Optional[MessageDef]:
        return self._by_data_cmd.get(ct)

    def by_id(self, identifier: dict) -> Optional[MessageDef]:
        """协议无关的标识符查询"""
        pf = identifier.get("pf")
        if pf is not None:
            return self.by_pf(pf)
        cmd = identifier.get("command_number")
        if cmd is not None:
            return self.by_command(cmd)
        ct = identifier.get("command_type")
        if ct is not None:
            return self.by_data_command(ct)
        return None

    def by_can_id(self, can_id: int, data: Optional[bytes] = None) -> Optional[MessageDef]:
        """从 CAN ID 中提取标识符并匹配报文（协议无关）"""
        schema = self.protocol.can_id_schema
        matcher = self.protocol.message_matcher

        if matcher.type == "pf_based":
            pf = self._extract_can_id_field(can_id, "pf")
            if pf is not None:
                return self.by_pf(pf)

        elif matcher.type == "command_number":
            cmd = self._extract_can_id_field(can_id, "command_number")
            if cmd is not None:
                return self.by_command(cmd)

        elif matcher.type == "data_field" and data is not None and len(data) >= 2:
            cmd_byte = matcher.match_byte or 1
            cmd_idx = cmd_byte - 1
            if cmd_idx < len(data):
                ct = data[cmd_idx]
                # 也读取 aux_field (MessageType) 用于精确匹配
                aux_byte = matcher.aux_byte or 1
                aux_idx = aux_byte - 1
                msg_type = None
                if aux_idx < len(data) and matcher.aux_nibble == "low":
                    msg_type = data[aux_idx] & 0x0F
                # 先尝试精确匹配 command_type + message_type
                if msg_type is not None:
                    for m in self.protocol.messages:
                        if m.identifier.get("command_type") == ct:
                            msg_type_field = next((f for f in m.fields if not f.editable and f.bit_start == 0 and f.bit_len == 4), None)
                            if msg_type_field and msg_type_field.default_value == msg_type:
                                return m
                # 回退到只按 command_type 匹配
                return self.by_data_command(ct)

        return None

    def _extract_can_id_field(self, can_id: int, field_name: str) -> Optional[int]:
        """从 CAN ID 中按 can_id_schema 提取指定字段"""
        for f in self.protocol.can_id_schema.fields:
            if f.name == field_name:
                mask = ((1 << f.bit_len) - 1) << f.bit_start
                return (can_id & mask) >> f.bit_start
        return None

    def parse_can_id(self, can_id: int) -> Dict[str, Any]:
        """解析 CAN ID 各位域（协议无关，按 can_id_schema）"""
        result = {}
        for f in self.protocol.can_id_schema.fields:
            mask = ((1 << f.bit_len) - 1) << f.bit_start
            val = (can_id & mask) >> f.bit_start
            result[f.name] = val
            result[f"{f.name}_hex"] = f"0x{val:0{(f.bit_len + 3) // 4}X}"
        return result

    def by_stage(self, stage: str) -> List[MessageDef]:
        return [m for m in self.protocol.messages if m.stage == stage]

    def search(self, keyword: str) -> List[MessageDef]:
        kw = keyword.lower()
        results = []
        for msg in self.protocol.messages:
            if kw in msg.name.lower() or kw in msg.abbr.lower():
                results.append(msg)
                continue
            for field in msg.fields:
                if kw in field.name.lower() or (field.spn and str(field.spn) == kw):
                    results.append(msg)
                    break
        return results

    def all_messages(self) -> List[MessageDef]:
        return self.protocol.messages

    def all_stages(self) -> List[str]:
        seen = []
        for g in self.protocol.message_groups:
            name = g.get("name", "")
            if name not in seen:
                seen.append(name)
        return seen

    def messages_in_group(self, group_name: str) -> List[MessageDef]:
        for g in self.protocol.message_groups:
            if g.get("name") == group_name:
                abbrs = g.get("messages", [])
                return [self.by_abbr(a) for a in abbrs if self.by_abbr(a)]
        return []
