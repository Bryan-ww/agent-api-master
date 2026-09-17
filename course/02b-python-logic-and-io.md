# 第 02B 课 · 运算、逻辑与 IO：让数据进来、出去、以及被算清楚

> 目标：补齐三块"每天都在用但第 02 课没讲"的基础——**运算与逻辑**（怎么算、怎么判断）、**IO**（文件/JSON/环境变量/网络怎么进怎么出）、以及**正则**（项目里到处是 `re.sub`）。
> 本课结束后，你应该能独立读懂 `src/utils/paddle_ocr.py` 这个 197 行的文件——它是本课所有知识点的"活教材"。
> 前置：第 02、02A 课。

---

## 2B.1 运算符全表（对照 JS）

### 算术

| 运算 | Python | JS | 注意 |
|---|---|---|---|
| 加 | `+` | `+` | 字符串 `+` 也是拼接 |
| 减 | `-` | `-` | |
| 乘 | `*` | `*` | `"ab" * 3` → `"ababab"` |
| 除 | `/` | `/` | **永远返回 float**：`6 / 2` → `3.0` |
| 整除 | `//` | —— | `7 // 2` → `3`（JS 要 `Math.floor(7/2)`） |
| 取模 | `%` | `%` | 负数行为不同，见下 |
| 幂 | `**` | `**` | `2 ** 10` → `1024` |
| 同时取商和余 | `divmod(7, 2)` | —— | `(3, 1)`，很实用 |

**负数取模的坑**（Python 和 JS 结果不一样）：

```python
-7 % 3        # 2      ← Python：结果符号跟除数走
-7 // 2       # -4     ← 向下取整，不是向零截断
int(-7 / 2)   # -3     ← 想要 JS 那种"截断"行为得这么写
```

### 比较

```python
1 == 1          # True    注意：Python 没有 ===，== 就是值比较
1 == True       # True    ⚠️ 因为 bool 是 int 子类（02A 讲过）
1 is True       # False   is 比较的是"是不是同一个对象"
x is None       # ★ 判断 None 永远用 is / is not，不用 ==

3 > 2 > 1       # True    ★ 链式比较，JS 里没有！等价 (3>2) and (2>1)
"a" in "abc"    # True    in / not in
"a" in ["a","b"] # True   对 list 也成立
"k" in {"k": 1} # True   对 dict 判断的是"键"
```

### 逻辑与位运算

```python
a and b
a or b
not a

a & b      # 按位与（也用于 set 交集）
a | b      # 按位或（也用于 set 并集、dict 合并）
a ^ b      # 异或
a << 2     # 左移
a >> 1     # 右移
```

> 位运算在业务代码里不常见，但你会读到 `CRON_MAX_PAYLOAD_BYTES: int = 64 * 1024` 这类"用位运算算容量"的写法，认识即可。

### 赋值运算符

```python
n = 1
n += 1        # 等价 n = n + 1
n //= 2
n **= 2
s = "a"
s += "b"      # 字符串：新对象

lst = [1]
lst += [2]    # ⚠️ list 的 += 是【原地修改】！等价 lst.extend([2])
lst = lst + [2]  # 这个是【新建】列表
```

**最后两行的区别是 02A 那道自测题的答案**：因为 list 实现了 `__iadd__`（原地加法），`lst += [x]` 会改到所有指向这个 list 的变量；而 `lst = lst + [x]` 只是把标签挪到新列表上。

## 2B.2 最容易踩的坑：and / or 返回的不是布尔值

```python
0 or "fallback"        # "fallback"
"a" and "b"            # "b"
[] or {}               # {}
```

规则很简单：

- **`a or b`**：a 为真 → 返回 **a**；a 为假 → 返回 **b**
- **`a and b`**：a 为假 → 返回 **a**；a 为真 → 返回 **b**
- 都是**短路求值**（short-circuit）：`a and b` 里 a 为假，b 根本不会被求值

这一点和 JS 的 `||` / `&&` 行为一致，所以你应该很熟。**但两边"什么是假值"不一样**，这才是真正的坑（见 2B.3）。

常见用法——**用 `or` 给默认值**：

```python
port = os.getenv("PORT") or 2026      # 环境变量没配就用 2026
```

⚠️ 但这个写法有个陷阱：如果合法值是 `0`、`""`、`[]`，会被误判成"没配"而替换掉：

