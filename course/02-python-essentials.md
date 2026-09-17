# 第 02 课 · Python 速成：给前端开发者的对照语法表

> 目标：不需要精通，只要**能读懂本仓库代码 + 能写 50 行以内的小脚本**。全程对照你已经会的 JS/TS。遇到生词随时回来查这一课。

---

## 本课与 02A~02D 的关系（先读这段）

本课是**"查表课"**：用最短时间把 Python 语法和你的 JS 知识对上，让你能开始读真代码。

但"能读"不等于"能写对"。下面四课是配套的**"补基础课"**，专治第 02 课没展开、但写代码时一定会撞上的东西：

| 课 | 主题 | 什么时候读 |
|---|---|---|
| [02A](02a-python-types-and-structures.md) | **类型与数据结构** | 遇到"改了一个变量另一个也变了"、`KeyError`、中文乱码时 |
| [02B](02b-python-logic-and-io.md) | **运算、逻辑与 IO** | 要读写文件/JSON、配环境变量、调 HTTP 接口时 |
| [02C](02c-python-advanced-functions.md) | **进阶函数** | 看不懂 `@dataclass`、`*args`、`yield`、`Annotated` 时 |
| [02D](02d-python-debugging.md) | **调试** | 报错看不懂、想打断点、日志不会看时 |

> 建议节奏：**按 02 → 02A → 02B → 02C → 02D 顺序读**，每课都不长，加起来约 2 小时，之后再去第 03 课。地基打牢，后面读 LangGraph 代码会轻松很多。
> 如果实在着急想先看到 Agent 跑起来：**至少别跳过 02A 和 02D**——一个教你避开"改了 A 结果 B 也变了"这类诡异 bug，一个教你读懂报错。这两样是第一天就会用到的。

---

## 2.1 心智模型：Python 和 JS 最大的三个不同

1. **没有 `{}` 块，用缩进表达层级**。`if`/`for`/`def` 后面是冒号，下一行必须缩进（统一 4 空格）。缩进错了 = 语法错误。
2. **类型是"可选标注"**。运行时不做类型检查，`int | None` 这类标注只给编辑器/工具看（Pylance 相当于你的 TS 编译器）。
3. **列表遍历和"真值"语义不同**。`0`、`""`、`[]`、`None` 都是假值；`[]` 不是"空指针"，就是普通的空数组。

## 2.2 与 JS 语法对照表

| 你会的 JS/TS | Python 等价写法 | 备注 |
|---|---|---|
| `const x = 1` | `x = 1` | 没有 const/let，靠约定全大写=常量 |
| `let arr = [1,2,3]` | `arr = [1, 2, 3]` | 列表 |
| `{a: 1, b: 'x'}` | `{"a": 1, "b": "x"}` 或 `{"a": 1}` 简写 | 字典 dict（可类比对象，但取不存在键会报错） |
| `arr.push(x)` | `arr.append(x)` | |
| `arr.map(f)` | `[f(x) for x in arr]`（列表推导式） | 速度更快、更 Pythonic |
| `arr.filter(f)` | `[x for x in arr if f(x)]` | |
| `arr.slice(1,3)` | `arr[1:3]` | 切片，负索引 `arr[-1]` 取最后一个 |
| `for (const x of arr)` | `for x in arr:` | |
| `if (a && b || !c)` | `if a and b or not c:` | `and/or/not` |
| `a === null ? d : a` | `a if a is not None else d` | 或 `a or d`（注意 0/"" 也会被 or 吃掉） |
| `s.includes('x')` | `"x" in s` | 字符串包含 |
| `obj?.a ?? b` | `obj.a if obj else b` | 没有可选链，多用 if |
| 模板字符串 `` `hi ${name}` `` | `f"hi {name}"` | f-string，前端最该先学会的 |
| `function f(a, b=1) {}` | `def f(a, b=1):` | |
| `const f = (a) => a*2` | `f = lambda a: a*2`（不常用） | 传函数时直接写 `def` 或现成函数名 |
| `try { } catch(e) { }` | `try: ... except Exception as e: ...` | |
| `console.log(x)` | `print(x)` / `logger.info(...)` | 项目里用 structlog |
| `import x from 'y'` | `from y import x` | |
| `export const x` | 模块里直接定义即可 | 顶层变量天然可被 import |
| `undefined` / `null` | `None` | |
| `Promise` | `await`（见第 03 课） | |
| 真/假 | `True` / `False` | 首字母大写 |
| 注释 `// x` | `# x` | 中文注释很常见，文件头部常有大段 docstring |

