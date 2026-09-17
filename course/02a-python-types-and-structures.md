# 第 02A 课 · 类型与数据结构：Python 的"内存模型"和前端不一样

> 目标：第 02 课让你**看得懂语法**，这一课让你**不写出诡异 bug**。
> 核心差异只有一个——**Python 的变量是贴在对象上的"标签"，不是装值的"盒子"**。理解这一点，本课后面所有坑都会自动消失。
> 前置：第 02 课。

---

## 2A.1 最重要的一课：可变 vs 不可变

先看前端里你已经习惯的规则：

```js
const a = [1, 2, 3];
a.push(4);            // ✅ 合法！const 只锁"绑定"，不锁"内容"
```

Python 里更极端：**连"绑定"都不锁**。

```python
a = [1, 2, 3]
b = a                 # ⚠️ 不是复制！b 和 a 是同一个列表的两个名字
b.append(4)
print(a)              # [1, 2, 3, 4]  ← a 也变了
```

### 心智模型：盒子 vs 标签

- **JS**：变量 ≈ 一个盒子，盒子里装着值（对象类型装的其实是引用）。
- **Python**：**对象住在内存里，变量只是贴在对象上的标签**。`b = a` 是"又贴了一张标签"，不是"复制一份"。

所以赋值 = 贴标签。这意味着：

```python
a = [1, 2, 3]
b = a
b = [9]               # 这只是把 b 这张标签撕下来、贴到新列表上，a 完全不受影响
print(a)              # [1, 2, 3]
```

**改对象**（`b.append`）会影响 a；**改标签**（`b = ...`）不会。分清楚这两件事，Python 的内存模型就通了。

### 谁可变，谁不可变

| 不可变（immutable） | 可变（mutable） |
|---|---|
| `int` `float` `bool` `complex` | `list` |
| `str` | `dict` |
| `tuple` | `set` |
| `frozenset` | `bytearray` |
| `None` | 绝大多数自定义类实例 |

不可变的好处：**可以当 dict 的键、可以放进 set、可以被安全地共享**。项目里 `@dataclass(frozen=True)`（`src/services/rag_service.py:57`）就是在声明"这个配置对象创建后不许改"。

### 经典坑 1：可变默认参数

```python
def add_item(x, bucket=[]):    # ❌ 默认值只在定义时求值一次，所有调用共享同一个 list
    bucket.append(x)
    return bucket

add_item(1)     # [1]
add_item(2)     # [1, 2]   ← 你以为会是 [2]
```

正确写法：

```python
def add_item(x, bucket=None):
    if bucket is None:
        bucket = []
    bucket.append(x)
    return bucket
```

**这条在 Python 里是铁律。** 你在 `src/` 里会看到大量 `field(default_factory=list)`（`src/agents/react_agent/state.py:21`）——那就是 dataclass / Pydantic 版本的正确写法，原理完全一样。

### 经典坑 2：`[[0]] * 3`

```python
grid = [[0]] * 3               # ❌ 三个元素指向同一个内层列表
grid[0].append(1)
print(grid)                    # [[0,1], [0,1], [0,1]]

grid = [[0] for _ in range(3)] # ✅ 每次循环新建一个
```

JS 的 `Array(3).fill([])` 有一模一样的问题。

## 2A.2 数值类型：int 比 JS 强，float 比你想的弱

| 类型 | 前端对照 | 说明 |
|---|---|---|
| `int` | JS `number` / `BigInt` | **无限精度**，没有 2^53 上限 |
| `float` | JS `number` | IEEE754 双精度，有精度误差 |
| `bool` | `boolean` | **是 int 的子类**：`True == 1`、`False == 0` |
| `Decimal` | —— | 精确十进制，金额计算用 |

```python
2 ** 100                    # 1267650600228229401496703205376（JS 里会变成 1.2676506002282294e+30）
0.1 + 0.2                   # 0.30000000000000004   ← JS 也一样，别惊讶
round(2.675, 2)             # 2.67  ← 浮点误差 + 银行家舍入，别用 round 处理钱
int("42")                   # 42    字符串转数字（JS: parseInt）
int(3.9)                    # 3     ← 截断，不是四舍五入
7 // 2                      # 3     整除
7 % 2                       # 1     取模
```

项目里的真实写法（`src/settings.py:75,410`）：

```python
PORT: int = 2026
CRON_MAX_PAYLOAD_BYTES: int = 64 * 1024     # 注意：这是运行时的乘法，不是字面量
```

`64 * 1024` 这种"算式当常量"在 Python 里非常常见，读代码时别以为它是字符串。

## 2A.3 字符串：不可变，而且有"编码"这个概念

