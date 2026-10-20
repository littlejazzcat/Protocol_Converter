# Protocol Converter 架构文档

> 适用版本：`v1.2.2`（2026-10）
> 本文描述当前已落地的实现，不是规划稿。旧版 PySide6 架构见 `readme/protocol_converter-v1.1.md`。

---

## 一、定位与设计约束

**定位**：面向充电通信协议的多协议 CAN 报文工具，提供协议查询、单帧编解码、批量抓包解析三项能力。

**设计约束**：

| 约束 | 内容 |
|------|------|
| 协议与代码分离 | 协议的报文、字段、位域全部定义在 `data/*.json`，代码中不出现具体报文名 |
| 零重依赖 | 不使用 pandas / numpy / PySide6，批量解析用 `csv` + `openpyxl` 自实现 |
| 单机单实例 | 本地 `127.0.0.1:8027`，浏览器访问，无多用户并发设计 |
| 轻量交付 | PyInstaller onedir，目录约 87MB，压缩包约 41MB |

---

## 二、目录结构

```
protocol_converter/
├── app.py                    Web 层：路由、全局状态、自更新
├── main.py                   启动入口：uvicorn + 自动开浏览器
├── models/                   模型层
│   ├── protocol.py           dataclass 定义 + 地址解析工具
│   └── loader.py             JSON → 模型，完整性校验
├── services/                 服务层
│   ├── query_engine.py       报文索引与匹配
│   ├── can_codec.py          编解码 + 两套多帧
│   └── excel_parser.py       批量解析（格式识别/列映射/归组/导出）
├── data/                     协议定义（唯一事实来源）
│   ├── gbt27930_v1.1.json
│   ├── anshibo_1k040b.json
│   ├── sg_unified_v107.json
│   └── infypower_v107.json
├── templates/
│   └── index.html            单页应用（三 Tab）
├── tests/                    测试与真实抓包样本
├── architecture/             本文档
├── update/                   版本变更记录
├── issue/                    缺陷记录
├── readme/                   历史设计文档
└── ProtocolConverter.spec    PyInstaller 配置
```

---

## 三、分层架构

```
┌─────────────────────────────────────────────┐
│  浏览器  templates/index.html（原生 JS 单页）  │
└───────────────────┬─────────────────────────┘
                    │ HTTP / JSON / Form
┌───────────────────▼─────────────────────────┐
│  Web 层  app.py                              │
│  · 路由（页面 5 + API 13）                    │
│  · 全局 state：protocol / query / codec /   │
│    parser / parse_results                    │
│  · 自更新（双源检测、流式下载、进度轮询）      │
└───────────────────┬─────────────────────────┘
                    │ 纯 Python 调用
┌───────────────────▼─────────────────────────┐
│  服务层                                       │
│  QueryEngine  索引、匹配、CAN ID 位域解析      │
│  CanCodec     字段编解码、TP / 自定义多帧      │
│  ExcelParser  文件加载、列映射、批量归组解析    │
└───────────────────┬─────────────────────────┘
                    │
┌───────────────────▼─────────────────────────┐
│  模型层  models/                              │
│  ProtocolDefinition / MessageDef / FieldDef  │
│  CanIdSchema / CanIdField / MessageMatcher   │
└───────────────────┬─────────────────────────┘
                    │ json.load
┌───────────────────▼─────────────────────────┐
│  数据层  data/*.json                          │
└─────────────────────────────────────────────┘
```

**依赖方向严格向下**：服务层不认识 HTTP，模型层不认识协议语义（如「PF」「命令号」都由 JSON 描述，代码只按 `can_id_schema` 通用处理）。

---

## 四、数据模型

### 4.1 ProtocolDefinition

| 字段 | 类型 | 说明 |
|------|------|------|
| `meta` | dict | 协议名、ID、版本、波特率、帧格式 |
| `can_id_schema` | CanIdSchema | 29 位标识符的位域切分 |
| `addresses` | dict | 地址表，支持单值 `value` 与区间 `range` |
| `encoding_rules` | dict | 默认字节序、未用位填充值 |
| `message_matcher` | MessageMatcher | 报文匹配策略 |
| `message_groups` | list | 报文分组（UI 消息树） |
| `messages` | list[MessageDef] | 报文定义 |
| `transport` | dict | 自定义多帧配置（可选） |

### 4.2 MessageDef

| 字段 | 说明 |
|------|------|
| `name` / `abbr` | 中文名 / 缩写 |
| `identifier` | 匹配用的标识符，如 `{"pf": 16}`、`{"command_number": 8, "role": "req"}` |
| `can_id_template` | 编码时拼 CAN ID 的位域取值 |
| `direction` | 人读方向文本 |
| `cycle_ms` | 周期，0 表示非周期 |
| `data_length` | 固定长度；`null` 表示不定长 |
| `tp` | 是否可能走传输协议 |
| `stage` | 所属阶段/分组 |
| `fields` | 字段列表 |
| `description` | 备注 |

