# SheetKit · 表格效率助手

面向公司内部使用 WPS Office / Microsoft Excel 的普通员工的 **Windows 本地桌面工具**。
提供三个高频功能：**Excel 差异对比**、**Excel 批量合并**、**Excel 数据清洗**。

所有文件只在本机处理：不启动 HTTP 服务、不开放网络端口、不上传任何数据、不保存处理过的表格内容。

| 表格对比 | 批量合并 | 数据清洗 |
| --- | --- | --- |
| ![表格对比](docs/screenshot-compare.png) | ![批量合并](docs/screenshot-merge.png) | ![数据清洗](docs/screenshot-clean.png) |

---

## 1. 快速开始

### 1.1 直接使用（什么都不用装）

双击 **`dist\SheetKit.exe`** 就能运行。

- 只需要 Windows 10/11 和 **WebView2 Runtime**（Windows 11 自带；Windows 10 若缺失请安装微软 Evergreen Runtime）。
- **不需要**安装 Python、Node.js，也**不需要**部署任何服务器。
- 这是一个 12.8 MB 的独立文件，可以单独拷到别的电脑、U 盘或共享盘直接用。
- 所有处理都在本机完成，不联网、不上传。

### 1.2 从源码运行（开发环境）

```bat
:: 1. 准备 Python 虚拟环境
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt

:: 2. 构建前端（产出单个 HTML 文件）
cd frontend
npm install
npm run build
cd ..

:: 3. 启动
.venv\Scripts\python.exe python\main.py
```

### 1.3 打包成 Windows 程序

```bat
build.bat
```

