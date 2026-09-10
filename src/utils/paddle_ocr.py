import json
import re
import time
from json import JSONDecodeError
from pathlib import Path
from typing import Any
import requests
import structlog

logger = structlog.get_logger(__name__)


def extract_pdf_markdown_with_paddle_api(
        path: Path,
        paddle_job_url: str,
        paddle_token: str,
        paddle_model: str,
        paddle_request_timeout_seconds: int,
        paddle_poll_timeout_seconds: int,
        paddle_poll_interval_seconds: int,
) -> str:
    """ paddle ocr识别PDF文件  """

    if not paddle_job_url or not paddle_token:
        raise RuntimeError("必须配置Paddle OCR API。设置JOB_URL和TOKEN！！！")

    headers = {
        "Authorization": f"Bearer {paddle_token}",
        "Accept-Encoding": "gzip, deflate, br",
    }
    optional_payload = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": True,
        "useFormulaRecognition": True,
    }
    with path.open("rb") as file_obj:
        response = requests.post(
            paddle_job_url,
            headers=headers,
            data={
                "model": paddle_model,
                "optionalPayload": json.dumps(optional_payload, ensure_ascii=False),
            },
            files={"file": (path.name, file_obj, "application/pdf")},
            timeout=paddle_request_timeout_seconds,
        )
    response.raise_for_status()
    payload = response.json()
    _raise_for_paddle_error(payload)
    job_id = (payload.get("data") or {}).get("jobId")
    if not job_id:
        raise RuntimeError(f"Paddle OCR response did not include jobId: {payload}")

    # 轮训job
    result = _wait_for_paddle_result(requests, headers, job_id, paddle_job_url, paddle_request_timeout_seconds, paddle_poll_timeout_seconds, paddle_poll_interval_seconds)

    markdown_url = ((result.get("data") or {}).get("resultUrl") or {}).get("markdownUrl")
    if markdown_url:
        markdown_response = requests.get(markdown_url, timeout=paddle_request_timeout_seconds)
        markdown_response.raise_for_status()
        markdown_text = markdown_response.text.strip()
        if markdown_text:
            return markdown_text

    json_url = ((result.get("data") or {}).get("resultUrl") or {}).get("jsonUrl")
    if json_url:
        json_response = requests.get(json_url, timeout=paddle_request_timeout_seconds)
        json_response.raise_for_status()
        return _extract_markdown_from_payload(_parse_paddle_json_response(json_response.text))

    return _extract_markdown_from_payload(result)


def _wait_for_paddle_result(
        requests_module: Any,
        headers: dict[str, str],
        job_id: str,
        paddle_job_url: str,
        paddle_request_timeout_seconds: int,
        paddle_poll_timeout_seconds: int,
        paddle_poll_interval_seconds: int
) -> dict[str, Any]:
    """ 轮训Paddle OCR结果  """

    deadline = time.monotonic() + paddle_poll_timeout_seconds

    status_url = f"{paddle_job_url.rstrip('/')}/{job_id}"
    last_payload: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        response = requests_module.get(
            status_url,
            headers=headers,
            timeout=paddle_request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        _raise_for_paddle_error(payload)
        last_payload = payload
        data = payload.get("data") or {}
        state = str(data.get("state") or data.get("status") or "").lower()
        if state in {"done", "completed", "success", "succeeded"}:
            return payload

        if state in {"failed", "error", "canceled", "cancelled"}:
            raise RuntimeError(f"Paddle OCR job failed: {payload}")

        time.sleep(paddle_poll_interval_seconds)
    raise TimeoutError(f"Paddle OCR job timed out: job_id={job_id}, last_payload={last_payload}")



def _raise_for_paddle_error(payload: dict[str, Any]) -> None:
    error_code = payload.get("errorCode")
    if error_code not in (None, 0, "0"):
        raise RuntimeError(f"Paddle OCR API error: {payload}")


def _extract_markdown_from_payload(payload: Any) -> str:
    if isinstance(payload, str):
        return payload

    if isinstance(payload, list):
        return "\n\n".join(_extract_markdown_from_payload(item) for item in payload if item)

    if not isinstance(payload, dict):
        return ""

    for key in ("markdown", "md", "content", "text", "recognizedText"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    data = payload.get("data")
    if data is not None:
        text = _extract_markdown_from_payload(data)
        if text:
            return text

    parts: list[str] = []
    for value in payload.values():
        text = _extract_markdown_from_payload(value)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _parse_paddle_json_response(text: str) -> Any:
    """Parse Paddle JSON output that may be JSON, JSONL, or concatenated JSON."""
    stripped = text.strip()
    if not stripped:
        return ""

    try:
        return json.loads(stripped)
    except JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    items: list[Any] = []
    index = 0
    length = len(stripped)
    while index < length:
        while index < length and stripped[index].isspace():
            index += 1

        if index >= length:
            break
        try:
            item, next_index = decoder.raw_decode(stripped, index)
        except JSONDecodeError:
            logger.warning("paddle_json_parse_fallback_to_text", offset=index)
            return stripped

        items.append(item)
        index = next_index

    return items if len(items) != 1 else items[0]


def safe_filename(filename: str) -> str:
    """ 文件名称安全过滤 """
    base = Path(filename).name.strip() or "document.pdf"
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    return base if base.lower().endswith(".pdf") else f"{base}.pdf"


def clean_ocr_markdown(text: str) -> str:
    """ 清理OCR识别的Markdown文本 """
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", " ", text)
    text = re.sub(r"\b(?:header|header_image|footer|footer_image|aside_text|footnote|number)\b", " ", text)
    text = re.sub(r"\b(?:pdf|success)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