派生属性：`pgn`（= `pf << 8`）、`pgn_hex`、`can_id_hex`。

### 4.3 FieldDef

| 字段 | 说明 |
|------|------|
| `byte_start` | 1-based 起始字节 |
| `length` | 字节长度 |
| `bit_start` / `bit_len` | 位域（`data_type="bits"` 时） |
| `data_type` | `int_le` / `int_be` / `float_ieee754` / `bits` / `bcd` / `ascii` |
| `resolution` / `offset` | 物理量换算：`phys = raw * resolution + offset` |
| `unit` / `enum` | 单位 / 枚举标签 |
| `signed` | 有符号整数（补码） |
| `variable` | 变长：占满从 `byte_start` 起的剩余数据 |
| `editable` | 编码时是否允许编辑（身份字段可锁） |
| `default_value` | 编码默认值 |

`variable` 用于「长度由上下文决定」的字段，例如三统一定值帧的「定值信息」：其长度取决于定值序号，无法在 JSON 中写死。

---

## 五、协议适配：三种匹配策略

架构不为任何协议写分支，而是由 `message_matcher.type` 决定匹配路径。

| 策略 | 使用协议 | 标识来源 | 索引键 |
|------|---------|---------|--------|
| `pf_based` | GB/T 27930、三统一 | CAN ID 的 PF（bit16~23） | `pf` |
| `command_number` | 英飞源 | CAN ID 的 command_number（bit16~21，6 位） | `(command_number, role)` |
| `data_field` | 安世博 | 数据域字节（命令类型 + MessageType 半字节） | `command_type` |

### 5.1 英飞源的方向维度

英飞源命令号双向复用：请求与回复同号，靠 `source_addr` 区分。

```
source_addr ∈ 0xF0~0xF8  →  请求（上级监控发出）
source_addr ∈ 0x00~0x3F  →  回复（模块发出）
```

因此索引键是 `(command_number, role)`，`by_can_id` 先解析 `source_addr` 再决定 role，找不到时回退到另一角色。

### 5.2 CAN ID 解析

`QueryEngine.parse_can_id` 按 `can_id_schema.fields` 逐字段掩码提取，输出：

```
{ name: value, name_hex: "0x..", name_label: 枚举标签 }
```

### 5.3 地址与方向显示

- `resolve_address_name(addresses, value)`：先精确匹配 `value`，未命中再按 `range`（如 `"0xA0~0xAE"`）区间匹配。
- 方向文本按匹配策略分支：
  - `data_field`：看 MessageType 低 nibble
  - `command_number`：看 `dest_addr` 是否落在监控段
  - `pf_based`：用 `sa` / `ps` 查地址表

区间匹配是必需的：三统一抓包里模块地址是 `0x20~0x9E` 中的任意值，只做精确匹配会导致方向列大面积空白。

---

## 六、编解码引擎

### 6.1 解码

`decode(msg, data)` 遍历字段，按 `data_type` 分派到 `_unpack_*`，再应用分辨率、偏移、枚举：

```
raw = 读取字节（小端/大端/浮点/BCD/ASCII/位域）
phys = raw * resolution + offset
返回值：标量 或 {"value": raw, "label": 枚举文本}
```

变长字段经 `_eff_len()` 计算有效长度：`len(data) - (byte_start - 1)`。

### 6.2 编码

`encode(msg, params)` 逐字段打包：

1. 枚举文本 → 原始值（`_resolve_enum_value`）
2. 物理量 → 原始值（减 offset、除分辨率）
3. 无符号字段负值 clamp 到 0；有符号字段按补码写入
4. 按字段顺序拼接，不足 `data_length` 补 0

`make_can_id(msg)` 按 `can_id_schema` 位域拼装标识符，未在模板中给出的位使用 `fixed_value` 或 0。

---

## 七、传输层：两套多帧

系统内并存两套互不兼容的多帧机制，由协议决定走哪套。

### 7.1 标准 J1939 TP（GB/T 27930）

| 项 | 内容 |
|----|------|
| 触发 | `msg.tp` 且数据长度 > 6 |
| 分包 | `tp_split`：RTS(0xEC) → CTS(0xEC，SA/PS 互换) → DT(0xEB) |
| 帧格式 | DT 每帧 7 字节数据，首字节为序号，末帧 0xFF 填充 |
| 重组 | `tp_reassemble`，兼容两型：序号型（首帧 byte0=0x01，数据从 byte1 起）与 0x10 标记型 |
| 总长 | 由 RTS 的 byte1~2 给出 |

### 7.2 三统一自定义多帧（`sg_sequence`）