```python
s = "aegra"
s.upper()          # "AEGRA" —— 返回新串，原串不变（和 JS 一样）
s[0] = "A"         # ❌ TypeError：字符串不支持下标赋值（JS 里是静默失败）
```

常用方法对照：

| JS | Python |
|---|---|
| `s.split(',')` | `s.split(",")` |
| `arr.join(',')` | `",".join(arr)` ← **分隔符在前、数组在后**，别写反 |
| `s.trim()` | `s.strip()` / `.lstrip()` / `.rstrip()` |
| `s.replace(a, b)` | `s.replace(a, b)` |
| `s.startsWith(x)` | `s.startswith(x)` |
| `s.endsWith(x)` | `s.endswith(x)` |
| `s.includes(x)` | `x in s` |
| `s.toUpperCase()` | `s.upper()` / `.lower()` |
| `s.repeat(3)` | `s * 3` |
| `s.slice(0, 3)` | `s[:3]` |

f-string 进阶（本项目天天用）： 

```python
name, port = "aegra", 2026
f"{name} 跑在 {port}"      # aegra 跑在 2026
f"{port:>6}"               # '  2026'   右对齐补空格
f"{3.14159:.2f}"           # '3.14'
f"{name=}"                 # "name='aegra'"  ← 调试神器：变量名和值一起打印
```

### 编码：Python 比 JS 更需要你操心

JS 的字符串天生 UTF-16，你几乎不用管编码。而 Python 的**文件 IO 有编码参数**，在中文 Windows 上这是真实的坑：

```python
"中文".encode("utf-8")            # b'\xe4\xb8\xad\xe6\x96\x87'
b"\xe4\xb8\xad".decode("utf-8")   # 乱码 / 报错就查这里
```

真实案例 `src/utils/setup_logging.py:31-46`：项目检测到 `sys.platform == "win32"` 时，**特意换成不画 Unicode 方框字符的 traceback 渲染器**——因为 Windows 控制台默认编码（cp936/cp1252）渲染不了那些字符，会直接 `UnicodeEncodeError` 把日志系统搞崩。同一套配置里读 `.env` 也显式写了 `env_file_encoding="utf-8"`（`src/settings.py:64`）。

> **行动项**：以后你自己写文件读写，永远显式写 `encoding="utf-8"`。这一行能省掉你未来无数小时的乱码排查。

原始字符串（正则、Windows 路径必用）：

```python
r"[^A-Za-z0-9._-]+"      # 反斜杠不转义
r"C:\Users\admin"        # 否则 \U 会被当成转义序列
```

## 2A.4 list 与 tuple

```python
ids = ["a", "b"]     # list：可变、可增删
pair = (1, 2)        # tuple：不可变、可当 dict 键
one = (1,)           # ⚠️ 单元素 tuple 的逗号不能省，否则它就是 int 1
```

常用操作：

| 目的 | 写法 | 备注 |
|---|---|---|
| 追加一个 | `arr.append(x)` | |
| 合并另一个 | `arr.extend(other)` / `a + b` | |
| 插入 | `arr.insert(0, x)` | 头部插入是 O(n)，别放进循环 |
| 删除 | `arr.remove(x)` / `arr.pop()` / `del arr[0]` | `pop()` 返回被删的元素 |
| 原地排序 | `arr.sort()` | 返回 None！别写 `arr = arr.sort()` |
| 排序并返回新表 | `sorted(arr)` | |
| 按字段排序 | `sorted(items, key=lambda it: it["created_at"])` | ★ 最常用 |
| 反转 | `arr.reverse()` / `arr[::-1]` | |
| 查下标 | `arr.index(x)` | 不存在抛 `ValueError` |
| 计数 | `arr.count(x)` | |
| 长度 | `len(arr)` | **不是 `arr.length`** |
| 求和 / 最值 | `sum(arr)` / `min(arr)` / `max(arr)` | |

切片进阶：

```python
nums = [0, 1, 2, 3, 4, 5]
nums[1:4]      # [1, 2, 3]        左闭右开（和 JS slice 一致）
nums[:3]       # [0, 1, 2]
nums[-2:]      # [4, 5]           最后两个
nums[::2]      # [0, 2, 4]        步长 2
nums[::-1]     # [5, 4, 3, 2, 1, 0]  反转
```

**tuple 的真正用途：结构化返回值 + 不可变记录。**

```python
def min_max(nums):
    return min(nums), max(nums)      # 返回一个 tuple

lo, hi = min_max([3, 1, 4])          # 解构，等价于 JS 的 const [lo, hi] = ...
```

