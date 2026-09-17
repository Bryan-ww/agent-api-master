# 第 02D 课 · 调试：把"猜"变成"看见"

> 目标：后端开发 80% 的时间在调试。前端你有一套成熟工具链（console.log → DevTools 断点 → Sentry），后端是**一模一样**的四层，只是工具名字不同。
> 这一课把四层全部打通，并给你一个"照着做就能定位问题"的流程。
> 前置：第 01、02、02A、02B 课。

---

## 2D.1 调试的四个层次（从便宜到贵，先用便宜的）

| 层 | 手段 | 成本 | 前端对照 |
|---|---|---|---|
| ① | **读报错堆栈** | 几乎免费 | 读浏览器控制台报错 |
| ② | **打日志** | 很低 | `console.log` / 结构化日志 |
| ③ | **断点调试器** | 中 | DevTools Sources 面板打断点 |
| ④ | 可观测性（trace/metrics） | 高（要配基础设施） | Sentry / Lighthouse / Performance 面板 |

**核心原则：能用第①层解决的，绝不上第③层。** 90% 的 bug 靠读报错就能定位，新手最常见的问题不是"不会调试"，而是"报错都没读完就开始改代码"。

## 2D.2 第一层：读懂 Traceback（本课最重要的技能）

Python 的报错叫 **Traceback（回溯）**，它把"从入口到出错点"的完整调用链打给你看：

```
Traceback (most recent call last):
  File "C:\...\uvicorn\main.py", line 620, in main
    ...
  File "D:\XJT-Bryan\...\main.py", line 143, in <module>
    app = create_app()
  File "D:\XJT-Bryan\...\src\core\app_loader.py", line 61, in create_app
    raise RuntimeError("Could not connect to PostgreSQL") from exc
RuntimeError: Could not connect to PostgreSQL
```

### 读法：三步，别从第一行开始读

1. **先读最后一行** —— 那是"什么错了"。这里是 `RuntimeError: Could not connect to PostgreSQL`。**你已经知道答案了：连不上数据库。**
2. **再从下往上找第一个属于"你的项目"的 File 行** —— 也就是跳过 `uvicorn\main.py` 这种第三方库，找到 `src\core\app_loader.py:61`。**这就是出事的地点。**
3. **看它的上一行代码** —— `raise RuntimeError(...)`，说明这行是"主动抛出"的，真正的问题在更早（`from exc` 说明它包装了底层异常）。

> **关键技巧**：只看路径里带 `D:\XJT-Bryan\...` 的 File 行。`site-packages`、`uvicorn`、`langgraph` 里的行先忽略——那通常是"别人调用你的代码"或者"你把错值传给了库"。

**`from exc` 是什么？** 表示"这个异常是从另一个异常包装来的"，原始异常会在上面几行显示。这叫异常链（exception chaining），项目里到处用（`raise ... from exc`）。

## 2D.3 常见异常对照表（看到名字就知道往哪查）

| 异常 | 典型原因 | 前端对照 / 怎么修 |
|---|---|---|
| `SyntaxError` | 语法错。看它用 `^` 指的位置 | 少冒号、括号不配对 |
| `IndentationError` | 缩进错（混了 Tab/空格） | 用 VSCode 的 Ruff 自动格式化 |
| `NameError` | 变量没定义或拼错 | JS 里 `ReferenceError` |
| `TypeError` | 类型不对，如 `None` 上取属性 | 最常见：函数返回 None 你却当 dict 用 |
| `KeyError` | `d["k"]` 取了不存在的键 | **JS 返回 undefined，Python 直接炸**（02A） |
| `IndexError` | 列表越界，如 `arr[10]` | |
| `AttributeError` | 对象没这个属性 | `'NoneType' object has no attribute 'xxx'` = 前面某步返回了 None |
| `ValueError` | 值不合法，如 `int("abc")` | 类型对但内容不对 |
| `ModuleNotFoundError` | 没装依赖 / **没选对解释器** | 见 01 课 1.5 节 |
| `FileNotFoundError` | 路径不存在 | |
| `UnicodeDecodeError` | 编码问题 | 加 `encoding="utf-8"`（02B） |
| `ConnectionRefusedError` | 目标服务没起来 | **本项目最常见：Docker 容器没起** |
| `asyncio.TimeoutError` | 异步任务超时 | 检查下游是否挂了 |
| `RuntimeError` | 通用运行时错误 | 看它自己写的中文/英文提示 |