协议在 JSON 中声明，代码按配置启用：

```json
"transport": {
  "type": "sg_sequence",
  "applies_to_pf": [128, 129, 130, 131, 142, 143],
  "max_frames": 32
}
```

**帧结构**（源协议 2.5 节）：

```
帧1      : [序号=01][总帧数 k][长度L][长度H][数据01-04]
帧2..k-1 : [序号][数据 × 7]
末帧     : [序号][数据 × N][校验L][校验H][填充 00]
```

**校验**：`总帧数 + 长度低 + 长度高 + Σ有效数据`，取低 16 位，存放在数据之后的两个字节。

**关键实现点**：

| 方法 | 职责 |
|------|------|
| `sg_first_frame(pf, data)` | 首帧判定。除 `byte0=0x01`、`byte1=k` 外，还要求 `L` 与 `k` 的容量自洽（`L ≤ 4 + 7(k-2) + 5`），以此排除「接口标识恰好为 0x01」的单帧误判 |
| `sg_reassemble(frames)` | 按序号拼接；末帧只取剩余长度，避免把校验码当数据 |
| `sg_verify(frames, assembled)` | 累加和校验，末帧数据长度取下界 0（数据恰好填满中间帧时算出负值） |
| `sg_split(data)` | 编码侧分包，产物与实测抓包逐字节一致 |

**重要事实**：该协议的多帧**沿用报文自身 PF**，不使用 `0xEB/0xEC`。实测抓包中标准 J1939 TP 帧数为 0，因此不能按 TP 路径适配。

### 7.3 两套机制对照

| 维度 | J1939 TP | 三统一 sg_sequence |
|------|----------|---------------------|
| PF | 固定 0xEB/0xEC | 沿用原报文 PF |
| 握手 | RTS / CTS | 无 |
| 首帧 | 序号 1，7 字节数据 | 序号 1 + 总帧数 + 总长，4 字节数据 |
| 校验 | 依赖 J1939 链路层 | 应用层累加和 |
| 触发 | `msg.tp` + 长度 | `transport.type` + `applies_to_pf` |

---

## 八、批量解析

### 8.1 格式识别（按序尝试）

```
.xlsx → openpyxl 读取首行作表头
.csv  → 编码探测（utf-8-sig / utf-8 / gbk）
        × 分隔符探测（comma / tab / semicolon）
        要求至少 2 列（避免单列误接受）
定宽  → GBK 优先，按 2 个以上空格切列
```

### 8.2 列映射

三级优先：hex 关键词列 → 数据关键词列（排除含「长度」的列）→ 数据关键词兜底。用户也可手动指定。

### 8.3 解析主流程

```
逐行：
  ├─ CAN ID 非法 → ERROR 行
  ├─ PF ∈ {0xEB,0xEC} → 归入 TP 组，跳过
  ├─ 命中多帧首帧 → 开新组，跳过
  ├─ 命中活动多帧组且序号匹配 → 追加，跳过
  └─ 常规单帧 → 匹配报文 → 解码 → 结果行

循环结束：
  ├─ TP 组：按 RTS 分组、DT 排序 → tp_reassemble → 解码 → 回插
  └─ 多帧组：序号齐全 → sg_reassemble + sg_verify → 解码 → 回插
```

**多帧归组必须按 CAN ID 分别维护**。实测抓包中两组多帧交错到达（A 首帧 → B 首帧 → A 续帧），单一「当前组」变量会导致前一组被顶掉。

### 8.4 输出

`export()` 生成 xlsx，列含：原始列 + CAN ID + 位域解析 + 数据域 + 报文 + 解析结果。

---

## 九、Web 层

### 9.1 全局状态

```python
state = {
    "protocol": ProtocolDefinition,
    "query":    QueryEngine,
    "codec":    CanCodec,
    "parser":   ExcelParser,
    "protocols": {id: 显示名},
    "parse_results": [...],
}
```

单用户单实例，协议切换即重建 `query/codec/parser`。启动时默认加载 27930。

### 9.2 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/`、`/query`、`/decode`、`/encode`、`/parse` | 均渲染同一 `index.html`（前端 Tab 切换） |
| POST | `/api/protocol/select` | 切换协议 |
| GET | `/api/messages` | 报文列表（带 `ident`） |
| GET | `/api/messages/tree` | 分组树 |
| POST | `/api/decode` | 单帧解码 |
| POST | `/api/encode` | 取报文字段模板 |
| POST | `/api/encode/build` | 按字段值编码出 CAN ID + 数据 + 多帧 |
| GET | `/api/parse/path` | 按路径加载（含 EFS 兜底） |
| POST | `/api/parse/upload` | 上传加载 |
| POST | `/api/parse/run` | 执行解析 |
| GET | `/api/parse/export` | 导出 xlsx |
| GET | `/api/check-update` | 检查新版本 |
| GET | `/api/download-progress` | 下载进度 |
| POST | `/api/do-update` | 下载更新包 |

