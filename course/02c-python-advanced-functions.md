# 第 02C 课 · 进阶函数：读懂项目里那些"看不懂的写法"

> 目标：本仓库里有一批"看着像魔法"的语法——`@dataclass`、`@computed_field`、`*objects`、`yield`、`Annotated[str, ...]`。
> 这一课把它们全部拆开。**要求是"读得懂 + 会照抄"，不是"会默写"**。
> 前置：第 02、02A、02B 课。

---

## 2C.1 函数参数全解

### 四种参数，按顺序排

```python
def f(a, b=2, *args, c, d=4, **kwargs):
    #   ①  ②    ③      ④   ⑤      ⑥
    ...
```

| 序号 | 写法 | 名称 | 说明 |
|---|---|---|---|
| ① | `a` | 位置参数 | 必传，按顺序 |
| ② | `b=2` | 默认参数 | 可省略（02A 讲过默认值别用可变对象） |
| ③ | `*args` | 可变位置参数 | 多出来的位置参数打包成 **tuple** |
| ④ | `c` | 关键字限定参数 | **必须写成 `c=1` 传**，不能靠位置 |
| ⑤ | `d=4` | 带默认的关键字限定 | |
| ⑥ | `**kwargs` | 可变关键字参数 | 多出来的关键字参数打包成 **dict** |

`*` 之后的参数全部"必须用关键字传"，这叫 keyword-only。项目里的真实用法：

```python
# src/agents/react_agent/context.py:12
@dataclass(kw_only=True)          # 生成的所有字段都必须用关键字传
class Context:
    model: str = "openai/qwen-flash"
```

好处是**调用处自解释**：`Context(model="openai/gpt-4o-mini")` 比 `Context("openai/gpt-4o-mini")` 好读得多，而且以后加字段不会把参数位置搞错。

### `*args` / `**kwargs` 真实案例

`src/utils/run_utils.py:49-55`：

```python
def _merge_jsonb(*objects: dict) -> dict:
    """Mimics PostgreSQL's JSONB merge behavior"""
    result = {}
    for obj in objects:            # objects 是 tuple，可以遍历
        if obj is not None:
            result.update(copy.deepcopy(obj))
    return result
```

调用时可以传任意多个 dict：

```python
_merge_jsonb(None, {"a": 1}, {"b": 2})    # {'a': 1, 'b': 2}
```

> 前端对照：JS 里写 `function f(...args)`，Python 的 `*args` 就是它，只是多了一个"关键字版本" `**kwargs`（JS 要手动 `Object.entries` 处理）。

### 调用时也要用星号"拆包"

```python
nums = [1, 2, 3]
f(*nums)                    # 把列表拆成位置参数
conf = {"c": 3, "d": 4}
f(1, 2, **conf)             # 把 dict 拆成关键字参数

# 组合列表 / dict 时也常用
merged = [*a, *b]           # 合并两个 list（等价 a + b）
merged = {**a, **b}         # 合并两个 dict
```

**读代码时看到 `**` 在"调用处"就是拆包，在"定义处"就是收集**——记住这个二分法。

## 2C.2 解包与星号表达式

```python
a, b = 1, 2                    # 同时赋值
a, b = b, a                    # 交换（不需要临时变量！）
x, y = point                   # 拆 tuple
name, _, port = ("h", "x", 5432)   # _ 表示"我不关心这个值"

first, *rest = [1, 2, 3, 4]    # first=1, rest=[2,3,4]  ★
*init, last = [1, 2, 3, 4]     # init=[1,2,3], last=4
a, *mid, b = [1, 2, 3, 4, 5]   # a=1, mid=[2,3,4], b=5
```

在 `for` 里拆包也很常见：

```python
for key, value in conf.items(): ...        # items() 返回 (k, v) 的 tuple
for mode, payload in events: ...           # 项目里事件流就是这样
```

## 2C.3 推导式三件套 + 生成器表达式

```python
nums = [1, 2, 3, 4, 5]

# 列表推导式
[x * x for x in nums]                      # [1, 4, 9, 16, 25]
[x for x in nums if x % 2 == 0]            # [2, 4]

# 字典推导式
{str(x): x * x for x in nums}              # {'1': 1, '2': 4, ...}

# 集合推导式（自动去重）
{len(w) for w in ["a", "bb", "cc"]}        # {1, 2}

# 生成器表达式：圆括号，惰性求值
gen = (x * x for x in nums)                # 不立刻算，用到才算
sum(x * x for x in nums)                   # 55  ← 省内存，推荐
```

