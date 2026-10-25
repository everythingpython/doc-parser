"""Parser adapters: each takes a file path and returns (markdown, seconds)."""
import json
import os
import time
from pathlib import Path

LLAMA_BASE = "https://api.cloud.llamaindex.ai/api/v2/parse"
LLAMA_TIERS = ["cost_effective", "fast", "agentic", "agentic_plus"]

_docling_converter = None


def run_docling(path: Path):
    """Local parsing with Docling. Nothing leaves your machine."""
    global _docling_converter
    if _docling_converter is None:
        from docling.document_converter import DocumentConverter

        _docling_converter = DocumentConverter()
    start = time.perf_counter()
    result = _docling_converter.convert(str(path))
    markdown = result.document.export_to_markdown()
    return markdown, time.perf_counter() - start


def run_docling_html(path: Path):
    """Same Docling conversion, exported as HTML instead of markdown.
    HTML tables can carry merged cells (rowspan/colspan); markdown pipe tables cannot."""
    import re

    global _docling_converter
    if _docling_converter is None:
        from docling.document_converter import DocumentConverter

        _docling_converter = DocumentConverter()
    start = time.perf_counter()
    result = _docling_converter.convert(str(path))
    html = result.document.export_to_html()
    secs = time.perf_counter() - start
    html = re.sub(r"<head>.*?</head>", "", html, flags=re.S)  # drop CSS so it is not scored as text
    return html, secs


_vlm_converter = None


def run_docling_vlm(path: Path):
    """Docling's vision-model pipeline (Granite-Docling, runs locally). It reads page images
    instead of using the classic layout + table models. Exported as HTML to keep merged cells."""
    import re

    global _vlm_converter
    if _vlm_converter is None:
        from docling.datamodel import vlm_model_specs
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import VlmPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.pipeline.vlm_pipeline import VlmPipeline

        try:
            import mlx_vlm  # noqa: F401  (Apple Silicon)
            spec = vlm_model_specs.GRANITEDOCLING_MLX
        except ImportError:
            spec = vlm_model_specs.GRANITEDOCLING_TRANSFORMERS
        print(f"           VLM model spec: {spec.repo_id}", flush=True)
        _vlm_converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_cls=VlmPipeline,
                    pipeline_options=VlmPipelineOptions(vlm_options=spec),
                )
            }
        )
    start = time.perf_counter()
    result = _vlm_converter.convert(str(path))
    html = result.document.export_to_html()
    secs = time.perf_counter() - start
    html = re.sub(r"<head>.*?</head>", "", html, flags=re.S)
    return html, secs


_paddle_vl = None


def run_paddleocr_vl(path: Path):
    """PaddleOCR-VL-1.6 (0.9B, Apache 2.0), local. PP-DocLayoutV3 finds regions on each page
    image, then the VLM reads each region; tables come out as HTML. Uses Paddle's own
    inference backend on the local GPU (vLLM/SGLang do not run natively on Windows).

    Low-VRAM settings: GPUs without bfloat16 (RTX 20xx) load the model in float32 (~4 GB), so
    pages go through one at a time (the default queues 64, layout model 8 per batch).
    PADDLE_VL_MAX_PIXELS optionally lowers the per-region image cap (pipeline default 1003520,
    ~1.0 MP); lower values save memory but can blur small table text.
    PADDLE_VL_SERVER_URL sends the VLM step to a server instead (default backend llama-cpp-server,
    override with PADDLE_VL_BACKEND); only the small layout model then runs in this process."""
    global _paddle_vl
    if _paddle_vl is None:
        from paddleocr import PaddleOCRVL
        from paddlex.inference import load_pipeline_config

        config = load_pipeline_config("PaddleOCR-VL-1.6")
        config["batch_size"] = int(os.environ.get("PADDLE_VL_PAGE_BATCH", "1"))
        config["use_queues"] = False
        config["SubModules"]["LayoutDetection"]["batch_size"] = 1
        server = os.environ.get("PADDLE_VL_SERVER_URL")  # e.g. llama.cpp: http://127.0.0.1:8111/v1
        backend = {"vl_rec_backend": os.environ.get("PADDLE_VL_BACKEND", "llama-cpp-server"),
                   "vl_rec_server_url": server} if server else {}
        print(f"           PaddleOCR-VL backend: {backend or 'native (in-process)'}", flush=True)
        _paddle_vl = PaddleOCRVL(pipeline_version="v1.6", paddlex_config=config, **backend)
    kwargs = {}
    if os.environ.get("PADDLE_VL_MAX_PIXELS"):
        kwargs["max_pixels"] = int(os.environ["PADDLE_VL_MAX_PIXELS"])
    start = time.perf_counter()
    pages = list(_paddle_vl.predict(str(path), **kwargs))  # one result per PDF page
    markdown = "\n\n".join(p.markdown["markdown_texts"] for p in pages)
    return markdown, time.perf_counter() - start