**最有价值的三个**：`KeyError`（取键）、`AttributeError` + `NoneType`（空值）、`ConnectionRefusedError`（服务没起）。项目里 80% 的报错落在这三个。

## 2D.4 第二层：日志（比 print 强在哪）

### 先看项目怎么用

```python
import structlog
logger = structlog.get_logger(__name__)      # src/utils/paddle_ocr.py:10

logger.info("run_started", run_id=run_id)                                   # 正常流程
logger.warning("paddle_json_parse_fallback_to_text", offset=index)          # 异常但可继续
logger.error("连接数据库失败", error=str(exc))                              # 出错
logger.exception("未知错误")                                                 # ★ 自动带上完整堆栈
```

**格式**：`logger.级别("事件名", 字段=值, 字段=值)`。第一个参数是**事件名（常量字符串）**，后面全是关键字参数——这是结构化日志，机器能按字段检索。

### 五个级别，什么时候用哪个

| 级别 | 用在哪 | 生产环境会输出吗 |
|---|---|---|
| `debug` | 开发时的细节（循环里的值） | 不会（默认级别是 INFO） |
| `info` | 关键业务节点（run 开始/结束） | 会 |
| `warning` | 异常但已兜底（降级、重试） | 会 |
| `error` | 出错了，但服务还能跑 | 会 |
| `exception` | **只在 `except` 块里用**，等价 `error` + 自动堆栈 | 会 |

**最常见的错误用法**：

```python
except Exception as e:
    logger.error("出错了", error=str(e))     # ⚠️ 只有一句话，堆栈全丢了
    logger.exception("出错了")               # ✅ 自动带完整 traceback
```

> **规则**：在 `except` 块里，**永远用 `logger.exception`**。它会把当前 traceback 完整打出来。用 `logger.error` 只打一行消息，你后面查问题会想哭。

### 怎么控制日志详细程度

`src/settings.py:106`：`LOG_LEVEL: UpperStr = "INFO"`。所以你在 `.env` 里写：

```ini
LOG_LEVEL=DEBUG        # 看最详细的日志
```

**这就是"调日志级别"的标准做法**——不用改代码，改配置重启即可。

### print 为什么不够

| | `print` | `logger` |
|---|---|---|
| 级别控制 | 无 | 有（改配置就能关） |
| 带时间戳 | 无 | 有 |
| 带文件名行号 | 无 | 有（项目配了 CallsiteParameterAdder） |
| 带请求 ID | 无 | 有（项目配了 merge_contextvars） |
| 机器可检索 | 否 | 是（JSON 格式） |
| 错误走 stderr | 要手写 | 自动 |

**练手建议**：调试时随便 `print` 没问题；但**提交代码前把 print 换成 logger**。

## 2D.5 第三层：VSCode 调试器（你的舒适区，几乎和前端一样）

这是前端工程师最大的优势区——你已经在浏览器里用过 DevTools 断点，VSCode 的调试器**操作逻辑完全一样**，只是对象从 JS 变成了 Python。

### 前置：解释器必须是 `.venv`

01 课 1.5 节那步：`Ctrl+Shift+P` → `Python: Select Interpreter` → 选 `./.venv`。**没选对的话，调试器根本找不到依赖。**

### 创建 `.vscode/launch.json`