```python
retries = int(os.getenv("RETRIES") or 3)   # ❌ 用户配 RETRIES=0 会被吃掉，变成 3

raw = os.getenv("RETRIES")
retries = int(raw) if raw is not None else 3   # ✅ 安全：只有"没配"才用默认值
```

JS 里同样的坑对应 `??`（空值合并）——**Python 没有 `??`，等价写法就是上面那个 `is not None` 三元式**。

## 2B.3 真值表：哪些东西是"假"

```python
假值：False  None  0  0.0  ""  []  {}  ()  set()
真值：其他一切 —— 包括 "0"、"False"、[0]、{"a": None}
```

**和 JS 的关键差异**：

| 值 | JS | Python |
|---|---|---|
| `[]` | **真**（！） | **假** |
| `{}` | **真**（！） | **假** |
| `"0"` | 真 | 真 |
| `0` | 假 | 假 |
| `None` / `null` | 假 | 假 |

前端最需要改掉的习惯：JS 里判断空数组必须写 `arr.length === 0`；**Python 里直接 `if not arr:` 就行**，而且这是最 Pythonic 的写法。

```python
if not messages:          # 空列表 / None 都会进来
    logger.warning("没有消息")

if messages:              # 非空
    ...
```

项目里的实例：`src/utils/paddle_ocr.py:63` 的 `if markdown_text:` —— 一行同时挡掉了"空字符串"和"None"两种情况。

## 2B.4 浮点数、取整与 math 模块

```python
0.1 + 0.2                 # 0.30000000000000004（IEEE754，和 JS 完全一样）
0.1 + 0.2 == 0.3          # False  ⚠️

import math
math.isclose(0.1 + 0.2, 0.3)   # True  ★ 比较浮点数应该用这个
math.floor(3.7)           # 3
math.ceil(3.2)            # 4
math.sqrt(16)             # 4.0
math.pi                   # 3.141592653589793
float("inf")              # 正无穷
float("nan")              # NaN（注意：nan != nan）

round(2.5)                # 2  ⚠️ 银行家舍入：.5 往偶数靠
round(3.5)                # 4
round(2.675, 2)           # 2.67 ⚠️ 浮点误差导致的"反直觉"

# 处理金额请用 Decimal，不要用 float
from decimal import Decimal
Decimal("0.1") + Decimal("0.2")   # Decimal('0.3')  ✅
```

项目里 `max(1, int(...))`（`src/settings.py:128`）是一个典型组合：先转 int、再保证至少为 1，防止 `0` 或负数传下去把下游搞崩。

## 2B.5 IO 之一：stdout / stderr 与 `__main__`

### print 是调试工具，不是日志

```python
print("hello")                      # 写到 stdout
import sys
print("出错了", file=sys.stderr)     # 写到 stderr（错误信息该走这里）
```

**为什么要分清 stdout / stderr？** 因为容器/CI 里两者会被分别收集：正常输出进日志、错误输出进告警。把错误 `print` 到 stdout 是很常见但很糟的习惯。

### 项目为什么不用 print

打开 `src/utils/setup_logging.py`，你会看到项目用 **structlog** 把日志做成了"结构化事件"：

```python
logger = structlog.get_logger(__name__)

logger.info("run_started", run_id=run_id, thread_id=thread_id)
logger.warning("paddle_json_parse_fallback_to_text", offset=index)   # paddle_ocr.py:172
logger.exception("未知错误")                                          # 自动带上堆栈
```

对比前端：

```js
console.log(`run ${runId} started`);           // ❌ 拼成字符串，机器读不了
logger.info({ event: 'run_started', runId });  // ✅ 结构化，可被 ELK/Loki 检索
```

**关键区别**：`logger.info("事件名", key=value)` —— 第一个参数是**事件名（常量字符串）**，后面全是关键字参数。这样日志能被机器按字段检索，而不是一团文本。这是"前端 console.log → 生产可观测"的分水岭。

### `if __name__ == "__main__":` 是什么

```python
def main():
    print("跑起来了")

if __name__ == "__main__":     # 只有"直接运行这个文件"时才执行
    main()
```

- **直接运行** `python script.py` → `__name__` 是 `"__main__"` → 执行
- **被 import** `from script import main` → `__name__` 是 `"script"` → 不执行

前端对照：相当于"这个文件既是模块、又能当 CLI 入口"，但 Python 需要显式写这个判断（JS 里靠 `require.main === module`）。