项目里 `isinstance(t, (tuple, list))`（`src/utils/run_utils.py:17`）就是把 tuple 当"只读的小数组"在用。

## 2A.5 dict：本项目出现频率第一的结构

```python
conf = {"port": 2026, "debug": True}

conf["port"]                    # 2026
conf["host"]                    # ❌ KeyError —— 和 JS 返回 undefined 完全不同！
conf.get("host")                # None（安全）
conf.get("host", "0.0.0.0")     # "0.0.0.0"（带默认值）★ 最常用
"port" in conf                  # True，判断键是否存在
conf.setdefault("tags", [])     # 有就返回，没有就设成 [] 再返回
conf.pop("debug", None)         # 取出并删除
conf.update({"a": 1})           # 合并另一个 dict
```

遍历：

```python
for k in conf: ...                    # 遍历键
for k, v in conf.items(): ...         # 遍历键值对 ★
for v in conf.values(): ...
```

字典推导式与合并：

```python
{name: len(name) for name in ["a", "bb"]}    # {'a': 1, 'bb': 2}
{**a, **b}                                   # 合并（旧写法）
a | b                                        # 合并（3.9+，更清晰）
```

**键必须是可哈希的**（也就是不可变）：`str` / `int` / `tuple` 可以，`list` / `dict` 不行。这就是 2A.1 的可变性知识第一次变成硬性限制。

## 2A.6 set 与 frozenset：去重和"是否存在"

```python
s = {1, 2, 2, 3}        # {1, 2, 3}  自动去重
s.add(4)
s.discard(1)
1 in s                  # True，O(1) —— 比 list 的 in 快一个量级
a & b                   # 交集
a | b                   # 并集
a - b                   # 差集
```

项目里的真实用法，全是拿 `frozenset` 当**常量白名单**：

- `src/api/threads.py:48`：`_ALLOWED_SORT_FIELDS = frozenset({"created_at", "updated_at", "thread_id", "status"})`
- `src/services/worker_executor.py:38`：`_TERMINAL_STATUSES = frozenset({"success", "error", "interrupted"})`
- `src/settings.py:30`：`_LIBPQ_ONLY_PARAMS = frozenset({...})`

为什么是 `frozenset` 而不是 `set`？**因为不可变，可以安全地当模块级常量被所有代码共享**，不怕被谁改掉。这就是 2A.1 的知识直接变成工程判断。

## 2A.7 本项目的"数据形状"（本课最重要的一节）

读完 `src/models/` 你会发现，整个项目的数据就三种形状：

```python
# 1) 单条记录：dict[str, Any]
metadata = {"title": "第02课测试", "tags": ["a", "b"]}

# 2) 集合：list[dict[str, Any]]（API 返回的列表）
threads = [{"thread_id": "..."}, {"thread_id": "..."}]

# 3) 包裹：{"items": [...], "total": 10}
```

真实代码里的类型标注（`src/models/threads.py`）：

```python
metadata: dict[str, Any] | None = Field(None, ...)              # 第 16 行
threads: list[Thread]                                           # 第 63 行
values: dict[str, Any] | list[dict[str, Any]] | None            # 第 139 行 ← 联合类型
sort_by: Literal["thread_id", "status", "created_at"] | None    # 第 79 行 ← 只能取这几个字面量
```

`Literal` 相当于 TS 的字符串字面量联合类型：`type SortBy = 'thread_id' | 'status' | 'created_at'`。

### 安全取值链：`or {}` 模式（本项目到处都是）

```python
payload = {"data": None}
payload.get("data") or {}          # {} ← 拿到 None 也不会炸
```

真实案例 `src/utils/paddle_ocr.py:51`：

```python
job_id = (payload.get("data") or {}).get("jobId")
```

一行做了三件事：安全取键 → None 兜底成空 dict → 再安全取键。**这是本项目最值得背下来的一行惯用法**，等价于前端 `payload?.data?.jobId`。同文件第 58、66 行还有更长的三层版本。

### 判断类型：`isinstance`

```python
isinstance(x, dict)                 # 是 dict 吗
isinstance(x, (list, tuple))        # 是两者之一吗 ★ 常见
isinstance(x, str) and x.strip()    # 既判断类型、又判断非空
```

真实案例：`src/utils/paddle_ocr.py:119-145` 的 `_extract_markdown_from_payload` 就是一棵 isinstance 判断树。**读它，你就读懂了"Python 怎么写防御式解析"**——面对一个格式不确定的外部 API 响应，怎么一层层剥出想要的值。

## 2A.8 浅拷贝 vs 深拷贝