在项目根建 `.vscode/launch.json`：

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "FastAPI (uvicorn)",
      "type": "debugpy",
      "request": "launch",
      "module": "uvicorn",
      "args": ["main:app", "--port", "2026"],
      "cwd": "${workspaceFolder}",
      "console": "integratedTerminal",
      "justMyCode": false
    },
    {
      "name": "pytest (调试当前文件)",
      "type": "debugpy",
      "request": "launch",
      "module": "pytest",
      "args": ["${file}", "-v", "-s"],
      "cwd": "${workspaceFolder}",
      "console": "integratedTerminal"
    }
  ]
}
```

配置项解释：

| 字段 | 作用 |
|---|---|
| `"type": "debugpy"` | 新版 Python 扩展的调试器类型。**如果报错说不认识，改成 `"python"`** |
| `"module": "uvicorn"` | 用 `python -m uvicorn` 启动，而不是直接跑 `main.py` |
| `"args"` | 传给 uvicorn 的参数 |
| `"cwd": "${workspaceFolder}"` | 工作目录设为仓库根，**否则 `.env` 和 `aegra.json` 找不到** |
| `"justMyCode": false` | **允许步入第三方库代码**。读 LangGraph 内部逻辑时很有用（第 08 课起） |
| `"console": "integratedTerminal"` | 输出到集成终端，日志有颜色、能交互 |

### ⚠️ 一个必踩的坑：调试时不要用 `--reload`

01 课启动服务用的是 `uvicorn main:app --port 2026 --reload`。`--reload` 会**另起一个子进程**来跑应用，导致**断点绑不上**（你打断点了，但代码在另一个进程里跑）。

> **调试时去掉 `--reload`**，改完代码手动重启。上面的 `launch.json` 已经帮你处理了。

### 三种断点（前两种前端也有，第三种前端没有）

| 类型 | 怎么设 | 用途 |
|---|---|---|
| **普通断点** | 行号左侧点一下 | 每次到这行都停 |
| **条件断点** | 右键 → `Add Conditional Breakpoint` → 写条件如 `run_id == "abc"` | **只在满足条件时停** ★ 调试循环/多请求必备 |
| **日志点** | 右键 → `Add Logpoint` → 写 `run_id={run_id}` | **不暂停，只打印**，等于"不用改代码的 console.log" ★★ |

**日志点是本课最实用的技巧**：你想看某个变量的值，但不想改代码、也不想中断请求流——用日志点。它甚至支持 `{变量名}` 插值。

### 调试面板和快捷键（和 DevTools 几乎一一对应）

| VSCode | 作用 | DevTools 对应 |
|---|---|---|
| **VARIABLES** | 当前作用域所有变量 | Scope 面板 |
| **WATCH** | 盯住某个表达式 | Watch 面板 |
| **CALL STACK** | 完整调用栈，点哪层跳哪层 | Call Stack |
| `F5` | 继续运行 | Resume |
| `F10` | 步过（不进入函数） | Step over |
| `F11` | 步入（进入函数） | Step into |
| `Shift+F11` | 步出 | Step out |

**CALL STACK 是后端调试的杀手锏**：一层层往上点，你能看到"请求是从哪个 API 路由进来的"——这在有中间件、依赖注入的 FastAPI 里非常有用。

### 调试异步代码和 SSE

- **异步函数可以正常打断点**，VSCode 支持。
- 想调试流式输出（第 14 课），在 `src/services/graph_streaming.py` 里 `yield` 那一行打断点，然后观察每次 `yield` 时变量的变化。因为 `yield` 会暂停函数，断点会**反复命中**——这正是理解生成器的好机会。
- 想调试测试：用上面 `pytest (调试当前文件)` 配置，打开某个测试文件按 F5。

## 2D.6 第四层：`breakpoint()` 与 pdb（没有 GUI 时的救命稻草）

```python
def process(data):
    breakpoint()        # ← 执行到这里会【停住】并进入交互式调试器
    return data["x"]
