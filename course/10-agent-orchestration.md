# 第 10 课 · 多智能体编排引擎：图缓存 + 热加载 + 运行时注入（核心点 2）

> 目标：吃透项目核心点 2。学完你能回答三件事：**① 同一个进程里怎么同时托管 N 个智能体图？② 改了图代码怎么不重启就生效？③ 为什么"一个图"能服务"一千个配置不同的 Assistant"而不串数据？**
> 主战场：`aegra.json` + `src/services/langgraph_service.py` + `src/services/graph_factory.py`。

---

## 10.1 编排引擎要解决的三个问题

假设你的产品有 3 个 Agent：客服、写作助手、RAG 问答。如果直接"import 三个图、各跑各的"，会撞上三堵墙：

| 问题 | 普通做法 | 本项目的解法 |
|---|---|---|
| 图要**反复执行**，每次都重新编译很贵 | 不管，慢 | **图缓存**：编译好的图放内存字典，按 graph_id 取 |
| 改图代码要**重启服务**才生效 | 手动重启 | **热加载**：清缓存 → 按 `aegra.json` 重新加载模块 |
| 同一张图被不同用户/不同配置的 Assistant 共用，**会串状态/串配置** | 不敢共用，复制图代码 | **运行时注入**：每请求从"基础图"深拷贝一份，注入各自 checkpointer/store/上下文 |

## 10.2 图注册表 aegra.json：多智能体的"入口清单"

```json
{ "graphs": { "agent": "./src/agents/react_agent/graph.py:graph" } }
```

字段含义：`graph_id`（`agent`）→ `文件路径:变量名`（`graph.py` 里的 `graph`）。将来加一个写作 Agent，只要加一行：

```json
{ "graphs": {
    "agent":  "./src/agents/react_agent/graph.py:graph",
    "writer": "./src/agents/writer_agent/graph.py:graph"
}}
```

这就是**多智能体架构的入口约定**：路由层只知道 `graph_id`（`POST /assistants` 时传 `"graph_id": "writer"`），不知道也不关心背后是哪个 Python 文件。

## 10.3 LangGraphService：看图怎么被管理（读 `src/services/langgraph_service.py`）

这个类是本课主角。先看它的状态（`__init__`，第 67~79 行）：

```python
class LangGraphService:
    def __init__(self, config_path=None):
        self.config_path = ...            # 默认读根目录 aegra.json
        self._base_graph_cache: dict[str, Pregel] = {}   # ⭐ 图缓存：编译好的"基础图"
        self._graph_factories: dict = {}                  # ⭐ 工厂函数缓存（见 10.5）
```

再看方法调用链（对照文件里的方法名）：

```
initialize()                    # 启动时（main.py lifespan 第 4 步）
 ├─ _load_graph_registry()      # 读 aegra.json，得到 {graph_id: 文件路径}
 └─ _load_all_graph_modules()   # 逐个 import 模块 → 拿到编译好的图
     └─ 静态图存入 _base_graph_cache[graph_id]
```

### 缓存为什么分"基础图"和"请求图"两层？

核心设计在 `get_graph()`（第 305 行起，注释写得很清楚）：
- `_base_graph_cache[graph_id]` 存**没挂 checkpointer/store 的"裸图"**（不可变、可安全复用）；
- 每次 `get_graph()` 时：取出基础图 → `graph.copy(update={"checkpointer": ..., "store": ...})` **复制一份并注入**本次请求所需的持久化组件 → 返回给执行器。

> 为什么要 copy 而不是直接用基础图？因为 checkpointer/store 里带着**本次会话的身份**。如果大家共享同一个编译实例，A 用户的对话状态就可能串到 B 用户——**并发下最经典的隐性 bug**。每请求一份副本 = 彻底隔离。

（对照前端：相当于"组件模板"与"实例"的区别——模板只定义一次，每次渲染 new 一个实例。）

### 热加载 invalidate_cache()

第 598 行：

```python
def invalidate_cache(self, graph_id=None):
    """graph_id=None 时清空全部；否则只清指定图"""
    # 清 _base_graph_cache 与 _graph_factories 里对应的项
```

清完缓存后，下一个请求再 `get_graph()` 会发现缓存未命中 → 回到 `aegra.json` **重新加载模块**（注释里写：`_load_graph_from_file` 失败/未命中时会重新加载）→ 新代码生效。**这就是"热加载"：不用重启进程就能让图代码变更生效**。目前它主要被测试与管理工具调用；生产上你可以再包一个管理端点（如 `POST /admin/graphs/reload`）来触发。

