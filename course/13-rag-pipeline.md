# 第 13 课 · RAG 落地全流程：OCR → 清洗 → 分块 → Embedding → Qdrant（核心点 5）

> 目标：把第 12 课的概念对到项目真实代码上，逐段读懂 `src/services/rag_service.py` + `src/utils/paddle_ocr.py`，并亲自上传一个 PDF 走通全流程。学完你能画出"一个 PDF 从上传到能被 Agent 检索"的完整数据流。这是项目核心点 5 的完整落地。

---

## 13.1 全流程总览（先记住这张图）

```
用户上传 PDF
  │  POST /rag/documents（src/api/rag.py）
  ▼
① save_pdf：存本地临时文件
  ▼
② PaddleOCR 识别（异步线程池）：PDF → 图片/版面 → 文本 + Markdown
     src/utils/paddle_ocr.py：提交 Job → 轮询 → 取回 Markdown
  ▼
③ 文本清洗 clean_ocr_markdown：去噪声（页眉/乱码/多余换行…）
  ▼
④ 文本分块 chunk_text：chunk_size=2000, overlap=200
  ▼
⑤ Embedding 并发批处理：分小批 → asyncio.Semaphore(3) 限流 → 算向量
  ▼
⑥ upsert 进 Qdrant：点 = 向量 + payload(原文/user_id/文件名)
  ═══════════════════════════════════════════════
用户提问 → ⑦ search：问题也 Embedding → Qdrant 按 user_id 过滤 + TopK
        → 原文 chunks 回给 Agent（react_agent 的 rag_search 工具用它）
```

**两个入口你要分清**：
- `POST /rag/documents`：上传入库（走 ①~⑥）；
- `POST /rag/search` 或 Agent 的 `rag_search` 工具：检索（走 ⑦）。
`rag_service.py` 开头的 `RagSettings` 就是这些步骤的参数面板（chunk 大小、OCR 地址、collection 名……都能用环境变量覆盖）。

## 13.2 逐段读代码：src/services/rag_service.py

打开文件对照以下关键点（都是真代码，边看边标）：

### ① `ingest_pdf`（第 84 行起）——异步编排的"主线函数"
```python
async def ingest_pdf(self, document, user_id):
    # OCR：同步网络轮询 → asyncio.to_thread 丢线程池，别卡事件循环
    text = await asyncio.to_thread(self._ocr_pdf, document)   # 实际调 paddle_ocr 封装
    text = self._clean_text(text)          # ③ 清洗
    chunks = self._chunk_text(text, ...)   # ④ 分块
    vectors = await self._embed_documents(chunks)  # ⑤ Embedding（真正 async）
    await asyncio.to_thread(self._upsert_chunks, document, user_id, chunks, vectors)  # ⑥ Qdrant（同步客户端）
```
注意它怎么用第 03 课的知识：**同步的 OCR 轮询和 Qdrant 写入用 `to_thread` 丢线程池，异步的 Embedding 网络调用直接 await**——这就是"全栈异步 + IO 线程池"在一个函数里的缩影。

### ② OCR 的异步线程处理（`src/utils/paddle_ocr.py`）
PaddleOCR 是远程服务，封装做的是：**提交识别 Job → 轮询状态（`asyncio` 或带超时的循环）→ Job 完成取回识别文本（Markdown 格式）→ `clean_ocr_markdown` 清洗**。
（settings 里 `PADDLE_OCR_POLL_INTERVAL_SECONDS=3`、`PADDLE_OCR_POLL_TIMEOUT_SECONDS=600` 控制轮询节奏。识别大 PDF 可能要几分钟，所以绝不能同步阻塞在请求里。）

> 想本地体验 OCR 而不想连远程服务？PaddleOCR 有开源本地版（`pip install paddleocr paddlepaddle`），第 17 课可以把它接进来当"第二个 OCR 实现"。本课先用项目默认的远程 API。

### ③ `_clean_text` / `clean_ocr_markdown`——清洗
OCR 结果很脏：多余空行、页眉页脚、识别错的乱码、Markdown 残留标记。清洗函数做正则/规则清理，**给分块器干净的输入**。清洗质量直接决定后面检索质量——这是 RAG 里最"脏活累活"却最影响效果的一步。

### ④ `_chunk_text`（第 276 行起）——滑动窗口分块
```python
def _chunk_text(self, text, chunk_size, overlap):
    # 滑窗：每段 chunk_size，下一段从 end-overlap 开始（保住跨块语义）
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        start = max(end - overlap, start + 1)   # 重叠 200
```
就是第 12 课讲的滑动窗口，代码不过 10 行。