**列表推导式 vs 生成器表达式怎么选？**

| | 列表推导式 `[...]` | 生成器表达式 `(...)` |
|---|---|---|
| 立即计算 | 是 | 否，惰性 |
| 占用内存 | 全部结果 | 一次一个 |
| 能重复遍历 | 能 | **只能遍历一次** |
| 用在 | 结果要复用、要 `len()` | 喂给 `sum`/`any`/`join` 等一次性消费 |

真实案例 `src/settings.py:116`：

```python
return tuple(part.strip() for part in self.LOG_EXCLUDE_PATHS.split(",") if part.strip())
```

注意这里用的是**生成器表达式**（没有方括号）——因为结果直接喂给 `tuple()` 一次性消费，中间不需要一个临时 list。

## 2C.4 内置迭代工具（后端每天都在用）

```python
# enumerate：同时拿到下标和值（替代 JS 的 forEach((v, i) => ...)）
for i, item in enumerate(items):
    print(i, item)

# zip：并行遍历多个序列（JS 没有，要自己写）
for name, score in zip(names, scores):
    print(name, score)
list(zip([1,2], ["a","b"]))        # [(1,'a'), (2,'b')]
dict(zip(["a","b"], [1,2]))        # {'a': 1, 'b': 2}   ★ 很实用

# sorted + key：按字段排序
sorted(items, key=lambda it: it["created_at"])
sorted(items, key=lambda it: it["created_at"], reverse=True)
sorted(words, key=len)                       # 按长度
sorted(words, key=str.lower)                 # 忽略大小写

# any / all：短路求值
any([False, False, True])      # True   有一个真就是真
all([True, True, False])       # False  全真才是真
any(x > 10 for x in nums)      # 配合生成器表达式用

# 其他
sum(nums) / min(nums) / max(nums) / len(nums)
list(reversed(nums))
```

**`any` / `all` 的真实案例** `src/utils/run_utils.py:17-19`：

```python
if isinstance(cmd_update, (tuple, list)) and all(
    isinstance(t, (tuple, list)) and len(t) == 2 and isinstance(t[0], str) for t in cmd_update
):
```

读作："如果 cmd_update 是 list/tuple，**且它的每一个元素都满足**（是 tuple/list 且长度为 2 且第一个元素是字符串）"。这就是后端里最常见的**数据形状校验**写法。

## 2C.5 生成器与 `yield`：流式输出的地基

普通函数 `return` 一次就结束。**带 `yield` 的函数变成"生成器"——可以被反复取值，每次取一个。**

```python
def countdown(n):
    while n > 0:
        yield n            # 吐出一个值，然后【暂停】，等下一次被取
        n -= 1

for x in countdown(3):
    print(x)               # 3, 2, 1
```

关键点：**函数体不是一次跑完的**，每次 `next()` 才往前推进到下一个 `yield`。这就是"惰性"。

项目里的真实用法 `src/services/graph_streaming.py:99` 起：

```python
async def stream_graph_events(...):
    ...
    async for event in stream:
        ...
        yield event_name, event["data"]     # 边收边吐
```

这里 `yield` 吐的是 `(事件名, 数据)` 这样的 tuple，最终变成 SSE 响应推给浏览器。**第 14 课会讲透这条链路**，你现在只需要知道：

> `yield` = "我暂时交出一个值，但我不结束，你下次来取我继续。"

这也是为什么 AI 对话能"一个字一个字往外蹦"——LLM 的流式响应、graph 的事件流、SSE 的推送，本质都是生成器在逐段产出。

## 2C.6 装饰器 `@`：读得懂就够

装饰器的本质：**一个接收函数、返回新函数的函数**。

```python
def log_calls(fn):
    def wrapper(*args, **kwargs):        # 用 *args/**kwargs 转发所有参数
        print(f"调用 {fn.__name__}")
        return fn(*args, **kwargs)
    return wrapper

@log_calls                              # 等价于：say_hello = log_calls(say_hello)
def say_hello(name):
    print(f"hi {name}")
```

**前端对照**：这就是 React 的高阶组件（HOC）、Express/Koa 的 middleware、或者 JS 的 `const f = compose(g, h)(fn)`。你已经会这个思维了，只是 Python 给了它一个专门的语法糖 `@`。

项目里的装饰器清单（全是真实存在的）：

