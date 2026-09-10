# 第 04 课 · FastAPI：用 Python 写你的第一个 Web API

> 目标：理解 FastAPI 的核心概念（路由、Pydantic、依赖注入、中间件），**从 0 写一个能跑的小服务**，然后回看本项目 `main.py` 是怎么组织起来的，为第 05 课的项目结构课铺路。前端类比：**FastAPI ≈ Express/NestJS，但类型与文档自动生成更接近 tRPC + OpenAPI**。

---

## 4.1 三个"你一定会喜欢"的特性

1. **声明式校验**：用 Python 类型标注/Pydantic 定义入参出参，FastAPI 自动做请求解析、校验、错误返回（400/422），顺便**自动生成 Swagger 文档**（`/docs`）。
2. **原生 async**：路由函数可以 `async def`，直接享受第 03 课的协程并发，不用像 Express 那样纠结。
3. **依赖注入（DI）**：`Depends(...)` 给路由"注入"依赖——本项目的数据库会话、鉴权、用户上下文全部靠它，相当于 NestJS 的 `@Injectable` 精简版。

## 4.2 最小可运行示例（对照 Express）

```python
# sandbox/app_demo.py
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel

app = FastAPI(title="My First API")

# ---- 请求体模型：TS interface + zod 二合一 ----
class ChatIn(BaseModel):
    message: str                    # 必填 str
    max_tokens: int = 256           # 可选，默认 256

class ChatOut(BaseModel):
    reply: str
    echo_length: int

# ---- 一个"伪依赖"：以后会换成数据库会话 ----
def get_db():
    # FastAPI 会在每次请求时调用；yield 前的代码=进入,后的=退出
    print("open session")
    yield {"session": "db-1"}
    print("close session")

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/chat", response_model=ChatOut)
async def chat(body: ChatIn, db: dict = Depends(get_db)):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="message 不能为空")
    return ChatOut(reply=f"echo: {body.message}", echo_length=len(body.message))
```

跑起来：`uv run uvicorn sandbox.app_demo:app --reload --port 8000`
（uvicorn 命令格式：`模块路径:app变量`，`sandbox/app_demo.py` 的 app → `sandbox.app_demo:app`）

打开 http://localhost:8000/docs 体验三件事：
- 自动文档：POST /chat 的请求/响应 schema 已生成，可点 **Try it out** 直接调；
- 发一个缺 `message` 的 body → 自动 422 且错误信息结构清晰；
- `get_db` 依赖在每次请求进出时打印 open/close（日志在终端），体会 DI 生命周期。

> 如果你把路由函数改成**同步** `def chat(...)`（去掉 async），FastAPI 会自动把它丢进线程池执行——这就是 3.5 节"同步代码不卡事件循环"的官方兜底机制。**小知识**：路由里凡是有 `await` 都要 `async def`；纯 CPU 或同步 IO 的小函数用普通 `def` 反而更安全。

## 4.3 FastAPI vs Express 对照表

| Express/NestJS 概念 | FastAPI 概念 | 本项目里的样子 |
|---|---|---|
| `app.use(router)` | `app.include_router(router)` | `main.py` 里 include 8 个 router |
| `router.get('/x')` | `@router.get("/x")` + 函数 | `src/api/runs.py` 等 |
| 中间件 middleware | `app.add_middleware(...)` | CORS / 日志 / CorrelationId |
| NestJS DI / Provider | `Depends(...)` | `Depends(get_session)`、`Depends(get_current_user)` |
| `class-validator` DTO | Pydantic `BaseModel` | `src/models/*.py` |
| OpenAPI/Swagger 插件 | **内置** `/docs` | 第 01 课你已经打开过 |
| 生命周期 onModuleInit/onModuleDestroy | `lifespan` 上下文管理器 | `main.py` 的 `lifespan()` |
| 鉴权 Guard | `Depends(auth_dependency)` | 每个 router 声明 `dependencies=[auth_dependency]` |

## 4.4 读真实代码：本项目一个 API 路由长什么样