_glm_ocr = None


def run_glm_ocr(path: Path):
    """GLM-OCR (0.9B, MIT), local: the glmocr SDK runs PP-DocLayoutV3 here and sends each
    region to the model served by Ollama (config in glm_ocr.yaml). Tables come out as HTML."""
    global _glm_ocr
    if os.environ.get("ZHIPU_API_KEY") or os.environ.get("GLMOCR_API_KEY"):
        raise RuntimeError("Unset ZHIPU_API_KEY / GLMOCR_API_KEY: they switch glmocr to the cloud.")
    if _glm_ocr is None:
        from glmocr import GlmOcr

        _glm_ocr = GlmOcr(config_path=str(Path(__file__).with_name("glm_ocr.yaml")), mode="selfhosted")
    start = time.perf_counter()
    result = _glm_ocr.parse(str(path), save_layout_visualization=False)
    markdown = result.markdown_result or ""
    return markdown, time.perf_counter() - start


def _check(resp):
    if not resp.ok:
        raise RuntimeError(f"LlamaParse HTTP {resp.status_code}: {resp.text[:600]}")


def run_llamaparse(path: Path, tier: str = "cost_effective"):
    """LlamaParse v2 REST API: upload, poll the job, fetch per-page markdown.
    Uploads the file to LlamaIndex's servers (public documents only)."""
    import requests

    key = os.environ.get("LLAMA_CLOUD_API_KEY", "")
    if not key:
        raise RuntimeError("Set LLAMA_CLOUD_API_KEY first.")
    headers = {"Authorization": f"Bearer {key}"}
    start = time.perf_counter()
    with open(path, "rb") as f:
        resp = requests.post(
            f"{LLAMA_BASE}/upload",
            headers=headers,
            files={"file": (path.name, f)},
            data={"configuration": json.dumps({"tier": tier, "version": "latest"})},
            timeout=300,
        )
    _check(resp)
    job_id = resp.json()["id"]

    deadline = time.time() + 1200
    while True:
        poll = requests.get(f"{LLAMA_BASE}/{job_id}", headers=headers, timeout=60)
        _check(poll)
        job = poll.json().get("job", {})  # when polling, status is under "job"
        status = job.get("status")
        if status == "COMPLETED":
            break
        if status in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"LlamaParse job {status}: {job.get('error_message')}")
        if time.time() > deadline:
            raise TimeoutError("LlamaParse job did not finish within 20 minutes")
        time.sleep(3)

    result = requests.get(
        f"{LLAMA_BASE}/{job_id}", headers=headers, params={"expand": "markdown"}, timeout=180
    )
    _check(result)
    pages = (result.json().get("markdown") or {}).get("pages") or []
    ok_pages = [p.get("markdown", "") for p in pages if p.get("success")]
    if not ok_pages:
        raise RuntimeError("LlamaParse returned no markdown pages.")
    failed = [p.get("page_number") for p in pages if not p.get("success")]
    markdown = "\n\n".join(ok_pages)
    if failed:
        markdown = f"<!-- LlamaParse failed on pages {failed} -->\n\n" + markdown
    return markdown, time.perf_counter() - start