| 装饰器 | 出处 | 作用 |
|---|---|---|
| `@dataclass` | `state.py:14`、`context.py:12` | 自动生成 `__init__`、`__repr__` 等 |
| `@dataclass(frozen=True)` | `rag_service.py:57` | 不可变版本（02A 讲过） |
| `@field_validator("status", mode="before")` | `threads.py:51` | Pydantic：字段级校验 |
| `@model_validator(mode="after")` | `settings.py:78` | Pydantic：整体校验 |
| `@computed_field` + `@property` | `settings.py:110-112` | 派生字段（不算输入，只算输出） |
| `@classmethod` | `threads.py:52` | 第一个参数是 `cls` 而不是 `self` |

`settings.py:110-116` 的 `@computed_field @property` 组合值得单独看：

```python
@computed_field
@property
def log_exclude_paths(self) -> tuple[str, ...]:
    if not self.LOG_EXCLUDE_PATHS:
        return ()
    return tuple(part.strip() for part in self.LOG_EXCLUDE_PATHS.split(",") if part.strip())
```

意思是："`LOG_EXCLUDE_PATHS` 是环境变量传来的字符串（`"a,b,c"`），但代码里想要的是 tuple"。于是定义一个**计算属性**，用的时候直接 `settings.app.log_exclude_paths`，它自动帮你转换。**两个装饰器叠着写，是从下往上生效的**（先 `property`，再 `computed_field`）。

## 2C.7 上下文管理器 `with`

```python
with open("a.txt", encoding="utf-8") as f:
    text = f.read()
# 出了这个块，文件自动关闭——即使中间抛异常也会关
```

**前端对照**：`useEffect` 的 cleanup 函数、或者 `try/finally`。它保证"资源一定被释放"。

项目真实用法 `src/utils/paddle_ocr.py:37-47`：

```python
with path.open("rb") as file_obj:
    response = requests.post(..., files={"file": (path.name, file_obj, "application/pdf")}, ...)
```

文件对象只在 `with` 块内有效。你以后写任何文件、数据库连接、锁，都该用 `with`。

**异步版本 `async with`**：第 03 课的 `async with sem:`（信号量限流）就是这个。原理一样，只是进入/退出时要 `await`。

自己写一个上下文管理器（用 `contextlib`，很简单）：

```python
from contextlib import contextmanager

@contextmanager
def timer(label):
    start = time.monotonic()
    try:
        yield                                  # yield 之前 = 进入时
    finally:
        print(f"{label} 耗时 {time.monotonic() - start:.2f}s")   # yield 之后 = 退出时

with timer("查询"):
    do_something()
```

## 2C.8 类型标注进阶（读 `src/models/` 的必备钥匙）

第 02 课讲过基础标注，这里补齐项目里真正用到的那些：

```python
from typing import Any, Literal, Callable, TypedDict, Optional

x: int | None                       # 可能是 int 也可能是 None ★ 项目最常见
x: Optional[int]                    # 老写法，等价
x: list[str]                        # 字符串列表
x: dict[str, Any]                   # 键 str、值任意 ★ 项目的 metadata 就是它
x: tuple[str, ...]                  # 不定长 str tuple
x: Literal["asc", "desc"]           # 只能是这两个字面量之一 ★ 等价 TS 的字面量联合
x: Callable[[int], str]             # 一个"收 int 返回 str"的函数
x: Any                              # 关掉类型检查
```

真实案例 `src/models/threads.py:79`：

```python
sort_by: Literal["thread_id", "status", "created_at", "updated_at"] | None = Field(None, ...)
```

读作："`sort_by` 要么是这四个字符串之一，要么是 None"。FastAPI 会自动据此**拒绝**非法值并生成 Swagger 文档里的下拉框。

### `Annotated`：给类型挂"额外说明"

```python
from typing import Annotated
from pydantic import BeforeValidator

def parse_lower(v: str) -> str:
    return v.strip().lower()

LowerStr = Annotated[str, BeforeValidator(parse_lower)]   # src/settings.py:55
```

`Annotated[类型, 额外信息]` = "基础类型是 str，但**在赋值前先跑一遍 `parse_lower`**"。项目用它把 `AUTH_TYPE: LowerStr = "noop"` 变成"无论环境变量写 `NOOP` 还是 `Noop`，一律转成小写"。同文件还有 `UpperStr`（`settings.py:56`），用于 `ENV_MODE: UpperStr = "LOCAL"`。