### 一个真实 Windows 坑

`src/utils/setup_logging.py:97-99` 里日志流的配置写的是**字符串** `"ext://sys.stdout"` 而不是直接传 `sys.stdout` 对象，注释解释了原因：**Windows 上多进程会 pickle 这个配置，直接传流对象会 pickle 失败**。这类"字符串引用延迟到子进程再解析"的技巧，是跨平台后端开发的日常。

## 2B.6 IO 之二：文件读写

```python
# 基础写法：with 自动关闭文件（相当于 useEffect 的 cleanup）
with open("data.txt", "r", encoding="utf-8") as f:
    text = f.read()

with open("out.txt", "w", encoding="utf-8") as f:      # "w" 会清空原文件
    f.write("hello\n")

with open("out.txt", "a", encoding="utf-8") as f:      # "a" 追加
    f.write("more\n")

with open("logo.png", "rb") as f:                       # "rb" 二进制读（图片/PDF）
    data = f.read()
```

模式速查：`r` 读 / `w` 覆盖写 / `a` 追加 / `r+` 读写 / 加 `b` 表示二进制。

> **`encoding="utf-8"` 不是可选项。** 在中文 Windows 上不写它，Python 会用系统默认编码（cp936），读写中文文件时随机乱码或抛 `UnicodeDecodeError`。02A 已经讲过原理，这里再强调一次。

### 用 pathlib 的现代写法（本项目用的就是这套）

```python
from pathlib import Path

p = Path("data") / "file.txt"      # 用 / 拼路径，跨平台，不用管 \ 还是 /
p.exists()                          # 是否存在
p.name                              # "file.txt"     文件名
p.stem                              # "file"         去掉后缀
p.suffix                            # ".txt"         后缀
p.parent                            # 父目录
p.read_text(encoding="utf-8")       # 一行读完
p.write_text("hi", encoding="utf-8")
p.open("rb")                        # 需要二进制时的写法
```

真实案例 `src/utils/paddle_ocr.py:37`：

```python
with path.open("rb") as file_obj:
    response = requests.post(..., files={"file": (path.name, file_obj, "application/pdf")})
```

注意两点：① 上传文件用 `"rb"` 二进制模式；② 传给服务端的是 `path.name`（**只有文件名，不含目录**）。

### 顺带一个安全知识点

`src/utils/paddle_ocr.py:181-185`：

```python
def safe_filename(filename: str) -> str:
    base = Path(filename).name.strip() or "document.pdf"
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    return base if base.lower().endswith(".pdf") else f"{base}.pdf"
```

用户传上来的文件名可能是 `../../etc/passwd`。`Path(filename).name` 只保留最后一段（**干掉目录穿越**），正则再把所有非白名单字符换成 `_`。**这就是"永远不要相信用户输入"的最小实例**——前端出身的人尤其容易忽略，因为浏览器里通常没有这种攻击面。

## 2B.7 IO 之三：JSON（本项目最核心的数据格式）

```python
import json

# 字符串 ↔ Python 对象
text = json.dumps({"name": "中文"})                        # '{"name": "\\u4e2d\\u6587"}'
text = json.dumps({"name": "中文"}, ensure_ascii=False)     # '{"name": "中文"}'  ★
data = json.loads('{"a": 1}')                              # {'a': 1}

# 文件 ↔ Python 对象
with open("c.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
with open("c.json", encoding="utf-8") as f:
    data = json.load(f)
```

**`ensure_ascii=False` 是中文项目的必写项**，否则中文全变成 `\u4e2d\u6587` 转义。项目真实用法 `src/utils/paddle_ocr.py:43`。

类型映射（写 API 时反复遇到）：

| JSON | Python |
|---|---|
| `null` | `None` |
| `true` / `false` | `True` / `False` |
| `{}` | `dict` |
| `[]` | `list` |

**解析失败要捕获**：`src/utils/paddle_ocr.py:154-157` 就专门处理了"返回的不是合法 JSON"这种情况：

```python
from json import JSONDecodeError

try:
    return json.loads(stripped)
except JSONDecodeError:
    pass            # 落到后面的兜底逻辑，而不是让服务崩掉
```

> 读外部 API 的响应时**永远假设它可能不是你以为的格式**——这是后端和前端最大的心态差别之一。

## 2B.8 IO 之四：环境变量（配置从哪来）