## 10.4 运行时注入：Context 是怎么"长"进节点里的

回顾第 08 课的节点签名：

```python
async def call_model(state: State, runtime: Runtime[Context]) -> dict:
    model = load_chat_model(runtime.context.model)   # runtime.context 从哪来？
```

**LangGraph 的机制**：`builder.compile(context_schema=Context)` 声明了"图运行时需要一个 Context"。执行时框架从执行配置里解析出该 Assistant 的 context 数据 → 构造 `Runtime[Context]` → **注入每个节点的第二个参数**。这样：
- 图代码（graph.py）**完全不关心**调用者是哪个 Assistant；
- 每个 Assistant 只要在创建时提交自己的 `context`（model、system_prompt、max_search_results……），运行时就自动生效。

（对照前端：Context ≈ React 的 Context/依赖注入，节点函数 ≈ 组件——组件不自己找配置，配置由上层注入。）

## 10.5 图工厂 graph_factory.py：图的另一种注册形态

有些图不是"直接编译好的变量"，而是**工厂函数**（运行时才根据参数造图）。`src/services/graph_factory.py` 用 `inspect.signature` 反射函数的参数签名，把工厂分成几类，**自动决定调用时给它传什么**：

- 0 参数工厂：`() -> graph`，直接调；
- 1 参数：`(config) -> graph`，传配置；
- 2 参数：`(config, runtime) -> graph` 或带 `ServerRuntime[Context]` 的形态——**把"每个请求的上下文"传进工厂**，工厂可以据此动态组装子图/路由。

> 现在只求理解概念：**"工厂 + 反射分类 + 上下文注入"让本项目能托管"静态图"之外的"动态组装图"**，这是多智能体框架比"写死一张图"高级的地方。第 17 课你写自己的图时，用静态图（10.2 那种一行注册）即可。

## 10.6 动手实验：注册你自己的"第二个图"（体验多智能体）

1. 复制 `src/agents/react_agent/` 的 graph.py 成 `src/agents/hello_agent/`（先只复制 graph.py、state.py、context.py、prompts.py、utils.py、tools.py，或干脆从一个最小 graph 开始——**不用**，直接复制整套最简单）。
2. 把 `aegra.json` 改成注册两个图：
   ```json
   { "graphs": {
       "agent":  "./src/agents/react_agent/graph.py:graph",
       "hello":  "./src/agents/hello_agent/graph.py:graph"
   }}
   ```
3. 重启服务，用第 01 课的 requests.http **新建一个 `graph_id="hello"` 的 Assistant**，跑一轮对话。
4. 再试试"热加载"：改 hello_agent 的 system prompt（如把"用一句话回复"加进去），然后调用 `uv run python -c "from src.services.langgraph_service import get_langgraph_service; s=get_langgraph_service(); import asyncio; asyncio.run(s.initialize()); s.invalidate_cache('hello'); print('cleared')"`（或直接在测试里触发），观察新 prompt 是否在**不重启**的情况下生效。

> 提示：新增 `src/agents/hello_agent/` 后，若 import 报错，多半是文件内部 `from src.agents.react_agent.xxx import ...` 的路径要改成 `hello_agent`。

## 10.7 常见坑
- **改 aegra.json 不生效**：图在启动 initialize 时加载，改完要重启或调用 invalidate。
- **图加载失败整个服务起不来**：lifespan 第 4 步出错会抛异常（第 05 课自测题 1），先单独 `uv run python -c "import <你的模块>"` 验证模块能 import。
- **"图会串数据"的恐惧**：项目已用"每请求 copy + 注入 checkpointer/store"隔离，你自己写图时**不要**在模块顶层存可变全局状态（那才是真会串）。

## 自测题
1. `_base_graph_cache` 里存的是"裸图"还是"挂了 checkpointer 的图"？为什么这样分层？
2. `get_graph()` 每次请求都做什么？copy 的意义是什么？
3. `invalidate_cache()` 清空后，下一个请求会发生什么（提示：缓存未命中 → 重新走 aegra.json 加载）？
4. 一个 Assistant 的 `context`（比如 `model` 字段）最终是怎么出现在 `call_model` 函数里的？（提示：Runtime → runtime.context）
5. 图工厂为什么需要按参数个数分类？2 参数工厂比 0 参数工厂多拿到了什么？

**下一课**：[11-memory-checkpoint-hitl.md](11-memory-checkpoint-hitl.md) —— 常记忆 + Checkpoint + 消息裁剪/压缩 + 人工审查（核心点 4）。