**这解决了配置系统的经典痛点**：环境变量大小写不可控，与其在每个使用处 `if x.lower() == ...`，不如在入口统一规范化。

### `from __future__ import annotations`

`src/agents/react_agent/state.py:3` 和 `context.py:3` 都有这一行。作用：**让类型标注延迟求值**，从而可以在类里写引用自身或尚未定义的类型的标注（比如 `def f(self) -> "AppSettings"` 不用加引号）。看到它不用深究，知道是"为了让类型标注更自由"就行。

## 2C.9 functools / itertools 速览（知道有就行）

```python
from functools import lru_cache, partial

@lru_cache(maxsize=128)          # 缓存函数结果（相当于前端的 memo）
def expensive(n): ...

add10 = partial(lambda a, b: a + b, 10)   # 预设部分参数
add10(5)                                  # 15

from itertools import chain, groupby, islice
chain([1,2], [3,4])              # 1,2,3,4  把多个序列串起来
islice(range(100), 10)           # 只取前 10 个（惰性）
```

## 读真实代码（15 分钟）

1. **`src/agents/react_agent/context.py`**（全文，约 40 行）—— 找 `@dataclass(kw_only=True)`、`field(default=..., metadata=...)`、`Annotated[str, {...}]`、`from __future__ import annotations`。读完你会明白"一个 Agent 的可配置项"是怎么声明的。
2. **`src/utils/run_utils.py:10-26`** —— 找 `*args` 的思想、`all(...)` 配生成器表达式、`[tuple(t) for t in ...]` 推导式、条件表达式。
3. **`src/settings.py:110-116`** —— 找 `@computed_field` + `@property` + 生成器表达式 + `tuple()` 组合。
4. **`src/services/graph_streaming.py:99` 起** —— 找 `async def` + `async for` + `yield`，这就是流式输出的现场。

## 动手实验（25 分钟）

1. **写一个自己的装饰器**：`@timer`，打印被装饰函数的耗时。套在 `time.sleep(1)` 的函数上验证。再改成"带参数的装饰器" `@timer("查询")`（提示：外层再包一层）。
2. **`*args` / `**kwargs` 转发**：写一个 `wrapper(*args, **kwargs)`，用 `print` 打印收到的 args（tuple）和 kwargs（dict），再原样转发给内部函数。
3. **生成器 vs 列表**：用 `countdown(5)` 生成器版本和返回 list 的版本各跑一次，分别在开头 `print`，观察"生成器版本不会立刻执行"。
4. **`zip` 造字典**：把 `["host", "port"]` 和 `["localhost", "5432"]` 用 `dict(zip(...))` 拼成配置 dict。
5. **照抄一个 Pydantic 校验器**：定义 `class Config(BaseModel)`，字段 `mode: Literal["dev", "prod"]`，试试传 `"test"` 会报什么错。

## 常见坑速查

| 现象 | 原因 |
|---|---|
| 生成器只能遍历一次 | 生成器是"一次性"的，需要复用就转成 `list(...)` |
| 忘了写 `@` 后面的括号 | `@property` 不带括号；`@dataclass(frozen=True)` 带 |
| 装饰器顺序搞反 | 多个装饰器**从下往上**依次生效 |
| `*args` 拿到的是 tuple 不是 list | 设计如此，需要 list 就 `list(args)` |
| 关键字限定参数传不进去 | `kw_only=True` 后必须写 `参数名=值` |
| 类型标注写了但运行时不报错 | 标注只给编辑器/工具看，运行时不做检查（除非用 Pydantic） |
| `from __future__ import annotations` 报错 | 必须放在文件**最顶部**（docstring 之后） |

## 自测题

1. `def f(*args, **kwargs)` 里，`args` 和 `kwargs` 分别是什么类型？调用处 `f(*a, **b)` 又是在干什么？
2. 列表推导式和生成器表达式，什么场景必须用后者？
3. `@dataclass(frozen=True)` 为什么比普通 `@dataclass` 更适合当配置对象？（提示：回忆 02A 的 frozenset）
4. `Annotated[str, BeforeValidator(parse_lower)]` 解决了什么问题？为什么在配置系统里特别有用？
5. 为什么说"AI 对话能一个字一个字蹦出来"和 `yield` 是同一件事？

**下一课**：[02d-python-debugging.md](02d-python-debugging.md) —— 读报错、打日志、用调试器：把"猜"变成"看见"。
