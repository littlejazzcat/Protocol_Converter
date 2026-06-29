"""报文查询面板 — 左侧报文列表 + 右侧详情表格"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem,
    QLineEdit, QLabel, QHeaderView, QPushButton, QGroupBox,
    QTextEdit
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from services.query_engine import QueryEngine
from services.can_codec import CanCodec
from models.protocol import MessageDef


class QueryPanel(QWidget):
    """查询面板：协议报文浏览与搜索"""

    message_selected = Signal(object)  # MessageDef

    def __init__(self, query_engine: QueryEngine, codec: CanCodec):
        super().__init__()
        self.query = query_engine
        self.codec = codec
        self._setup_ui()
        self._load_messages()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 搜索栏
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("搜索:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("报文名/缩写/SPN...")
        self.search_input.textChanged.connect(self._on_search)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # 主分割器
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：报文树
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("报文列表"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(220)
        self.tree.currentItemChanged.connect(self._on_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        left_layout.addWidget(self.tree)
        splitter.addWidget(left_widget)

        # 右侧：详情
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 报文基本信息
        self.info_group = QGroupBox("报文信息")
        info_layout = QVBoxLayout(self.info_group)
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setMaximumHeight(120)
        self.info_text.setFont(QFont("Consolas", 10))
        info_layout.addWidget(self.info_text)
        right_layout.addWidget(self.info_group)

        # 字段定义表格
        self.field_group = QGroupBox("数据域定义")
        field_layout = QVBoxLayout(self.field_group)
        self.field_table = QTableWidget()
        self.field_table.setColumnCount(6)
        self.field_table.setHorizontalHeaderLabels(["字段名", "SPN", "字节", "长度", "分辨率/偏移", "单位/枚举"])
        self.field_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.field_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.field_table.setAlternatingRowColors(True)
        self.field_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.field_table.setSelectionBehavior(QTableWidget.SelectRows)
        field_layout.addWidget(self.field_table)
        right_layout.addWidget(self.field_group)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter)

    def _load_messages(self):
        """按阶段分组加载报文列表"""
        self.tree.clear()
        for group in self.query.protocol.message_groups:
            group_name = group.get("name", "")
            group_item = QTreeWidgetItem(self.tree, [group_name])
            group_item.setFlags(group_item.flags() | Qt.ItemIsEnabled)
            font = group_item.font(0)
            font.setBold(True)
            group_item.setFont(0, font)

            for abbr in group.get("messages", []):
                msg = self.query.by_abbr(abbr)
                if msg:
                    # 27930 缩写在前，模块协议中文在前
                    pid = self.query.protocol.meta.get("protocol_id", "")
                    if pid == "gbt27930_v1.1":
                        label = f"{msg.abbr}  {msg.name}"
                    else:
                        label = f"{msg.name}  ({msg.abbr})"
                    item = QTreeWidgetItem(group_item, [label])
                    item.setData(0, Qt.UserRole, msg)
            group_item.setExpanded(True)

    def _on_item_clicked(self, current, _previous):
        if current is None:
            return
        msg = current.data(0, Qt.UserRole)
        if msg is None:
            return
        self._show_message(msg)

    def _on_item_double_clicked(self, item, _column):
        if item is None:
            return
        msg = item.data(0, Qt.UserRole)
        if msg is None:
            return
        self.message_selected.emit(msg)

    def _show_message(self, msg: MessageDef):
        """显示报文详情"""
        # 基本信息
        can_id = self.codec.make_can_id(msg)
        pgn_info = ""
        if msg.pgn is not None:
            pgn_info = f"PGN: {msg.pgn} ({msg.pgn_hex})    PF: 0x{msg.identifier.get('pf', 0):02X}\n"
        info_lines = [
            f"名称: {msg.name}",
            f"缩写: {msg.abbr}",
            f"{pgn_info}"f"CAN ID: 0x{can_id:08X}    方向: {msg.direction}",
            f"周期: {msg.cycle_ms}ms    数据长度: {msg.data_length if msg.data_length else '不定长'}字节",
            f"阶段: {msg.stage}    {'TP(传输协议)' if msg.tp else ''}",
        ]
        # 滤掉空行
        info_lines = [l for l in info_lines if l.strip()]
        self.info_text.setPlainText("\n".join(info_lines))

        # 字段表格
        self._populate_field_table(msg)

    def _populate_field_table(self, msg: MessageDef):
        """填充字段定义表格"""
        self.field_table.setRowCount(len(msg.fields))
        for i, field in enumerate(msg.fields):
            # 字段名
            name = field.name
            if not field.required:
                name += " (可选)"
            self.field_table.setItem(i, 0, QTableWidgetItem(name))
            # SPN
            self.field_table.setItem(i, 1, QTableWidgetItem(str(field.spn) if field.spn else "-"))
            # 字节
            byte_pos = f"Byte{field.byte_start}"
            if field.bit_start is not None:
                byte_pos += f".bit{field.bit_start}"
            self.field_table.setItem(i, 2, QTableWidgetItem(byte_pos))
            # 长度
            if field.bit_len:
                self.field_table.setItem(i, 3, QTableWidgetItem(f"{field.bit_len}bit"))
            else:
                self.field_table.setItem(i, 3, QTableWidgetItem(f"{field.length}B"))
            # 分辨率/偏移
            res_text = ""
            if field.resolution is not None:
                res_text += f"×{field.resolution}"
            if field.offset is not None and field.offset != 0:
                res_text += f" +({field.offset})"
            if not res_text:
                res_text = "-"
            self.field_table.setItem(i, 4, QTableWidgetItem(res_text))
            # 单位/枚举
            extra = ""
            if field.unit:
                extra = field.unit
            if field.enum:
                enum_str = ", ".join(f"{v}({k})" for k, v in field.enum.items())
                extra = enum_str if not extra else f"{extra} | {enum_str}"
            self.field_table.setItem(i, 5, QTableWidgetItem(extra or "-"))

    def _on_search(self, text: str):
        """搜索过滤报文列表"""
        if len(text) < 1:
            # 恢复全部
            for i in range(self.tree.topLevelItemCount()):
                group = self.tree.topLevelItem(i)
                group.setHidden(False)
                for j in range(group.childCount()):
                    group.child(j).setHidden(False)
            return

        results = self.query.search(text)
        result_abbrs = {m.abbr for m in results}

        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            any_visible = False
            for j in range(group.childCount()):
                child = group.child(j)
                msg = child.data(0, Qt.UserRole)
                visible = msg is not None and msg.abbr in result_abbrs
                child.setHidden(not visible)
                if visible:
                    any_visible = True
            group.setHidden(not any_visible)

    def refresh(self):
        self._load_messages()