### ⑤ `_embed_documents`（第 165 行起）——并发批处理 + 信号量 ★
```python
semaphore = asyncio.Semaphore(3)        # ⭐ 同时最多 3 个 Embedding 请求
async def embed_batch(batch_index, batch):
    async with semaphore:               # 限流：防止把 Embedding API 打爆
        ... # 调模型算这一批的向量
results = await asyncio.gather(*[embed_batch(i, b) for i, b in enumerate(batches)])
```
**这就是"Embedding 并发批处理"**：把 chunks 切成小批 → `gather` 并发 → `Semaphore(3)` 限流。gather 保证总耗时接近"批次数/3 × 单批耗时"，而不是"批次数 × 单批耗时"。

### ⑥ `_upsert_chunks` / `_ensure_collection`（第 151 / 207 行起）——写 Qdrant
- `_ensure_collection`：collection 不存在就 `create_collection`（指定向量维度、距离度量）。
- `_upsert_chunks`：每条 chunk → 一个 Point = `vector + payload`。**payload 里带 `user_id`** ——多租户数据隔离靠它（检索时按 user_id 过滤，第 10 课"隔离"思想的又一实例）。
- 用同步 qdrant-client，所以在 async 里被 `to_thread` 包着。

### ⑦ `search`（第 121 行起）——检索
问题文本 → `_embed_query`（同样要 embedding）→ `_search_qdrant`：**payload 过滤器（user_id）+ Top-K 最近邻** → 返回 chunks（原文 + 分数）。`src/agents/react_agent/tools.py` 的 `rag_search` 工具就调它，把结果拼给 LLM 当参考资料（第 09 课的 tools 闭环回来了）。

## 13.3 动手实验：上传一个 PDF 并让 Agent 用它回答

1. 准备一个 PDF（几页含文字的即可，如把本仓库 README 导出成 PDF）。
2. 用 REST Client 上传（在 requests.http 追加）：
```http
### 上传 PDF 入库
POST http://localhost:2026/rag/documents
Content-Type: multipart/form-data; boundary=----wb

------wb
Content-Disposition: form-data; name="file"; filename="README.pdf"
Content-Type: application/pdf

< 你的.pdf 文件路径（REST Client 支持从磁盘引用，或先用 curl -F）
------wb--
```
（curl 版：`curl -F "file=@README.pdf" http://localhost:2026/rag/documents`）
3. 等入库完成（日志里能看到 OCR/embed/upsert 步骤；大文件多等一会儿）。
4. 检索验证：`POST /rag/search` body `{"query": "项目用的向量数据库是什么", "limit": 3}`，看返回的 chunks 是否相关。
5. 终极验证：让 Agent 用 rag_search 工具回答"**根据项目资料，本项目用了哪些中间件？**"——如果它引用文档回答而不是瞎编，**RAG 全链路打通** ✅
6. 打开 http://localhost:6333/dashboard 看 collection 里的点数、payload（user_id/原文）。

## 13.4 常见坑
- **Qdrant 连不上/默认地址错误**：`src/services/rag_service.py` 里 QDRANT_URL 默认值是作者局域网地址 `http://192.168.2.14:6333`，**务必在 .env 覆盖成 `http://localhost:6333`**（01 课的模板已配好）。
- **Embedding/OCR 一直 401/403**：.env 里的 `OPENAI_API_KEY`（embedding 也用同一个）、`PADDLE_OCR_TOKEN` 要有效。再次提醒：仓库源码里**硬编码了默认密钥**（rag_service.py 第 37、49 行），用 .env 覆盖它是正确姿势，也请别把它提交到公开仓库。
- **上传成功但搜不到**：等 ingest 真正跑完（看日志）；确认 search 的 user_id 与上传时一致（多租户隔离生效的表现）。
- **中文效果差**：考虑换更懂中文的 Embedding 模型或调 chunk 参数——这就是 `RagSettings` 存在的意义。

## 自测题
1. `ingest_pdf` 里哪些步骤是 `await asyncio.to_thread`？哪些是原生 async？为什么这样分工？
2. `Semaphore(3)` 在 Embedding 批处理里解决什么问题？没有它会怎样？
3. Qdrant 的 payload 里为什么要存 user_id？
4. `rag_search` 工具把什么喂给了 LLM？这和"直接回答"有什么不同？
5. 如果识别出的文本有大量重复页眉，会影响检索吗？该在哪一步处理？

**下一课**：[14-sse-streaming.md](14-sse-streaming.md) —— SSE 流式推送 + 断点续传（核心点 3）。