```

跑起来后终端会变成 `(Pdb)` 提示符，常用命令：

| 命令 | 作用 |
|---|---|
| `n` (next) | 下一行（步过） |
| `s` (step) | 步入函数 |
| `c` (continue) | 继续运行到下一个断点 |
| `p 变量名` | 打印变量的值 ★ |
| `pp 变量` | 漂亮打印（结构化数据用这个） |
| `l` (list) | 显示当前代码上下文 |
| `w` (where) | 显示调用栈 |
| `q` (quit) | 退出 |

**什么时候用 pdb 而不是 VSCode 调试器？**

- 代码跑在 **Docker 容器里**（`docker exec -it aegra-api bash` 进去后没法开 VSCode 调试器）
- 跑在**远程服务器**上
- 快速验证（不用配 launch.json）

> ⚠️ **两个警告**：① `breakpoint()` 会**阻塞整个服务**，多人共用的环境千万别留；② **提交代码前一定删掉**，否则线上会挂死。

## 2D.7 一次完整的真实调试（把四层串起来）

**场景**：按 01 课启动服务，终端报 `Could not connect to PostgreSQL`，或者 `/docs` 打开报 500。

### 步骤 1：读报错（第①层，30 秒）

看 Traceback 最后一行 → `RuntimeError: Could not connect to PostgreSQL`。
**结论**：应用连不上数据库。**还没改任何代码，方向已经明确了。**

### 步骤 2：验证假设，而不是改代码（关键！）

报错说的是"连不上"。可能原因有三种，逐个验证：

```bash
# 假设 A：容器没起来 → 验证
docker compose ps
#   期望看到 postgres / redis / qdrant 都是 running (healthy)

# 假设 B：配置不对（账号密码/端口）→ 验证
cat .env | grep POSTGRES
#   期望和 docker-compose.yml 里的 postgres/postgres/5432/aegra-api 一致

