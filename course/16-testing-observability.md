# 第 16 课 · 测试、调试与可观测性：让后端开发体验追上前端

> 目标：作为一个前端，你会用 Jest/Vitest、React DevTools、Sentry。本课把这三件事映射到 Python 后端：**pytest（≈Vitest）、结构化日志 + 断点调试（≈DevTools/console）、OpenTelemetry/Prometheus（≈Sentry/Grafana）**。学会后你改代码就不怕"跑挂了不知道为啥"。

---

## 16.1 测试：pytest 快速上手（对照 Vitest/Jest）

项目有 170 个测试文件（`tests/`），dev 依赖里配好了 pytest/pytest-asyncio/coverage，还按标记分了 `unit` / `e2e` / `prod_only`。最常用的命令：

```bash
uv run pytest                            # 跑全部
uv run pytest tests/unit -k "graph"      # 只跑路径含 unit、名字含 graph 的
uv run pytest -m unit                    # 只跑 unit 标记
uv run pytest --cov=src                  # 带覆盖率
```

> pytest 的 `-k` 过滤 ≈ Vitest 的 `-t`；`@pytest.mark.unit` ≈ `describe.unit`；`tests/unit/` 目录结构 ≈ 前端的 `__tests__/`。

### 一个测试长什么样（读 `tests/unit/` 里的真实例子）
```python
# 概念示例（项目里 tests/unit/test_services/... 有大量同类真实用例）
import pytest

@pytest.mark.unit
async def test_graph_stream_emits_end(service, fake_run):   # async 测试！
    events = []
    async for event in service.stream(fake_run):
        events.append(event)
    assert events[-1]["type"] == "end"          # 断言：流以 end 收尾
```

几个"前端转后端"必知点：
1. **测试函数就是普通函数**，`assert x == y` 即断言（pytest 会美化失败信息，类似 Vitest 的 diff）。
2. **异步测试直接写 `async def`**：项目 `pyproject.toml` 里 `asyncio_mode = auto`，pytest-asyncio 自动跑，不用手动 `asyncio.run`。
3. **fixture ≈ beforeEach + 依赖注入**：`@pytest.fixture` 提供"服务实例/数据库会话/mock 客户端"，函数参数声明要哪个就注入哪个——和 FastAPI 的 `Depends` 一个味道。
4. **标记**：单元测试要快、不碰真实外部服务（mock LLM/Qdrant/OCR）；外部依赖打上 `e2e`/`prod_only` 标记，CI 分层跑。

### 为什么要 mock 外部服务（关键习惯）
测 `rag_service` 不能真调 PaddleOCR/Embedding（慢、花钱、不可控）。用 `unittest.mock` / `pytest-mock` 把"外部调用"替换成假实现：

```python
def test_ingest(rag, mocker):                     # mocker 是 pytest-mock 注入的
    mocker.patch.object(rag, "_ocr_pdf", return_value="干净的文本")
    mocker.patch.object(rag, "_embed_documents", return_value=[[0.1]*768])
    # ...只测"分块 + 入 Qdrant"这段逻辑，外部全假
```

**前端类比**：就是 `vi.mock('openai')` / Mock Service Worker。mock 原则一样：**边界（网络/时间/随机）才 mock，业务逻辑尽量真跑**。

## 16.2 调试三板斧

### ① 日志（先于 print 学会）
项目用 **structlog** 输出**结构化日志**（JSON/键值对，而不是纯文本），`main.py` 启动时 `setup_logging()`。代码里统一 `logger = structlog.getLogger(__name__)`，然后：

```python
logger.info("run_started", run_id=run_id, status="pending")   # 键值对！可直接被采集
logger.error("db_down", error=str(e), hint="check docker compose ps")
logger.exception("unexpected", exc_info=True)                 # 带完整堆栈
```

> 前端直觉：**console.log 升级成"可搜索、可过滤、可被日志平台采集的键值对"**。看日志用 `--reload` 终端即可；字段越多越好查（`grep run_id=xxx`）。