打开 `src/api/threads.py`（节选心智，不必逐行）：

```python
router = APIRouter(tags=["Threads"], dependencies=auth_dependency)
#            ↑ 路由分组 + 整组路由统一挂鉴权（像 NestJS Controller 上的 Guard）

@router.post("/threads", response_model=Thread, responses={**CONFLICT})
async def create_thread(
    body: ThreadCreate,                                  # Pydantic 自动校验请求体
    session: AsyncSession = Depends(get_session),        # DI：异步数据库会话
    user: User = Depends(get_current_user),              # DI：当前登录用户（鉴权）
) -> Thread:
    ...
```

看懂这三件事就够用了：
1. `body: ThreadCreate` —— 请求体被 Pydantic 校验成对象（对照 `ThreadCreate` 见 `src/models/threads.py`）；
2. `Depends(get_session)` —— FastAPI 注入一个**异步数据库会话**（第 06 课展开），用完自动关；
3. 返回类型标注 `-> Thread` —— 自动序列化成 JSON 响应（`response_model`）。

**你会在几乎所有路由文件里看到同款结构**：`session`（数据库） + `user`（当前用户）两个依赖，然后查库/写库，返回 Pydantic 模型。

## 4.5 lifespan：启动/关闭时做什么

本项目大量"开机自启"逻辑都集中在 `main.py` 的 `lifespan()` 里（第 05 课精读）。先建立概念：

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- 启动阶段（等价 NestJS onApplicationBootstrap）----
    print("running DB migrations ...")
    print("connecting pools / loading graphs / starting workers ...")
    yield                      # 服务正式对外提供服务，直到进程退出
    # ---- 关闭阶段（优雅停机：按依赖倒序关）----
    print("stopping workers, closing DB ...")
```

FastAPI 创建时传 `lifespan=lifespan`，上述代码就在进程生命周期内执行。**本项目所有"中间件、图、执行器、Broker"的启停顺序都写在这里**，是你理解整个项目最重要的一个函数。

## 4.6 动手实验：给"伪 Agent"加两个接口

在 `sandbox/app_demo.py` 基础上扩展（或新建文件）：
1. 加一个 `GET /threads/{thread_id}` 路径参数接口，返回 `{"thread_id": ..., "found": True}`；
2. 加一个内存 `dict` 当"简易线程存储"，`POST /messages` 把消息 append 进 dict，`GET /messages/{thread_id}` 读出来——**体会"服务端保存状态"与前端 localStorage 的本质区别**；
3. 给其中一个接口加 `Depends` 依赖（比如打印日志的依赖），看它在每次请求时执行；
4. 故意传错类型（如把 int 字段传成字符串），观察自动 422 响应，并到 `/docs` 看错误 schema。

## 4.7 常见坑
- **启动报 `ModuleNotFoundError`**：uvicorn 的模块路径要相对你**当前目录**写对（`sandbox.app_demo:app`），且要在仓库根目录跑（依赖装在 `.venv`）。
- **改了代码不生效**：开发时带 `--reload`；生产不带。
- **`Depends` 里写成了 `Depends(get_db())`**（多了括号）——要传**函数本身**，不是调用结果。
- **忘记 response_model**：FastAPI 也会序列化 dict 返回，但少了类型约束与文档，团队项目规范是"一律标注"。

## 自测题
1. `@router.post("/threads/{thread_id}/runs")` 里，路径参数、请求体、依赖注入三者怎么在函数签名里体现？
2. 路由函数什么时候用 `async def`，什么时候用普通 `def` 反而更好？
3. lifespan 的 `yield` 前后分别做什么？为什么关闭阶段要"倒序"关组件（提示：先停依赖别人的人）？
4. 打开 `src/api/assistants.py` 的 `POST /assistants`，指出它的请求体模型、依赖、响应模型分别是什么。

**下一课**：[05-project-map-startup.md](05-project-map-startup.md) —— 把整个项目的目录结构与启动流程完整读一遍。
