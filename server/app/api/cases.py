"""
比邻AI · 病例病史路由

    GET    /v1/cases/types                     病历类型下拉（端侧不写死）
    GET    /v1/cases                           我的病例列表
    POST   /v1/cases                           建一份病历（可同时传文件，multipart）
    GET    /v1/cases/{id}                      详情（含解析出的全文）
    PATCH  /v1/cases/{id}                      改（诊断/小结/就诊日期…）
    DELETE /v1/cases/{id}                      删（连同附件）
    POST   /v1/cases/{id}/files                给已有病历加附件
    DELETE /v1/cases/{id}/files/{fid}          删一个附件
    GET    /v1/cases/{id}/files/{fid}/raw      取原件（家属端查看用）

## 两条解析路，自动选

  · **PDF** → `app/docs/pdf.py` 抽文本层。抽不出（扫描件）就返回
    `extractStatus=scanned` 并给出"拍张照发我"的提示——**不假装读到了**
  · **图片** → `app/vision/gateway.py` 识图（Qwen-VL）。
    没配 key 时返回 `extractStatus=failed` + 明确原因，老人仍可手填

两种情况下病历本身都能建起来（只是没有自动文字），
老人可以自己写诊断/小结——**识别是辅助，不是前置条件**。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from ..docs import (
    CASE_KINDS,
    FILE_IMAGE,
    FILE_PDF,
    MAX_CASES,
    MAX_FILE_BYTES,
    CaseFile,
    extract_text,
    new_file_id,
)
from ..errors import api_error
from ..models.message import now_iso
from ..vision import ALLOWED_MIME, detect_mime, is_pdf
from .accounts import _current_account

logger = logging.getLogger("bilin.docs.api")

router = APIRouter(prefix="/v1/cases", tags=["cases"])


def _store(request: Request):
    return request.app.state.cases


def _vision(request: Request):
    return request.app.state.vision


def _require_account(request: Request):
    account = _current_account(request)
    if account is None:
        return None, api_error("auth_required")
    return account, None


def _own_case(request: Request, account, case_id: str):
    """取病历并校验归属。**不能看/改别人的病历。**"""
    case = _store(request).find(case_id)
    if case is None:
        return None, api_error("not_found", "没找到这份病历")
    if case.elder_id != account.id:
        logger.warning("越权访问病历：me=%s owner=%s", account.id, case.elder_id)
        return None, api_error("forbidden")
    return case, None


async def _ingest(request: Request, upload: UploadFile) -> tuple[CaseFile | None, str]:
    """收一个文件：落盘 + 解析/识别。返回 (CaseFile, 错误说明)"""
    data = await upload.read()
    filename = upload.filename or ""
    mime = (upload.content_type or "").split(";")[0].strip()

    if not data:
        return None, "这个文件是空的"
    if len(data) > MAX_FILE_BYTES:
        return None, "文件太大了（最多 8MB），可以只拍关键那一页"

    store = _store(request)
    file_id = new_file_id()

    if is_pdf(mime, filename):
        parsed = extract_text(data)
        path = store.save_bytes(file_id, ".pdf", data)
        item = CaseFile(
            file_id=file_id,
            file_type=FILE_PDF,
            filename=filename or (file_id + ".pdf"),
            mime="application/pdf",
            size=len(data),
            path=path,
            extracted_text=parsed.text,
            # 扫描件不是"失败"，是"这条路读不出，得换识图"——状态要能区分
            extract_status="ok" if parsed.ok else ("scanned" if parsed.looks_scanned else "failed"),
            extract_reason=parsed.reason,
        )
        logger.info("病例 PDF：%s 字节，抽出 %s 字（%s）", len(data), len(parsed.text), item.extract_status)
        return item, ""

    mime_image = detect_mime(filename, mime)
    if not mime_image:
        return None, "只支持图片（jpg/png）和 PDF"

    path = store.save_bytes(file_id, "." + ALLOWED_MIME[mime_image], data)
    item = CaseFile(
        file_id=file_id,
        file_type=FILE_IMAGE,
        filename=filename or (file_id + "." + ALLOWED_MIME[mime_image]),
        mime=mime_image,
        size=len(data),
        path=path,
    )

    result = await _vision(request).read_image(data, mime_image)
    if result.ok:
        item.extracted_text = result.text
        item.extract_status = "ok"
    else:
        item.extract_status = "failed"
        item.extract_reason = result.reason
        logger.info("识图没成功：%s", result.reason)
    return item, ""


#: 识别结果里的小标题（不是内容）。自动填字段时要跳过这些行
_SECTION_LABELS = (
    "主要信息", "检查结果", "用药", "医嘱", "诊断", "结论", "医院名称", "日期",
    "科别", "药名", "剂量", "用法", "参考", "小 结", "小结",
)


def _pick_title(text: str) -> str:
    """从识别结果里挑一个**像标题的内容行**。

    为什么要挑：识图返回的是"主要信息：／医院名称：市第一人民医院／检查结果：…"
    这种分段文本。直接取第一行会得到「主要信息：」这个小标题——
    老人看到自己的病历叫"主要信息："只会觉得坏了。
    所以跳过分段标题，取第一条有实质内容的行。
    """
    for raw in text.splitlines():
        line = raw.strip().strip("：:").strip()
        if not line:
            continue
        # 纯分段标题（"主要信息"、"检查结果："）→ 跳过
        bare = line.rstrip("：:").strip()
        if bare in _SECTION_LABELS or any(bare == label for label in _SECTION_LABELS):
            continue
        # "诊断/结论：2型糖尿病" 这种带内容的，取冒号后面的内容当标题更准确
        for sep in ("：", ":"):
            if sep in line:
                head, tail = line.split(sep, 1)
                if any(label in head for label in _SECTION_LABELS) and tail.strip():
                    return tail.strip()[:40]
                break
        if len(line) <= 4 and line in _SECTION_LABELS:
            continue
        return line[:40]
    return ""


def _apply_auto_fields(case) -> None:
    """把识别/抽取出来的文字**顺手填进空着的字段**，老人可以再改。

    为什么做这件"小事"：老人拍完照多半不会再手打诊断名。
    自动填上（且只在字段为空时填）能让病历立刻有内容可读，
    同时**不覆盖老人已经写好的东西**。
    """
    if case.diagnosis and case.summary:
        return
    texts = [f.extracted_text for f in case.files if f.extracted_text.strip()]
    if not texts:
        return
    combined = "\n".join(texts)

    if not case.diagnosis:
        # 优先从"诊断/结论"那一行里取，比整段文字精确得多
        for raw in combined.splitlines():
            line = raw.strip()
            if any(key in line for key in ("诊断", "结论")):
                for sep in ("：", ":"):
                    if sep in line and line.split(sep, 1)[1].strip():
                        case.diagnosis = line.split(sep, 1)[1].strip()[:120]
                        break
                if case.diagnosis:
                    break

    if not case.summary:
        lines = [line.strip() for line in combined.splitlines() if line.strip()]
        case.summary = "\n".join(lines[:8])[:600]

    if not case.title:
        case.title = _pick_title(combined)


@router.get("/types")
async def case_types():
    """病历类型下拉（不要求登录：建表前要先渲染下拉）"""
    return JSONResponse(
        content={"types": [{"kind": key, "label": label} for key, label in CASE_KINDS.items()]}
    )


@router.get("")
async def list_cases(request: Request):
    """我的病例列表（按就诊时间倒序）"""
    account, error = _require_account(request)
    if error:
        return error
    cases = _store(request).cases_of(account.id)
    return JSONResponse(
        content={
            "cases": [case.to_dict() for case in cases],
            "count": len(cases),
            "vision": _vision(request).describe(),
        }
    )


@router.post("")
async def create_case(
    request: Request,
    kind: str = Form(default="other"),
    title: str = Form(default=""),
    hospital: str = Form(default=""),
    visit_date: str = Form(default="", alias="visitDate"),
    diagnosis: str = Form(default=""),
    summary: str = Form(default=""),
    note: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
):
    """建一份病历。可以只写文字、只传文件、或者两者都有。

    **用 multipart 而不是 base64**：病历照片动辄几百 KB，
    base64 平白多 33% 体积（与录音接口同一个理由，见 main.py 的 ASR 说明）。
    """
    account, error = _require_account(request)
    if error:
        return error

    store = _store(request)
    if len(store.cases_of(account.id)) >= MAX_CASES:
        return api_error("bad_request", "病历太多了，先整理一下")

    case = store.create(
        elder_id=account.id,
        kind=kind if kind in CASE_KINDS else "other",
        title=title,
        hospital=hospital,
        visit_date=visit_date,
        diagnosis=diagnosis,
        summary=summary,
        note=note,
    )

    problems: list[str] = []
    for upload in files or []:
        item, problem = await _ingest(request, upload)
        if problem:
            problems.append(problem)
            continue
        store.add_file(case, item)

    _apply_auto_fields(case)
    if case.summary or case.title or case.diagnosis:
        store.update(case, summary=case.summary, title=case.title, diagnosis=case.diagnosis)

    logger.info(
        "新病历：%s %s（附件 %s，%s）",
        account.name, case.kind_label(), len(case.files), now_iso(),
    )
    return JSONResponse(
        content={
            "case": case.to_dict(with_text=True),
            "problems": problems,
            "vision": _vision(request).describe(),
        },
        status_code=201,
    )


@router.get("/{case_id}")
async def get_case(case_id: str, request: Request):
    """病历详情（含解析出的全文）"""
    account, error = _require_account(request)
    if error:
        return error
    case, error = _own_case(request, account, case_id)
    if error:
        return error
    return JSONResponse(content={"case": case.to_dict(with_text=True)})


@router.patch("/{case_id}")
async def update_case(case_id: str, request: Request):
    """改病历字段（老人自己修认识错的地方）"""
    account, error = _require_account(request)
    if error:
        return error
    case, error = _own_case(request, account, case_id)
    if error:
        return error

    body = await request.json()
    fields = {}
    for key in ("kind", "title", "hospital", "summary", "note"):
        if key in body:
            fields[key] = body[key]
    if "diagnosis" in body:
        fields["diagnosis"] = body["diagnosis"]
    for key in ("visitDate", "visit_date"):
        if key in body:
            fields["visit_date"] = body[key]
    if fields.get("kind") and fields["kind"] not in CASE_KINDS:
        fields["kind"] = "other"

    _store(request).update(case, **fields)
    return JSONResponse(content={"case": case.to_dict(with_text=True)})


@router.delete("/{case_id}")
async def delete_case(case_id: str, request: Request):
    """删病历（连同附件与磁盘原件）"""
    account, error = _require_account(request)
    if error:
        return error
    case, error = _own_case(request, account, case_id)
    if error:
        return error
    _store(request).remove(case.id)
    return JSONResponse(content={"ok": True})


@router.post("/{case_id}/files")
async def add_file(case_id: str, request: Request, file: UploadFile = File(...)):
    """给已有病历再加一张照片 / 一个 PDF"""
    account, error = _require_account(request)
    if error:
        return error
    case, error = _own_case(request, account, case_id)
    if error:
        return error

    item, problem = await _ingest(request, file)
    if problem:
        return api_error("bad_request", problem)

    store = _store(request)
    store.add_file(case, item)
    _apply_auto_fields(case)
    store.update(case, summary=case.summary, title=case.title)
    return JSONResponse(content={"case": case.to_dict(with_text=True)}, status_code=201)


@router.delete("/{case_id}/files/{file_id}")
async def delete_file(case_id: str, file_id: str, request: Request):
    """删一个附件（原件也一起删）"""
    account, error = _require_account(request)
    if error:
        return error
    case, error = _own_case(request, account, case_id)
    if error:
        return error
    removed = _store(request).remove_file(case, file_id)
    if removed is None:
        return api_error("not_found", "没找到这个附件")
    return JSONResponse(content={"ok": True, "case": case.to_dict(with_text=True)})


@router.get("/{case_id}/files/{file_id}/raw")
async def get_raw(case_id: str, file_id: str, request: Request):
    """取原件（家属端想自己看一眼原图时用）"""
    account, error = _require_account(request)
    if error:
        return error
    case, error = _own_case(request, account, case_id)
    if error:
        return error

    item = next((f for f in case.files if f.file_id == file_id), None)
    if item is None:
        return api_error("not_found", "没找到这个附件")
    data = _store(request).read_bytes(item.path)
    if data is None:
        return api_error("not_found", "原件找不到了")
    return Response(
        content=data,
        media_type=item.mime or "application/octet-stream",
        headers={"Content-Disposition": "inline; filename=\"" + (item.filename or item.file_id) + "\""},
    )


@router.get("/vision/status")
async def vision_status(request: Request):
    """识图能力自检（老人端/家人端都可能想知道"拍照能不能用"）"""
    return JSONResponse(content=_vision(request).describe())