### ② Python 调试器（≈ 前端的 breakpoint）
VSCode 里：
- 在 `.py` 行号左侧点红点 → 打开 `.py` 文件按 `F5`（首次选 Python Debugger，配置用 `.venv` 解释器）→ 命中断点后看变量、步进（F10/F11），**体验与调试 TS 完全一致**。
- 快速版：代码里写 `breakpoint()`（内置断点），跑到即停。
- 注意：`--reload` 模式下调试器会跟随重载重启，调试复杂问题时建议**不带 --reload 单独起一个调试会话**。

### ③ 测试失败信息
pytest 失败会打印**实际值 vs 期望值**的 diff + 出错的断言行——先读它，别瞎猜。配合 `-x`（失败即停）与 `--pdb`（失败进调试器）食用更佳。

## 16.3 可观测性：OpenTelemetry + Prometheus（≈ Sentry + 监控大盘）

目录 `src/observability/` 封装了：
- **OpenTelemetry**（`setup_observability`）：给 LangChain/HTTP/DB 调用自动生成 **trace（追踪）**——一次 run 从 API 到 LLM 的完整调用链，每段耗时一目了然。导出目标（`.env` 的 `OTEL_TARGETS`，逗号分隔）：`LANGFUSE`（LLM 可观测平台）/ `PHOENIX` / OTLP。
- **Prometheus 指标**（`src/observability/metrics.py` + `prometheus-fastapi-instrumentator`）：HTTP 请求数/延迟/错误率等**指标**，`main.py` 里 `setup_prometheus_metrics(application)` 挂好，暴露 `/metrics` 给 Prometheus 抓取。
- 配套中间件：`asgi-correlation-id` 给每个请求发 `X-Request-ID`，日志/trace 都能按它串联（`src/middleware/` 的结构化日志中间件）。

> 前端对照：**trace ≈ 一次请求的 Performance 火焰图；metrics ≈ Sentry 的请求量/错误率面板；correlation id ≈ 你在 console 里按 requestId 过滤日志**。本阶段你只需要：知道入口在哪、能开一个 trace 后端（如 Langfuse 云或本地 Phoenix）把 `OTEL_TARGETS` 配上、看到一次 run 的 span 树即可。

## 16.4 动手实验
1. 跑一次全量单测，体验 pytest 输出：`uv run pytest tests/unit -x -q`（若个别用例需要外部服务会 skip/失败，属正常，先看懂输出格式）。
2. 打开任意 `tests/unit/test_services/` 测试文件，找出一个 async 测试 + 一个 fixture + 一个 mocker 用法，各抄一段并注释。
3. 在 `src/agents/react_agent/graph.py` 的 `call_model` 里临时加一行 `logger.info("debug_here", msgs=len(state.messages))`，重启后跑一次对话，观察结构化日志输出（记得用完删掉）。
4. 用 VSCode 断点调试：在 `call_model` 设断点，F5 启动 debug 配置，发一次 run，观察 `state` 与 `runtime.context` 的运行时值——**亲眼看一次"运行时注入"**。
5. （进阶）把 `OTEL_TARGETS=LANGFUSE` 配上（需要 Langfuse 的 key），跑一次对话，去 Langfuse 看这条 run 的 trace 树：LLM 调用耗时、token 数、工具调用。

## 16.5 常见坑
- **测试里 import 报错**：确保在仓库根跑 `uv run pytest`（用 .venv 环境）。
- **`asyncio_mode = auto` 之外混用 pytest-asyncio 装饰器**：项目已配 auto，测试别再手写 `@pytest.mark.asyncio`，避免重复。
- **mock 没生效**：要 patch **使用处**（`rag_service` 模块里的名字），不是定义处——和 `vi.mock` 的模块路径同理。
- **日志中文乱码/JSON 缩进**：structlog 在终端用 `console` 渲染器友好显示，看原始 JSON 可关掉美化。
- **debug 模式下改 .env 不触发 reload**：手动重启。

## 自测题
1. pytest 的 fixture 解决了什么问题？和 FastAPI 的 Depends 有什么相似？
2. 为什么测外部服务要 mock？mock 的原则是什么？
3. structlog 的"键值对日志"比 print 好在哪？
4. trace 和 metrics 的区别？（一次请求的完整链路 vs 一段时间内的统计数字）
5. correlation id 有什么用？

**下一课**：[17-capstone.md](17-capstone.md) —— 毕业项目：从 0 造一个属于你自己的智能体。