```python
import os

os.getenv("POSTGRES_HOST")                 # 没配返回 None
os.getenv("POSTGRES_HOST", "localhost")    # 没配返回默认值 ★
os.environ["X"]                            # 没配直接 KeyError
```

真实代码 `src/settings.py:139-146`：

```python
DATABASE_URL: str | None = os.getenv("DATABASE_URL", None)
POSTGRES_USER: str = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT: str = os.getenv("POSTGRES_PORT", "5432")
```

而 `src/settings.py:62-66` 用 pydantic-settings 自动把 `.env` 文件加载成环境变量：

```python
model_config = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",     # ← 又是显式编码
    extra="ignore",                # 不认识的变量忽略，不报错
)
```

**这就是 01 课那个 `.env` 生效的全部原理**。优先级从高到低：

```
真实环境变量  >  .env 文件  >  Python 类里的默认值
```

所以你在 `.env` 里写 `POSTGRES_HOST=localhost` 会覆盖代码里的默认值；而如果在终端里 `export POSTGRES_HOST=1.2.3.4`，它又会覆盖 `.env`。**部署时改环境变量、本地开发改 .env**——这就是十二要素应用（12-Factor App）里的"配置外置"。

## 2B.9 IO 之五：网络 IO 的最小认知

```python
import requests

resp = requests.get("https://example.com", timeout=10)   # ★ timeout 必须写
resp.raise_for_status()          # 4xx/5xx 时抛异常（不写的话错误会被静默吞掉）
data = resp.json()               # 解析 JSON
text = resp.text                 # 拿原始文本
```

三条铁律：

1. **`timeout=` 必须写。** 不写的话，对端不响应你的程序会**永久挂住**。这是新手最常见的生产事故。
2. **`raise_for_status()` 必须写。** 否则 404/500 也会当成"成功"，然后你在解析 `resp.json()` 时才莫名其妙地崩。
3. **`requests` 是同步阻塞的。** 在 `async def` 里直接调它会**卡死整个事件循环**（第 03 课详解）。项目里 `paddle_ocr.py` 是同步函数所以没问题；一旦要放进异步流程，就得用 `asyncio.to_thread` 包起来。

### 一个值得学的细节：轮询为什么要用 `time.monotonic()`

`src/utils/paddle_ocr.py:86-90`：

```python
deadline = time.monotonic() + paddle_poll_timeout_seconds
while time.monotonic() < deadline:
    ...
    time.sleep(paddle_poll_interval_seconds)
```

**为什么不用 `time.time()`？** 因为 `time.time()` 读的是系统时钟，用户改时区、NTP 校时都会让它跳变，可能让 `while` 变成死循环。`time.monotonic()` 是**单调递增时钟**，只会前进不会回退，专门用来算"超时/间隔"。

> 记住这个模式：**凡是算耗时/超时，用 `monotonic()`；凡是记"什么时候发生的"，用 `time.time()` 或 `datetime`。** 这是后端工程师的基本素养，前端很少接触。

## 2B.10 正则速览（因为项目里到处是 `re`）

```python
import re

re.sub(r"\s+", " ", text)              # 替换：多个空白 → 一个空格
re.match(r"^abc", s)                   # 从开头匹配，返回对象或 None
re.search(r"abc", s)                   # 任意位置匹配
re.findall(r"\d+", s)                  # 找出所有匹配
re.sub(r"a", "b", s, flags=re.IGNORECASE)   # 忽略大小写

m = re.match(r"^(\w+):(\d+)$", "host:5432")
m.group(1)     # "host"
m.group(2)     # "5432"
```

项目真实案例（都在 `paddle_ocr.py` 里）：

```python
re.sub(r"[^A-Za-z0-9._-]+", "_", base)      # 白名单：不在集合里的字符全换成 _
re.sub(r"https?://\S+", "", text)           # 删掉所有 URL
re.sub(r"\n{3,}", "\n\n", text)             # 3 个以上换行压成 2 个
```

**够用就行**：你只需要能读懂 `[]`（字符集）、`^`（开头）、`+`/`*`/`?`（次数）、`\d`/`\w`/`\s`（数字/单词/空白）、`()`（分组）这几样。不要现在就去啃正则语法，遇到再查。

## 读真实代码（15 分钟）

**打开 `src/utils/paddle_ocr.py`，从上往下读一遍。** 这是本课的活教材，对照清单：