# 假设 C：端口被别的程序占了 → 验证
netstat -ano | findstr :5432
```

**这一步是新手和老手的最大区别**：新手看到"连不上"就去翻数据库代码；老手先用 30 秒排除掉 90% 的可能。

### 步骤 3：如果假设 A 成立

```bash
docker compose up -d
docker compose ps            # 等 healthy
```
重启服务，问题解决。**你一行代码都没改。**

### 步骤 4：如果容器是 healthy 但还连不上（上第③层）

说明是**配置或代码**的问题。在 `.vscode/launch.json` 里用 `FastAPI (uvicorn)` 启动，在 `src/core/app_loader.py` 抛异常那一行打断点，看两个值：

- **WATCH 面板加**：`settings.db.database_url` → 打印出实际用的连接串
- **VARIABLES 面板**：看 `exc` 的原始异常内容

对比它和你 `.env` 里写的值，差异一眼可见。（常见：`.env` 里 `POSTGRES_HOST` 写成了容器名而不是 `localhost`。）

### 步骤 5：修完要能解释

> "之前错是因为 Docker 的 postgres 容器没启动，所以 5432 端口没人监听，asyncpg 连接被拒绝。现在 `docker compose up -d` 起来了，端口通了，所以能连上。"

**能说出这句"因为…所以…"，才算真的修完了。** 只会说"我重启了一下就好了"，下次还会踩同一个坑。

## 2D.8 调试心法（前端转后端最该改的思维）

1. **报错是线索，不是敌人。** 后端的报错比前端详细得多——它甚至会告诉你文件名和行号。别怕，读完它。
2. **先看日志，再猜原因。** 你猜的"应该是缓存问题"，90% 是错的。
3. **假设必须可验证。** "我觉得是 DB 没起" → `docker compose ps`。把"觉得"变成"确认"。
4. **二分法缩小范围。** 100 行里出错？注释掉后 50 行再跑。这比逐行读快 10 倍。
5. **一次只改一个变量。** 同时改三处然后好了，你根本不知道是哪处修的，下次照样不会。
6. **善用 `f"{x=}"`。** 02A 讲过的调试神器，比 `print("x:", x)` 少打字且自带变量名。
7. **修完删掉调试代码。** `print`、`breakpoint()`、临时注释，提交前清理干净。

## 读真实代码（10 分钟）

1. **`src/utils/setup_logging.py` 全文** —— 看日志系统是怎么搭起来的。重点找：`LOG_LEVEL`（第 19 行）、`ConsoleRenderer`（开发用彩色文本，第 42 行）、`JSONRenderer`（生产用 JSON，第 49 行）、`format_exc_info`（生产环境才把异常转成字符串，第 50 行）。
2. **`src/utils/paddle_ocr.py:24-25`** —— 一个典型的"前置校验 + 清晰报错"：

   ```python
   if not paddle_job_url or not paddle_token:
       raise RuntimeError("必须配置Paddle OCR API。设置JOB_URL和TOKEN！！！")
   ```
   
   **写报错信息要写"怎么修"，不只是"哪里错"**——这条信息直接告诉你该配哪个变量。
3. **`src/settings.py:78-83`** —— `@model_validator` 里主动 `raise ValueError`，并且把实际值打进消息（`got {self.KEEPALIVE_INTERVAL_SECS}`）。**报错带上下文**是好习惯。

## 动手实验（25 分钟）

1. **故意制造 5 个异常**：在 `sandbox/` 里写脚本，分别触发 `KeyError`、`IndexError`、`TypeError`（None 上取属性）、`ValueError`、`AttributeError`。每次**先读 Traceback 猜原因，再验证**。这是最快的"报错脱敏"训练。
2. **日志 vs print**：把项目里的 `logger` 复制到你的脚本，用 `logger.info("test_event", a=1, b="x")` 打一条，观察输出格式（有时间戳、级别、字段）。再在 `.env` 里把 `LOG_LEVEL=DEBUG` 改成 `WARNING` 重启服务，看 `info` 日志是否消失。
3. **配置 VSCode 调试器**：建 `.vscode/launch.json`（用 2D.5 的内容），按 F5 启动。在 `main.py` 的启动流程里随便打断点，用 F10/F11 走一遍，在 VARIABLES 面板看 `settings` 对象。
4. **练条件断点和日志点**：在 `src/api/threads.py` 的某个接口里打断点，改成条件断点（如 `limit > 10`）；再加一个日志点打印请求参数。用 `/docs` 发几次请求观察差异。
5. **跑一次 pytest**：`uv run pytest tests/unit -x -q`。如果有失败，**完整读一遍 Traceback**再动手。（170 个测试文件是最好的"代码行为说明书"。）

## 常见坑速查

| 现象 | 原因 / 解法 |
|---|---|
| 断点打上去不停 | 用了 `--reload`（子进程）。去掉它再调 |
| 调试器找不到依赖 | 没选 `.venv` 解释器（01 课 1.5） |
| `ModuleNotFoundError` | 同上，或没跑 `uv sync` |
| 只看到一行报错没有堆栈 | 用了 `logger.error` 而不是 `logger.exception` |
| 日志太吵 / 看不到 debug | 改 `.env` 的 `LOG_LEVEL` |
| 报错堆栈全是第三方库的行 | 从下往上找第一个带你自己项目路径的 File |
| 改了代码不生效 | `--reload` 有时候会漏；手动重启服务 |
| 服务突然不响应 | 忘了删 `breakpoint()` |
| `.env` 改了没效果 | 需要重启服务（配置只在启动时读取） |
| 调试多请求时总是停在别人的请求上 | 用**条件断点**限定 `run_id` / `thread_id` |

## 自测题

1. 拿到一段 Traceback，你应该**先读哪一行**？为什么不是第一行？
2. `logger.error("出错了", error=str(e))` 和 `logger.exception("出错了")` 有什么区别？在 `except` 块里该用哪个？
3. 为什么调试时要去掉 `--reload`？
4. 条件断点和日志点分别解决什么问题？各举一个本项目的场景。
5. 容器里跑的服务出问题了，VSCode 调试器用不了，你怎么办？
6. 复述 2D.7 的调试流程。哪一步是"新手最容易跳过、但老手一定会做"的？

**下一课**：[03-async-coroutines.md](03-async-coroutines.md) —— 异步协程：从你熟悉的 JS 事件循环迁移过来。