```python
import copy

a = {"tags": ["x"]}
b = a                     # 同一个对象（贴标签）
c = a.copy()              # 浅拷贝：外层是新对象，内层还是共享的
d = copy.deepcopy(a)      # 深拷贝：递归复制所有层级

c["tags"].append("y")
print(a["tags"])          # ['x', 'y']  ← 浅拷贝没救你
```

前端对照：`{...a}` 是浅拷贝（等于 `.copy()`），`structuredClone(a)` 才等于 `deepcopy`。

项目真实用法：

- `src/utils/run_utils.py:54`：`result.update(copy.deepcopy(obj))` —— 合并 JSONB 时深拷贝，防止外部改动污染内部状态
- `src/services/langgraph_service.py:417,716`：深拷贝图配置，**让每个请求拿到自己独立的配置副本**

这就是这个项目"多用户并发不串数据"的一环——深拷贝是并发安全的基础设施。

## 2A.9 collections 工具箱（知道有这些就行）

```python
from collections import defaultdict, Counter, deque, namedtuple

defaultdict(list)          # 访问不存在的键自动建 []，省掉 if key not in d
Counter(["a", "a", "b"])   # Counter({'a': 2, 'b': 1})   计数神器
deque(maxlen=100)          # 两端 O(1) 的队列，天然适合"只保留最近 N 条"
namedtuple("P", "x y")     # 带字段名的 tuple，p.x 比 p[0] 好读
```

> 本项目内存版 Broker 用的是 `asyncio.Queue`（第 07 课），`deque` 是它的同步版近亲，理解概念即可。

## 读真实代码（10 分钟）

按顺序读这三个片段，只找本课讲过的东西：

1. **`src/models/threads.py` 第 60-95 行** —— 找 `list[Thread]`、`dict[str, Any]`、`Literal[...]`、`| None`。
2. **`src/utils/run_utils.py` 第 29-55 行** —— 找 `isinstance`、`(tuple, list)` 联合判断、`copy.deepcopy`、`dict.update`。
3. **`src/utils/paddle_ocr.py` 第 119-145 行** —— 找 `or {}` 安全取值、isinstance 判断树、`"\n\n".join(...)`。

## 动手实验（20 分钟）

1. **证明"变量是标签"**：写 `a = [1,2]` / `b = a` / `b.append(3)` / `print(a)`，解释输出。再用 `b = a.copy()` 重做一遍，对比差异。
2. **复现可变默认参数坑**：写一个带 `bucket=[]` 默认参数的函数，连续调用两次观察累积；然后改成 `bucket=None` 修好。
3. **安全解析嵌套 JSON**：把 `{"data": {"resultUrl": {"markdownUrl": None}}}` 存进变量，用一行 `or {}` 链取出 `markdownUrl`（取不到应得到 `None` 而不是报错）。
4. **深拷贝实验**：对 `{"tags": ["x"]}` 分别做 `.copy()` 和 `copy.deepcopy()`，改内层 list，观察原对象是否被影响。

## 常见坑速查

| 现象 | 原因 |
|---|---|
| 改 b 结果 a 也变了 | 赋值是贴标签不是复制。用 `.copy()` / `deepcopy` |
| 两次调用之间数据"串"了 | 可变默认参数。默认值改用 `None` |
| `KeyError` | `d[k]` 取了不存在的键。用 `.get(k, default)` |
| `TypeError: unhashable type: 'list'` | 拿 list 当 dict 的键 / set 的元素 |
| `UnicodeDecodeError`、中文乱码 | 文件 IO 没写 `encoding="utf-8"` |
| `(1)` 不是 tuple | 单元素 tuple 必须写 `(1,)` |
| 改了内层，原对象也变 | 浅拷贝的锅。需要 `deepcopy` |
| `[[]] * 3` 三行联动 | 同一个内层对象的三个引用 |
| `arr = arr.sort()` 得到 None | `sort()` 原地排序且返回 None，用 `sorted()` |

## 自测题

1. 为什么 `frozenset` 适合当模块级常量，而 `set` 不适合？
2. `d.get("a") or {}` 和 `d.get("a", {})` 有什么区别？各适合什么场景？
3. `a = [1,2,3]`，执行 `b = a` 后，`b = b + [4]` 和 `b += [4]` 对 `a` 的影响一样吗？为什么？
4. 打开 `src/models/threads.py`，说出 `values: dict[str, Any] | list[dict[str, Any]] | None` 允许哪几种输入。
5. 项目为什么要在合并配置时用 `copy.deepcopy` 而不是直接 `update`？

**下一课**：[02b-python-logic-and-io.md](02b-python-logic-and-io.md) —— 运算、逻辑、文件与网络 IO，以及怎么"看见"程序在干什么。