### 9.3 同步与异步

重操作端点（`do-update` / `parse-run` / `parse-path` / `parse-export`）声明为同步 `def`，由 FastAPI 放入线程池执行，避免阻塞事件循环（否则进度轮询会排队，进度条不动）。

### 9.4 EFS 加密兼容

Windows EFS 目录下的文件用 `shutil.copy2` 复制会被重新加密。实现改用 `cmd /c copy /y`，且目标放在源文件同目录（系统 temp 会触发重新加密）。

---

## 十、前端

单页 `index.html`，三个 Tab：

| Tab | 内容 |
|-----|------|
| 协议查询 | 左侧分组树 + 右侧报文详情 + 内嵌编码表单 |
| 帧解码 | CAN ID + 数据域 → 位域解析 + 字段结果 |
| 批量解析 | 上传/路径、列映射、进度、分页预览、导出 |

**标识列显示策略**（由后端 `_ident_text` 统一生成）：

| 协议类型 | 显示 |
|---------|------|
| PF 类 | `0x10` |
| 命令号类 | `CMD8` |
| 命令类型类 | `0x00` |

消息树对非 27930 协议只显示「名称 + 标识」，不显示报文缩写；27930 保持缩写在前（其缩写是行业通用识别符）。

---

## 十一、自更新

| 项 | 实现 |
|----|------|
| 版本源 | GitHub `littlejazzcat/Protocol_Converter`、Gitee `littlejazzcat/protocol_converter` |
| 比较 | `packaging.version.Version`，兼容 `v` 前缀 |
| 检测 | 手动按钮（双源）+ 启动静默（仅日志） |
| 行为 | 只下载 zip 到 `~/Downloads`，不杀进程、不自动覆盖 |
| 进度 | 64KB 分块写盘，前端轮询 `/api/download-progress` |

---

## 十二、打包

`ProtocolConverter.spec`，PyInstaller onedir：

| 关键点 | 原因 |
|--------|------|
| `excludes=[]` | 曾排除 `http`/`email` 导致 uvicorn 启动失败 |
| `hiddenimports` 显式声明 `services.*`、`models.*` | PyInstaller 不自动收集动态导入 |
| `console=True` | 避免 uvicorn 日志 `isatty` 报错 |
| `sys._MEIPASS` 适配资源路径 | `app.py` 中 `BASE_DIR` 按 frozen 状态切换 |
| `from app import app` 传对象 | 字符串形式在 frozen 环境无法导入 |

产物：目录约 87MB，zip 约 41MB。

---

## 十三、扩展：新增一个协议

1. **写 `data/<protocol_id>.json`**，至少包含 `meta`、`can_id_schema`、`message_matcher`、`messages`。
2. **选匹配策略**：
   - 标识符在 CAN ID 的固定位域 → `pf_based` 或 `command_number`
   - 标识符在数据域 → `data_field`（需给 `match_byte`、`aux_byte`、`aux_nibble`）
3. **注册**：`app.py` 的 `state["protocols"]` 加一项 `id: 显示名`。
4. **过校验**：`loader.validate_integrity()` 会检查字段越界、位域重叠、标识符唯一性、分组引用。
5. **加测试**：在 `tests/test_suite/vectors/` 放编解码向量，并补 golden vector 用例。

若协议有多帧且不走 J1939 TP，在 JSON 中加 `transport` 段，并在 `can_codec` 增加对应实现（参考 `sg_*` 系列）。

---

## 十四、测试体系

| 文件 | 覆盖 |
|------|------|
| `test_integrity.py` | 四协议完整性（越界、重叠、唯一性、引用） |
| `test_schema.py` | JSON 结构合规（必需键、类型、枚举） |
| `test_roundtrip.py` | 编码 → 解码往返一致性 |
| `test_golden_vectors.py` | 真实报文向量的编解码结果 |
| `test_excel_parser.py` | 批量解析（部分用例为 pandas 时代遗留，未随去 pandas 重构） |

当前基线：核心四文件 `168 passed`。

---

## 十五、已知约束

| 项 | 说明 |
|----|------|
| 单用户 | 全局 `state` 是进程级单例，多标签页切换协议会互相影响 |
| 三统一多帧 | 依赖「PF 沿用原报文」这一实测结论；协议文本未明示 |
| 英飞源广播 | 广播命令多数无回复，回复条目仅在点对点/组命令场景成立 |
| 安世博覆盖 | 部分命令（CMD_21/22 线电压等）尚未录入 |
| ExcelParser 测试 | 13 项失败源于旧 pandas 接口，属已知遗留 |