| 行号 | 你该认出的东西 |
|---|---|
| 1-10 | 导入：`json` / `re` / `time` / `Path` / `requests` / `structlog` |
| 13-21 | 函数签名与类型标注（02 课） |
| 24-25 | 参数校验 + `raise RuntimeError` |
| 37-47 | `with path.open("rb")`（2B.6）、`json.dumps(..., ensure_ascii=False)`（2B.7）、`timeout=`（2B.9） |
| 48-49 | `raise_for_status()` + `response.json()` |
| 51 | `(payload.get("data") or {}).get("jobId")`（02A 的安全取值链） |
| 86-108 | `time.monotonic()` 轮询循环 + `time.sleep()`（2B.9） |
| 113-116 | `errorCode not in (None, 0, "0")` —— 三种"零"都要认，**防御式判断的典范** |
| 119-145 | isinstance 判断树（02A） |
| 148-178 | `JSONDecodeError` 兜底解析（2B.7） |
| 181-196 | `re.sub` 清洗（2B.10）+ 文件安全（2B.6） |

读完你应该能回答："这个函数从收到一个 PDF 路径，到拿回一段 markdown，中间经历了哪些 IO？"

## 动手实验（25 分钟）

1. **验证真假值差异**：在 `sandbox/` 下写脚本，打印 `bool([])`、`bool({})`、`bool("0")`、`bool(0)`，和你在 JS 里的直觉对比。再写 `if not items:` 判断空列表。
2. **`or` 默认值陷阱**：写 `int(os.getenv("RETRIES") or 3)`，然后在终端 `export RETRIES=0` 再跑，看结果是不是你想要的；改用 `is not None` 三元式修好。
3. **读写一个中文 JSON**：把 `{"标题": "你好"}` 写入 `sandbox/test.json`（用 `ensure_ascii=False` + `encoding="utf-8"`），再读回来打印。然后故意去掉 `encoding="utf-8"` 再跑一次，观察乱码或报错——**亲眼见过一次，你以后就不会忘**。
4. **调用一次真实 HTTP**：用 `requests.get("http://localhost:2026/health", timeout=5)`（先按 01 课把服务跑起来），打印状态码和 `.json()`。再把 timeout 改成 `0.001` 观察超时异常。
5. **正则清洗**：把 `safe_filename("../../etc/passwd")` 复制到你的脚本里跑一遍，打印结果，理解为什么它安全。

## 常见坑速查

| 现象 | 原因 |
|---|---|
| 程序卡住不返回 | HTTP 请求没写 `timeout=` |
| 4xx/500 被当成功 | 没调 `raise_for_status()` |
| 中文变 `\u4e2d\u6587` | `json.dumps` 少了 `ensure_ascii=False` |
| 中文文件乱码 / `UnicodeDecodeError` | 文件 IO 少了 `encoding="utf-8"` |
| `KeyError` 读环境变量 | 用了 `os.environ["X"]`，改用 `os.getenv("X", 默认值)` |
| 配置了 `0` 却不生效 | `or` 把 `0`/`""`/`[]` 当成"没配"吃掉了，用 `is not None` |
| 空数组判断写错 | Python 里 `[]` 是假值，直接 `if not arr:` |
| `6 / 2` 得到 `3.0` | Python 的 `/` 永远返回 float，要整数用 `//` |
| 浮点比较失败 | 用 `math.isclose()`，别用 `==` |
| `round(2.5)` 是 2 | 银行家舍入，别用它做金额计算 |
| 耗时统计偶发变负 / 死循环 | 用了 `time.time()`，应改用 `time.monotonic()` |

## 自测题

1. JS 里 `[]` 是真值、Python 里是假值。这个差异会让哪些"从 JS 抄过来"的代码出 bug？
2. `a or b` 和 `a if a is not None else b` 分别在什么场景下必须用后者？
3. 为什么 HTTP 请求不写 `timeout` 是生产事故？`raise_for_status()` 又解决了什么问题？
4. 环境变量、`.env` 文件、代码里的默认值，三者优先级是什么？为什么这样设计？
5. `time.monotonic()` 和 `time.time()` 分别该用在什么场景？
6. 打开 `src/utils/paddle_ocr.py:113-116`，解释 `error_code not in (None, 0, "0")` 为什么要写三种形式。

**下一课**：[02c-python-advanced-functions.md](02c-python-advanced-functions.md) —— 进阶函数、装饰器、生成器：读懂项目里那些"看不懂的写法"。
