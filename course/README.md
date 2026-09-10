# 🧭 Agent 后端开发课程 · 课程地图

> **你是谁**：前端开发者，会 JS/TS、会用 npm/pnpm、懂浏览器，但没写过后端，没写过 Python。
> **你想干什么**：通过读懂并改造当前这个真实项目（Aegra-Api），学会 AI Agent 后端开发。
> **这套课是什么**：17 节课 + 配套示例文件，从「搭环境」一路到「自己造一个 Agent」，每节课都对着**本仓库的真实代码**讲。

---

## 一、这个项目是什么（先建立画面感）

Aegra-Api 是一个 **Agent 后端服务**，你可以把它理解为 **「Agent 的 Node.js 后端框架」**：

| 前端世界的熟悉概念 | 这里的对应物 |
|---|---|
| Express / NestJS | **FastAPI**（Python 的 Web 框架） |
| 一个"会思考"的接口（LLM 调用 + 工具调用循环） | **LangGraph 图**（一个可持久化、可流式执行的图） |
| npm scripts / vite dev | `uv` + `uvicorn` |
| localStorage / IndexedDB | **PostgreSQL**（会话状态、长记忆） |
| 内存缓存 / 消息队列（BullMQ 之类） | **Redis** |
| 给推荐系统用的"相似度搜索" | **Qdrant**（向量数据库，RAG 的知识库） |
| EventSource / fetch stream 读流 | **SSE**（服务器向浏览器推流） |
| Chrome DevTools / React Query 缓存 | 结构化日志 + OpenTelemetry + 图缓存/热加载 |

**它解决的业务问题**：把"LLM 对话 + 调用工具 + 知识库检索 + 长会话记忆 + 流式输出 + 高并发"这些 Agent 开发里最麻烦的事，封装成一组标准 REST API（`/assistants`、`/threads`、`/runs`、`/store`、`/rag`），并让多个 Agent（LangGraph 图）可以热 插拔。

## 二、课程路线图（按阶段推进，别跳课）

```
阶段 0 认知准备
  ├─ README.md（本文件）       课程地图与学习方法
  │
阶段 1 地基：环境 + 语言 + 异步 + Web 框架（第 01~04 课）
  ├─ 01-environment-setup      Windows 环境搭建：Python/uv/Docker/VSCode，把项目跑起来
  ├─ 02-python-essentials      Python 速成：给会 JS 的你一份对照语法表
  ├─ 03-async-coroutines       异步协程：从 JS 事件循环到 Python asyncio
  └─ 04-fastapi-first-api      用 FastAPI 写第一个 API（对照 Express）
  │
阶段 2 骨架：读懂这个大仓库是怎么组织起来的（第 05~07 课）
  ├─ 05-project-map-startup    项目目录结构 + main.py 启动流程（lifespan）
  ├─ 06-postgres-orm           PostgreSQL + SQLAlchemy(async) + Alembic 迁移
  └─ 07-redis-broker           Redis：缓存、Pub/Sub 消息代理（Broker）
  │
阶段 3 核心：LangGraph 智能体（第 08~11 课）★ 本项目最核心
  ├─ 08-langgraph-mental-model LangChain/LangGraph 心智模型：图、状态、节点、边
  ├─ 09-react-loop             ReAct：规划→思考→执行→验证 循环（读 graph.py）
  ├─ 10-agent-orchestration    多智能体编排：图缓存 + 热加载 + 运行时注入
  └─ 11-memory-checkpoint-hitl 常记忆 + Checkpoint + 消息裁剪/压缩 + 人工审查(HITL)
  │
阶段 4 RAG：让 Agent 拥有"知识库"（第 12~13 课）
  ├─ 12-rag-theory             RAG 原理：Embedding、向量检索、chunk 分块
  └─ 13-rag-pipeline           RAG 落地全流程：上传→OCR→清洗→分块→Embedding→Qdrant→检索
  │
阶段 5 工程化：流式、并发、可观测（第 14~16 课）
  ├─ 14-sse-streaming          SSE 流式推送 + 断点续传
  ├─ 15-concurrency-engine     高并发执行引擎：信号量、租约、Worker、Broker
  └─ 16-testing-observability  测试(pytest) + 调试 + 可观测性(OpenTelemetry)
  │
阶段 6 毕业（第 17 课）
  └─ 17-capstone               综合实战：从 0 造一个属于你自己的智能体
```

## 三、学习建议（写给前端背景的你）

1. **不要试图背语法**。看到不会的 Python 语法去第 02 课查对照表，其余时间一直在"读真代码 + 改真代码"。
2. **每课动手 > 每课阅读**。每课都有【动手实验】，做不出来就读报错、查本课【常见坑】。报错是你最好的老师。
3. **只求"能改"，不求"能默写"**。你的目标是能在这个仓库里**加一个工具、换一个模型、写一个新 Agent 图、调通一次流式输出**。理解主线即可，旁支（如 cron、租约）能说出大概就行。
4. **主线自检**（学完第 17 课你应该能回答）：
   - 一条消息从浏览器/curl 进来，代码是怎么一步步走到 LLM、再流式返回的？
   - 为什么换一个 Agent 只需要改 `aegra.json`？图缓存和热加载在哪里？
   - 会话为什么"重启服务还在"？Checkpoint 存在哪张表里？
   - 一个 PDF 上传后，RAG 的每一段代码做了什么？检索为什么比关键词搜索"懂语义"？
   - SSE 是怎么做到断线后能续传的？
5. **善用仓库自带材料**：`README.md`（71KB 中文架构文档）是这套课的"官方参考书"；`tests/` 下有 170 个测试文件，是最好的"代码行为说明书"。

## 四、约定

- 课程里所有相对路径，均以仓库根目录 **`agent-api-master/`（含 `main.py` 的那一层）** 为基准。
- 环境变量默认值以 `src/settings.py` 为准，本课程的 `.env.example` 与之一致。
- 每课结构固定：**本课目标 → 讲解 → 读真实代码 → 动手实验 → 常见坑 → 自测题**。

> 现在，打开第 01 课，把环境搭起来，跑通你的第一个 Agent API 🚀
