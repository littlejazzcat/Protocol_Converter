"""Excel 批量解析面板"""

import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from services.query_engine import QueryEngine
from services.can_codec import CanCodec
from services.excel_parser import ExcelParser


class ParserPanel(QWidget):
    """Excel 批量解析面板"""

    def __init__(self, query_engine: QueryEngine, codec: CanCodec):
        super().__init__()
        self.query = query_engine
        self.codec = codec
        self.parser = ExcelParser(query_engine, codec)
        self._filepath = ""
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── 文件选择 ──
        file_group = QGroupBox("Excel 文件")
        file_layout = QHBoxLayout(file_group)
        self.file_label = QLabel("未选择文件")
        self.file_label.setStyleSheet("color: #888;")
        file_layout.addWidget(self.file_label)
        file_layout.addStretch()
        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self._on_browse)
        file_layout.addWidget(btn_browse)
        self.btn_load = QPushButton("加载")
        self.btn_load.clicked.connect(self._on_load)
        self.btn_load.setEnabled(False)
        file_layout.addWidget(self.btn_load)
        layout.addWidget(file_group)

        # ── 列映射 ──
        map_group = QGroupBox("列映射")
        map_layout = QHBoxLayout(map_group)
        map_layout.addWidget(QLabel("CAN ID 列:"))
        self.id_col_label = QLabel("—")
        self.id_col_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        map_layout.addWidget(self.id_col_label)
        map_layout.addSpacing(20)
        map_layout.addWidget(QLabel("数据域列:"))
        self.data_col_label = QLabel("—")
        self.data_col_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        map_layout.addWidget(self.data_col_label)
        map_layout.addStretch()
        self.btn_parse = QPushButton("▶ 开始解析")
        self.btn_parse.clicked.connect(self._on_parse)
        self.btn_parse.setEnabled(False)
        self.btn_parse.setStyleSheet("font-weight: bold; font-size: 13px; padding: 6px 16px;")
        map_layout.addWidget(self.btn_parse)
        layout.addWidget(map_group)

        # ── 进度 + 汇总 ──
        progress_layout = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        progress_layout.addWidget(self.progress)
        self.summary_label = QLabel("")
        progress_layout.addWidget(self.summary_label)
        progress_layout.addStretch()
        self.btn_export = QPushButton("导出 Excel")
        self.btn_export.clicked.connect(self._on_export)
        self.btn_export.setEnabled(False)
        progress_layout.addWidget(self.btn_export)
        layout.addLayout(progress_layout)

        # ── 数据表格 ──
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.table)

    # ── 事件 ──────────────────────────────────────

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Excel 文件", "",
            "Excel/CSV 文件 (*.xlsx *.xls *.csv);;所有文件 (*.*)"
        )
        if path:
            self._filepath = path
            self.file_label.setText(os.path.basename(path))
            self.file_label.setStyleSheet("color: #000;")
            self.btn_load.setEnabled(True)

    def _on_load(self):
        if not self._filepath:
            return
        try:
            # 1. 直接加载
            self.parser.load(self._filepath)
        except Exception:
            # 2. 失败 → 复制到临时目录，改后缀为 .csv 再试
            try:
                import shutil, tempfile
                fd, dst = tempfile.mkstemp(suffix=".csv")
                os.close(fd)
                shutil.copy2(self._filepath, dst)
                self.parser.load(dst)
                os.unlink(dst)
            except Exception as e2:
                QMessageBox.critical(self, "加载失败", str(e2))
                return

        try:
            id_col, data_col = self.parser.auto_map_columns()
            if id_col:
                self.id_col_label.setText(f"「{id_col}」")
            else:
                self.id_col_label.setText("⚠ 未识别")
            if data_col:
                self.data_col_label.setText(f"「{data_col}」")
            else:
                self.data_col_label.setText("⚠ 未识别")

            # 预览
            preview = self.parser.preview(20)
            self._show_table(preview, self.parser.columns)
            self.summary_label.setText(f"✓ 已加载 {self.parser.row_count} 行，{len(self.parser.columns)} 列 · {os.path.basename(self._filepath)}")

            self.btn_parse.setEnabled(True)
            self.btn_export.setEnabled(False)
        except Exception as e3:
            self.summary_label.setText(f"加载失败: {e3}")

    def _on_parse(self):
        self.progress.setVisible(True)
        self.progress.setMaximum(self.parser.row_count)
        self.btn_parse.setEnabled(False)
        self.btn_export.setEnabled(False)

        def update_progress(current, total):
            self.progress.setValue(current)

        try:
            self.parser.parse(progress_callback=update_progress)
        except Exception as e:
            QMessageBox.critical(self, "解析失败", str(e))
            self.btn_parse.setEnabled(True)
            return

        # 显示结果
        result_rows = self.parser.to_rows()
        # 原始列在前，解析列在后
        orig_cols = [c for c in self.parser.columns
                     if c not in (self.parser._id_col, self.parser._data_col)
                     and not c.startswith("Unnamed")]
        parse_cols = ["CAN ID", "数据域", "CAN ID 解析", "报文", "解析结果"]
        display_cols = orig_cols + parse_cols
        self._show_table(result_rows, display_cols)

        summary = self.parser.get_summary()
        parts = [f"共 {summary['total']} 行", f"匹配 {summary['matched']}"]
        if summary.get('tp', 0) > 0:
            parts.append(f"TP {summary['tp']}")
        parts.append(f"未知 {summary['unknown']}")
        parts.append(f"错误 {summary['error']}")
        self.summary_label.setText(" | ".join(parts))
        self.progress.setVisible(False)
        self.btn_parse.setEnabled(True)
        self.btn_export.setEnabled(True)

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出解析结果", "parsed_result.xlsx",
            "Excel 文件 (*.xlsx)"
        )
        if path:
            try:
                self.parser.export(path)
                QMessageBox.information(self, "导出成功", f"已保存到:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", str(e))

    def _show_table(self, rows, columns):
        """用行列表填充表格"""
        import math
        self.table.clear()
        self.table.setRowCount(len(rows))
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setHorizontalScrollMode(self.table.ScrollMode.ScrollPerPixel)

        for r, row in enumerate(rows):
            for c, col in enumerate(columns):
                val = row.get(col, "")
                if isinstance(val, float):
                    if math.isnan(val):
                        val = ""
                    elif val == int(val):
                        val = str(int(val))
                    else:
                        val = f"{val:.2f}"
                self.table.setItem(r, c, QTableWidgetItem(str(val) if val is not None else ""))