产物是**单个可执行文件** `dist\SheetKit.exe`，双击即可运行，可直接拷到任何一台 Windows 电脑上。
详见 [§7 打包](#7-打包)。

### 1.4 运行测试

```bat
.venv\Scripts\python.exe -m pytest -q
```

---

## 2. 功能说明

### 2.1 表格对比

按**业务唯一键**匹配两个版本的表格，而不是按行号逐行比较。

- 支持单字段唯一键，也支持多字段组合键（如 `物料编码 + 规格型号`）。
- 识别四类结果：**新增**、**删除**、**修改**、**未变化**。
- 两个文件行顺序不同但数据相同 → 判定为「无变化」。
- 匹配字段为空或重复的行**不参与匹配**，而是列入「异常记录」；
  并且对侧出现重复时，不会把本侧的行断言为「新增/删除」——因为这种判定无法验证。
- 两个文件的列不一致时按**列名**对应，并单独列出「仅旧版存在 / 仅新版存在」的字段。
- 可选「忽略文本首尾空格」「忽略大小写」。
- 可指定数量、价格等字段使用**十进制数值比较**并设置容差；
  某一侧不是数字时回退为文本比较，并在结果中标注「数值比较失败，按文本比较」。
- 结果分四个分页表格展示，可就地筛选；导出为 `对比摘要 / 新增记录 / 删除记录 / 修改明细 / 异常记录` 五个工作表，按变更类型着色。

### 2.2 批量合并

多个结构相同或相近的表格**纵向**汇总为一个文件。

- 字段按**列名**对应，不按位置硬拼。
- 支持手动字段映射，例如 `出货日期 → 发货日期`、`物料编号 → 物料编码`。
- 字段名称不一致时**不会**擅自合并含义不同的列，而是保留为两列并提示；
  若手动映射造成冲突（例如两列映射到同一目标），会直接报错并列出冲突项。
- 默认保留全部数据，**不做自动去重**。
- 缺失字段保留空值。
- 结果包含 `来源文件 / 来源工作表 / 原始行号` 三列，便于回溯。
- 结果可分页浏览与筛选；导出为 `合并结果 / 合并摘要`（摘要列出各来源文件记录数与最终数据量）。

### 2.3 数据清洗

勾选式规则，应用于选定的字段：

| 规则 | 行为 |
| --- | --- |
| 删除完全空白行 | 统计并移除空行 |
| 清理首尾空格 | 只处理选定的文本列，且只动首尾 |
| 检测重复记录 | 按一个或多个字段判定，**默认只标记** |
| 标记必填字段缺失 | 列出缺失的字段名 |
| 检测日期/数字格式异常 | 识别无法解析的日期、文本形式存储的数字等 |

**重复数据默认只标记，不删除。** 选择「删除重复项（保留首次出现）」或「删除整组重复数据」时：

1. 先计算并展示影响预览（重复组数、涉及行数、将被删除的行数、删除后剩余行数）；
2. 用户在确认对话框中再次确认；
3. 确认后才执行删除。

任何情况下都不会静默删除疑似重复数据，也不会修改原始文件。

结果可分页浏览与筛选；导出为 `清洗结果 / 重复数据 / 异常数据 / 清洗摘要` 四个工作表。

---

## 3. 通用文件处理

### 3.1 结果查看

- 结果明细按分页展示，并可**在结果中筛选**（匹配任意一列即可，忽略大小写）；
  筛选显示「筛选后 / 总数」，不会把数据藏起来。
- 处理期间界面显示进度条与当前阶段，**不阻塞界面**；随时可以点「取消」中止本次处理。
  取消不会留下半成品文件（导出先写临时文件再原子替换）。
- 长任务在后台线程执行，界面始终可操作。

### 3.2 文件读取

- 支持 `.xlsx`、`.xlsm`、`.csv`。
- 可选择工作表、设置表头所在行。
- 文件预览显示前 50 行，支持分页。
- **不做类型推断**：文本 `00123` 不会被读成数字 123，19 位订单编号不会变成浮点数；
  混合列会保留每个单元格原本的类型。
- **CSV 全部按文本读取**，以保留前导零与长数字。
- CSV 编码自动识别：BOM → UTF-8 → GB18030 → Big5 → CP1252。
  识别用「乱码评分」而非固定顺序——因为每一段合法的 Big5 字节序列同时也是合法的 GB18030，
  固定顺序永远选不到 Big5；GB18030 会把无法映射的字节放进 Unicode 私用区，据此可以正确区分。
- **公式不计算**：有缓存结果时使用其上次保存的计算值，没有缓存结果时按空值处理并明确提示。
- 宏文件（`.xlsm`）只读取数据，**不会执行任何宏**，并给出提示。

---

## 4. 安全与隐私

| 要求 | 实现 |
| --- | --- |
| 不覆盖原始文件 | 导出前比对输入路径，命中即拒绝（`E_OUTPUT_CONFLICT`） |
| 最小权限 | 前端只能调用固定的 10 个桥接方法，无法执行任意命令；Python 侧只接受受校验的参数 |
| 只在本地处理 | 界面通过 WebView2 的 `NavigateToString` 加载单个 HTML 文件，**不启动本地 HTTP 服务、不开放端口** |
| 不留数据副本 | 处理结果只保存在内存中（上限 8 份，LRU 淘汰），关闭窗口即清空；不落盘、不建数据库 |
| 临时文件清理 | 导出先写同目录临时文件再原子替换；失败立即删除；正常退出时 `atexit` 兜底清理；超过 24 小时的残留会在下次导出同一目录时被清除 |
| 公式注入防护 | 以 `=` 开头的文本强制写成字符串类型（`data_type='s'`），不会被 Excel 当成公式执行 |
| 超长数字保护 | 超过 15 位有效数字的整数按文本写出，避免 Excel 静默舍入 |
| 不执行宏 | 只用 openpyxl 读取数据，从不加载 VBA |
| 日志不含业务数据 | 只记录异常类型，不记录单元格内容与文件内容 |

---

## 5. 项目结构

```text
SheetKit/
├─ frontend/                  Vue 3 + TypeScript + Vite + Tailwind CSS
│  ├─ src/
│  │  ├─ components/          AppSidebar / FilePicker / DataTable / ConfirmDialog …
│  │  ├─ composables/         useFileSlot / useTheme / useToast / useProgress / useDropTarget
│  │  ├─ services/bridge.ts   与 Python 桥接的类型化封装
│  │  ├─ views/               Home / Compare / Merge / Clean
│  │  ├─ App.vue  main.ts  router.ts
│  │  └─ styles/main.css      设计令牌（Frappe 视觉语言）
│  ├─ vite.config.ts          单文件 HTML 构建插件
│  └─ tailwind.config.js
├─ python/
│  ├─ main.py                 入口
│  └─ sheetkit/
│     ├─ reader.py            通用读取（xlsx / csv，类型保真，公式识别）
│     ├─ validators.py        参数与路径校验
│     ├─ values.py            取值规则（文本化、数字解析、日期解析、表头规范化）
│     ├─ compare.py           差异对比引擎
│     ├─ merge.py             批量合并引擎
│     ├─ clean.py             数据清洗引擎
│     ├─ exporter.py          安全导出（公式注入防护、长数字保护、原子写入）
│     ├─ reports.py           报表版式
│     ├─ results.py           内存结果仓库（分页）
│     ├─ api.py               桌面桥接
│     ├─ shell.py             pywebview 窗口、拖放接线、退出清理
│     └─ webui/index.html     构建产物（单文件）
├─ tests/                     pytest 测试（279 项）
├─ tools/                     基准测试、端到端探针、壳层能力探针
├─ SheetKit.spec              PyInstaller 配置
├─ build.bat                  一键构建
├─ requirements.txt
└─ README.md
```

---

## 6. 技术选型说明

### 6.1 为什么是 pywebview 而不是 Tauri 2

任务书给出的首选栈是 Tauri 2。**本机没有安装 Rust/Cargo，也没有 MSVC Build Tools（Visual Studio）**，
Tauri 2 无法编译；补齐工具链需要约 4–8 GB 下载与管理员权限。

在征得同意后改用 **pywebview 6.2.1 + WebView2**（EdgeChromium 后端，经 pythonnet 3.2.1 驱动）。
两者都是「本地 Web 界面 + 系统 WebView」的桌面容器，对本项目而言能力等价。

### 6.2 为什么没有使用 frappe-ui 作为组件库

调研结论：**frappe-ui 1.1.0 不适合作为独立组件库引入**。它的依赖里包含
`socket.io-client`、`tiptap`、完整的 CodeMirror 系列、`echarts`，并且把 `vitepress` / `shiki` 作为 peer 依赖——
这些都假定背后有一个 Frappe 服务端。任务书本身也只要求「参考其 UI 设计」，因此本项目**只复刻 Frappe 的视觉语言**
（左侧导航、顶部标题栏、卡片、表格、留白与圆角体系），用 Tailwind CSS 令牌实现，
不引入任何服务端耦合的组件。图标使用 Frappe 官方同款图标库 `lucide-vue-next`。

### 6.3 为什么没有开本地 HTTP 服务

pywebview 对本地文件 URL **总会**启动内置 HTTP 服务器（`http_server=False` 会被忽略），
这与「不开放网络端口」的硬性要求冲突。

解决办法：前端构建成**单个自包含 HTML 文件**，通过 WebView2 的 `NavigateToString` 加载。
经实测（`tools/app_probe.py`），此时 `location.protocol` 为 `about:`，**没有监听任何端口**。
构建插件会强制校验产物体积不超过 2 MB 的 `NavigateToString` 上限（实际约 193 KiB）。

### 6.4 为什么没有使用 pandas

任务书把 pandas 列为 Excel 处理栈的一员，本项目**有意不依赖它**。

pandas 在读取时会推断 dtype，这会把文本 `00123` 变成数字 123、把 19 位订单编号变成浮点数——
恰好是任务书明令禁止的行为（「不得在用户未确认时擅自转换业务字段的数据类型」）。
openpyxl 能拿到单元格原本的类型，因此引擎直接用 openpyxl 读取，
保证「物料编码 / 订单编号 / 电话号码 / 长数字」原样保留。

如果以后需要 pandas 做导出侧的表格重塑，再把它加回 `requirements.txt` 即可，但不要让它进入读取路径。

### 6.5 其它参考项目

| 项目 | 借鉴点 |
| --- | --- |
| [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) | 现代桌面观感；未直接采用（WebView 方案更适合数据密集型表格界面） |
| [ExcelMerge](https://github.com/skanmera/ExcelMerge) | 「按列名而非列位置合并」的思路 |
| [Excel-Branch-Merger](https://github.com/AlekseiRbo/Excel-Branch-Merger) | 多文件汇总时的来源可追溯设计（本项目落为「来源文件/来源工作表/原始行号」三列） |

本项目**未复制任何第三方源码**，全部逻辑为独立实现。

---

## 7. 打包

```bat
build.bat
```

流程：创建虚拟环境 → 安装 Python 依赖 → `npm install` → `npm run build`（产出单文件 HTML）→ PyInstaller 打包。

- 产物：**`dist\SheetKit.exe`（单个文件）**，双击即可运行
- 体积：**12.8 MB 单个文件**（内含 Python 运行时、openpyxl、pythonnet 与整个界面）
- 目标机器需要 **WebView2 Runtime**（Windows 11 自带；Windows 10 可从微软官网安装 Evergreen Runtime）
- 目标机器**不需要**安装 Python、Node.js 或任何服务器
- 单文件版每次启动会先把内置资源解压到临时目录，因此启动比「目录版」略慢

---

## 8. 性能实测

在普通办公场景的目标规模上实测（`tools/benchmark.py`，8 列 × 10,000 行）：

<!--PERF-->

| 工作负载 | 耗时 | 峰值内存 | 结果 |
| --- | ---: | ---: | --- |
| 读取 1 万行文件 | 0.84 s | 6.1 MiB | 10,000 行 |
| 对比两个 1 万行文件 | 2.13 s | 12.2 MiB | 新增 120 / 删除 120 / 修改 0 |
| 合并 5 个文件（合计 5 万行） | 4.72 s | 31.3 MiB | 50,000 行 × 11 列 |
| 清洗 1 万行文件 | 1.01 s | 8.1 MiB | 10,000 行 |
| 导出对比报告 | 0.18 s | — | 0.02 MiB |
| 导出合并报告（5 万行） | 6.01 s | — | 2.83 MiB |
| 导出清洗报告 | 1.25 s | — | 0.60 MiB |

源码体积参考：单个 1 万行 × 8 列的工作簿约 0.45 MiB。

启动速度（窗口可见，`tools/startup_probe.py`）：

| 启动方式 | 耗时 |
| --- | ---: |
| 源码运行 | 1.39 s |
| 打包后运行（单文件版） | 1.40 s |

打包体积：`dist\SheetKit.exe` 12.8 MB（单个文件）。

> 说明：以上为**本机实测值**，用于说明量级，不构成性能承诺。
> 「峰值内存」为 Python 层 `tracemalloc` 统计值；计时与内存分两轮测量，
> 避免 `tracemalloc` 的分配追踪把时间放大多倍。

---

## 9. 测试

```bat
.venv\Scripts\python.exe -m pytest -q
```

覆盖范围（`tests/`，共 295 项）：

| 文件 | 覆盖内容 |
| --- | --- |
| `test_values.py` | 取值规则：空值判定、文本化、数字解析、日期解析、表头去重 |
| `test_reader.py` | 格式、工作表、表头行、前导零、长数字、公式（带/不带缓存）、CSV 编码与分隔符、宏文件、损坏文件、文件被占用、不支持的格式 |
| `test_compare.py` | 行顺序变化、新增/删除/修改、组合键、重复主键、空主键、不同列顺序、缺失字段、忽略空格/大小写、数值比较与容差、数值解析失败回退 |
| `test_merge.py` | 按名对齐、按位置不对齐、字段映射、映射冲突、缺失字段留空、不自动去重、来源追溯列、表头偏移、工作表选择、跳过文件 |
| `test_clean.py` | 空白行、空格清理、重复标记、组合键判重、重复删除的确认闸门、必填缺失、日期/数字异常、前导零不被转换 |
| `test_export.py` | 拒绝覆盖输入、公式注入防护、超长数字保护、原子写入与失败清理、目标被占用、工作表命名、报表版式 |
| `test_api.py` | 桥接协议、错误信封、分页与筛选、影响预览、导出、结果释放与清理 |
| `test_cancel.py` | 取消正在运行的任务、结果表筛选 |

端到端探针：

```bat
.venv\Scripts\python.exe tools\app_probe.py
```

真实启动窗口、遍历四个页面、切换主题、通过桥接跑一次真实对比，并断言没有 JS 错误。

---

## 10. 已知限制

1. **不支持 `.xls` / `.xlsb` / WPS 专有 `.et`**：请先在 Excel/WPS 中另存为 `.xlsx`。
   程序会明确提示，不会假装能读。
2. **不计算公式**：只使用 Excel/WPS 上次保存的缓存结果；没有缓存结果的公式按空值处理并提示。
3. **不处理合并单元格**：合并单元格在读取时按其左上角的值展开。
4. **只做纵向合并**：第一版不做跨表关联查询。
5. **拖放依赖系统级文件拖放**：从资源管理器拖入窗口可拿到真实路径；
   从浏览器或压缩包内部拖入的对象不是磁盘文件，会被忽略。
6. **CSV 编码识别是启发式的**：极少见的编码可能识别错误，此时界面会给出「无法识别 CSV 编码」的提示。
7. **硬杀进程可能残留 `.sheetkit-*.tmp`**：正常退出与异常都会清理；被任务管理器强杀时，
   残留文件会在下次向同一目录导出时（超过 24 小时）被清除。
8. **打包体积约 26 MB**：为的是免安装 Python；如需更小体积可自行裁剪依赖。
9. **界面语言仅中文**，暂不支持国际化。

---

## 11. 后续可考虑（**不在 v0.1 范围内**）

以下想法有价值，但第一版**没有实现**，特此记录：

- 差异对比支持「忽略指定列」与「只比较指定列」的快捷预设；
- 合并时支持按日期字段拆分输出多个文件；
- 清洗规则支持自定义正则与自定义日期格式；
- 记住上次的表头行与匹配字段（需持久化设置文件）；
- 生成可分享的对比摘要图片；
- WPS 插件形态。

---

## 12. 许可证

本项目代码版权归项目所有者。依赖的第三方库各自遵循其许可证：

| 依赖 | 许可证 |
| --- | --- |
| [pywebview](https://github.com/r0x0r/pywebview) | BSD-3-Clause |
| [pythonnet](https://github.com/pythonnet/pythonnet) | MIT |
| [openpyxl](https://github.com/theorchard/openpyxl) | MIT |
| [Vue](https://github.com/vuejs/core) | MIT |
| [Vite](https://github.com/vitejs/vite) | MIT |
| [Tailwind CSS](https://github.com/tailwindlabs/tailwindcss) | MIT |
| [lucide](https://github.com/lucide-icons/lucide) | ISC |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | GPL-2.0-or-later（含例外条款，随打包工具使用） |