**切片与推导式是 Python 的"语法糖主力"**，本仓库随处可见，例如：

```python
# 列表推导式：过滤 + 转换一步到位
texts = [item["text"] for item in items if item["type"] == "text"]

# 切片：取最后一条消息、取前 N 条
last = messages[-1]        # 相当于 messages[messages.length-1]
head = messages[:10]       # 前 10 条
```

## 2.3 必须认识的核心类型与操作

```python
# 列表 list —— 可变
tasks = ["a", "b"]
tasks.append("c")          # push
tasks[0]                   # "a"
len(tasks)                 # 3（注意不是 .length）

# 元组 tuple —— 不可变，像只读数组/结构化返回值
point = (1, 2)
x, y = point               # 解构赋值！等价于 const [x, y] = point

# 字典 dict —— 取键要小心
conf = {"port": 2026, "debug": True}
conf.get("host", "0.0.0.0")   # 安全取值，缺省给默认
"port" in conf                # True，判断键存在

# 集合 set —— 去重/包含判断
unique = {1, 2, 2, 3}          # {1,2,3}

# 类型标注（仅提示，不影响运行）
def greet(name: str, times: int = 1) -> str:
    return f"hi {name}" * times
```

**注意 None 检查的坑**（等价于前端 `a ?? b` 但更容易写错）：

```python
value = maybe_get() or "fallback"   # ⚠️ 若 maybe_get() 返回 "" 或 0 也会被替换掉
value = maybe_get() if maybe_get() is not None else "fallback"  # 安全
```

> 📖 本课只讲了"认识这些类型"。**"改了一个变量另一个也变了""`KeyError` 怎么防""中文乱码"这些真正的坑 → 见 [02A 类型与数据结构](02a-python-types-and-structures.md)**。

## 2.4 类与 Pydantic（本项目大量使用）

仓库里到处是 `class Xxx(BaseModel)` / `class Yyy(BaseSettings)` —— 这是 **Pydantic**（数据校验库，FastAPI 的根基）。前端类比：**它同时干了 TypeScript interface 的活 + zod 的活 + 序列化的活**。

```python
from pydantic import BaseModel, Field

class RunCreate(BaseModel):
    assistant_id: str = Field(..., description="要执行的智能体")   # ... = 必填
    input: dict | None = Field(None, description="输入数据")        # 可选
    stream: bool = Field(False)                                     # 默认 false

# 用法一：解析并校验（自动抛错）
data = RunCreate.model_validate({"assistant_id": "abc"})
print(data.assistant_id, data.stream)      # abc False

# 用法二：序列化成 dict/json
payload = data.model_dump()
```

而 `src/settings.py` 里的配置类继承 `BaseSettings`，让它**自动从环境变量 + `.env` 读取**：类里写 `PORT: int = 2026`，就能被环境变量 `PORT` 覆盖——这就是 01 课 `.env` 生效的原理。你可以打开 `src/settings.py` 读一遍类字段，会发现每个配置项都"肉眼可懂"。

### 普通 class 长这样（对比 TS）

```python
class Context:                       # TS: class Context { ... }
    def __init__(self, name: str):   # 构造器，相当于 constructor
        self.name = name             # this.name = name
        self.retries = 0

    def ping(self) -> str:           # 方法
        self.retries += 1
        return f"pong {self.retries}"
```

## 2.5 异常处理（比 JS 更"裸"）

```python
try:
    result = await something()
except ConnectionError as e:       # 捕获特定异常
    logger.error("连不上", error=str(e))
except Exception:                  # 兜底（谨慎使用，别吞掉 bug）
    logger.exception("未知错误")
else:
    pass                           # 没异常才执行（少用）
finally:
    pass                           # 无论是否异常都执行
```

> 项目里常见模式是"把可能失败的 IO（数据库/外部 API）包进 try，日志用 `logger.exception` 打出完整堆栈"。前端 `throw` 的对象可以是任何值，Python 里 **raise 后面必须是异常实例**（`raise ValueError("...")`）。
>
> 📖 **怎么看懂报错、怎么打日志、怎么打断点 → 见 [02D 调试](02d-python-debugging.md)**（第一天就会用到）。

## 2.6 看懂本仓库代码的最小阅读集

按顺序打开下面三个文件，用上面的对照表逐行读（不要求全懂，找"眼熟"的语法）：

1. `src/agents/react_agent/utils.py`（~30 行）：`load_chat_model` —— 看 def 签名、f-string、`getenv` 兜底。
2. `src/agents/react_agent/context.py`：一个 dataclass —— 看**字段默认值与字段类型**如何共同定义"一个智能体的配置"。
3. `src/services/graph_factory.py`：看 `inspect.signature` 反射调用（超纲，先混个脸熟，第 10 课细讲）。

读完你会发现：**Python 的"配置文件/模型/工具函数"读起来几乎像读伪代码**，比 JS 生态更直白。

## 2.7 前端转 Python 最容易踩的坑

| 坑 | 说明 |
|---|---|
| `dict[key]` 取不存在键 | 抛 `KeyError`，习惯用 `.get(key, default)` |
| 缩进混用 Tab/空格 | 直接语法错误。VSCode 装了 Python 扩展会自动 4 空格 |
| 忘记 `self` | 类方法第一个参数必须是 `self`（名称可换但约定俗成） |
| `==` 与 `is` | 值比较用 `==`；判断 `None` 用 `is None` / `is not None` |
| 函数参数默认值是可变对象 | `def f(x=[])` 是共享同一个 list 的经典坑，默认值用 `None` 再在函数内赋值 |
| 分号 | Python 不需要分号，加了也能跑但不推荐 |
| `import` 循环依赖 | 大项目组织成包 `src/xxx`，从包根 import（本项目用 `from src.xxx import yyy`） |

## 动手实验（15 分钟）
1. 在仓库根建 `sandbox/` 文件夹，写 `hello.py`：读 `src/settings.py` 里 `AppSettings.PORT` 默认值，用 f-string 打印 `"服务默认端口是 2026"`（先手动写 2026，等第 04 课学会 import 再改真读）。
2. 把 `[1,2,3,4,5]` 里的大于 2 的数平方，用**列表推导式**一行完成并打印。
3. 定义一个 `Assistant` 类（`name` + `graph_id` 两个属性），实例化后打印。再改用 Pydantic 的 `BaseModel` 写一遍，体会"自动校验+序列化"。

## 自测题
1. `{"a":1}` 和 `[{"a":1}]` 在类型上分别是什么？取 `[0]` 和取 `["a"]` 分别对谁合法？
2. 切片 `messages[-3:]` 表示什么？改成一行的"取最近 5 条消息"。
3. f-string 里怎么把 dict 的一个键拼进去？写一行示例。
4. 打开 `pyproject.toml`，找到 `requires-python`（Python 版本要求）和测试相关配置（pytest / ruff），说说出 `uv run pytest` 大概会做什么。

**下一课**：[02a-python-types-and-structures.md](02a-python-types-and-structures.md) —— 类型与数据结构：Python 的"内存模型"和前端不一样（本课最重要的补充）。
（02A → 02B → 02C → 02D 读完后，接 [03-async-coroutines.md](03-async-coroutines.md)。）
