from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import os
import tempfile
import asyncio
import logging
from pathlib import Path
from typing import Optional
import aiofiles
import uuid
import json
import re

from video_processor import VideoProcessor
from transcriber import Transcriber
from summarizer import Summarizer
from translator import Translator
from editor import Editor
from pipeline import process_transcript_input

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI视频转录器", version="1.0.0")

# CORS中间件配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 获取项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 挂载静态文件
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")

# 创建临时目录
TEMP_DIR = PROJECT_ROOT / "temp"
TEMP_DIR.mkdir(exist_ok=True)

# 初始化处理器
video_processor = VideoProcessor()
transcriber = Transcriber()
summarizer = Summarizer()
translator = Translator()
editor = Editor()

# 全局翻译开关（通过环境变量控制，默认开启翻译）
def _env_flag(name: str, default: str = "0") -> bool:
    val = os.getenv(name, default).strip().lower()
    return val in ("1", "true", "yes", "y", "on")

NO_TRANSLATE = _env_flag("NO_TRANSLATE", "0") or _env_flag("DISABLE_TRANSLATION", "0")

# 存储任务状态 - 使用文件持久化
import json
import threading

TASKS_FILE = TEMP_DIR / "tasks.json"
tasks_lock = threading.Lock()

def load_tasks():
    """加载任务状态"""
    try:
        if TASKS_FILE.exists():
            with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except:
        pass
    return {}

def save_tasks(tasks_data):
    """保存任务状态"""
    try:
        with tasks_lock:
            with open(TASKS_FILE, 'w', encoding='utf-8') as f:
                json.dump(tasks_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存任务状态失败: {e}")

async def broadcast_task_update(task_id: str, task_data: dict):
    """向所有连接的SSE客户端广播任务状态更新"""
    logger.info(f"广播任务更新: {task_id}, 状态: {task_data.get('status')}, 连接数: {len(sse_connections.get(task_id, []))}")
    if task_id in sse_connections:
        connections_to_remove = []
        for queue in sse_connections[task_id]:
            try:
                await queue.put(json.dumps(task_data, ensure_ascii=False))
                logger.debug(f"消息已发送到队列: {task_id}")
            except Exception as e:
                logger.warning(f"发送消息到队列失败: {e}")
                connections_to_remove.append(queue)
        
        # 移除断开的连接
        for queue in connections_to_remove:
            sse_connections[task_id].remove(queue)
        
        # 如果没有连接了，清理该任务的连接列表
        if not sse_connections[task_id]:
            del sse_connections[task_id]

# 启动时加载任务状态
tasks = load_tasks()
# 存储正在处理的URL，防止重复处理
processing_urls = set()
# 存储活跃的任务对象，用于控制和取消
active_tasks = {}
# 存储SSE连接，用于实时推送状态更新
sse_connections = {}

def _sanitize_title_for_filename(title: str) -> str:
    """将视频标题清洗为安全的文件名片段。"""
    if not title:
        return "untitled"
    # 仅保留字母数字、下划线、连字符与空格
    safe = re.sub(r"[^\w\-\s]", "", title)
    # 压缩空白并转为下划线
    safe = re.sub(r"\s+", "_", safe).strip("._-")
    # 最长限制，避免过长文件名问题
    return safe[:80] or "untitled"

@app.get("/")
async def read_root():
    """返回前端页面"""
    return FileResponse(str(PROJECT_ROOT / "static" / "index.html"))

@app.post("/api/process-video")
async def process_video(
    url: str = Form(...),
    summary_language: str = Form(default="zh"),
    edit_mode: Optional[str] = Form(default=None),
):
    """
    处理视频链接，返回任务ID
    """
    try:
        # 检查是否已经在处理相同的URL
        if url in processing_urls:
            # 查找现有任务
            for tid, task in tasks.items():
                if task.get("url") == url:
                    return {"task_id": tid, "message": "该视频正在处理中，请等待..."}
            
        # 生成唯一任务ID
        task_id = str(uuid.uuid4())
        
        # 标记URL为正在处理
        processing_urls.add(url)
        
        # 初始化任务状态
        tasks[task_id] = {
            "status": "processing",
            "progress": 0,
            "message": "开始处理视频...",
            "script": None,
            "summary": None,
            "error": None,
            "url": url  # 保存URL用于去重
        }
        save_tasks(tasks)
        
        # 创建并跟踪异步任务
        task = asyncio.create_task(process_video_task(task_id, url, summary_language, edit_mode))
        active_tasks[task_id] = task
        
        return {"task_id": task_id, "message": "任务已创建，正在处理中..."}
        
    except Exception as e:
        logger.error(f"处理视频时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@app.post("/api/process-transcript")
async def process_transcript(
    transcript: str = Form(...),
    summary_language: str = Form(default="zh"),
    video_title: Optional[str] = Form(default=None),
    source_language: Optional[str] = Form(default=None),
    enable_translation: bool = Form(default=True),
    generate_summary: bool = Form(default=True),
    edit_mode: Optional[str] = Form(default=None),
):
    """直接处理已有的转录文本，生成摘要/翻译等结果。"""

    if not transcript or not transcript.strip():
        raise HTTPException(status_code=400, detail="转录文本不能为空")

    try:
        task_id = str(uuid.uuid4())

        tasks[task_id] = {
            "status": "processing",
            "progress": 5,
            "message": "准备处理转录...",
            "script": None,
            "summary": None,
            "translation": None,
            "error": None,
            "video_title": video_title,
            "summary_language": summary_language,
        }
        save_tasks(tasks)

        task = asyncio.create_task(process_transcript_task(
            task_id=task_id,
            transcript=transcript,
            summary_language=summary_language,
            video_title=video_title,
            source_language=source_language,
            enable_translation=enable_translation,
            generate_summary=generate_summary,
            edit_mode=edit_mode,
        ))
        active_tasks[task_id] = task

        return {"task_id": task_id, "message": "任务已创建，正在处理中..."}

    except Exception as e:
        logger.error(f"处理转录时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")

async def process_video_task(task_id: str, url: str, summary_language: str, edit_mode: Optional[str]):
    """
    异步处理视频任务
    """
    try:
        # 立即更新状态：开始下载视频
        tasks[task_id].update({
            "status": "processing",
            "progress": 10,
            "message": "正在下载视频..."
        })
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])
        
        # 添加短暂延迟确保状态更新
        import asyncio
        await asyncio.sleep(0.1)
        
        # 更新状态：正在解析视频信息
        tasks[task_id].update({
            "progress": 15,
            "message": "正在解析视频信息..."
        })
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])
        
        # 下载并转换视频
        audio_path, video_title = await video_processor.download_and_convert(url, TEMP_DIR)
        
        # 下载完成，更新状态
        tasks[task_id].update({
            "progress": 35,
            "message": "视频下载完成，准备转录..."
        })
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])
        
        # 更新状态：转录中
        tasks[task_id].update({
            "progress": 40,
            "message": "正在转录音频..."
        })
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])
        
        # 转录音频
        raw_script = await transcriber.transcribe(audio_path)

        # 将Whisper原始转录保存为Markdown文件，供下载/归档
        try:
            short_id = task_id.replace("-", "")[:6]
            safe_title = _sanitize_title_for_filename(video_title)
            raw_md_filename = f"raw_{safe_title}_{short_id}.md"
            raw_md_path = TEMP_DIR / raw_md_filename
            with open(raw_md_path, "w", encoding="utf-8") as f:
                content_raw = (raw_script or "") + f"\n\nsource: {url}\n"
                f.write(content_raw)

            # 记录原始转录文件路径（仅保存文件名，实际路径位于TEMP_DIR）
            tasks[task_id].update({
                "raw_script_file": raw_md_filename
            })
            save_tasks(tasks)
            await broadcast_task_update(task_id, tasks[task_id])
        except Exception as e:
            logger.error(f"保存原始转录Markdown失败: {e}")
        
        # 使用原始转录文本，跳过单块文本优化流程
        script = raw_script
        
        # 为转录文本添加标题，并在结尾添加来源链接
        script_with_title = f"# {video_title}\n\n{script}\n\nsource: {url}\n"
        
        # 检查是否需要翻译
        detected_language = transcriber.get_detected_language(raw_script)
        logger.info(f"检测到的语言: {detected_language}, 摘要语言: {summary_language}")
        
        translation_content = None
        translation_filename = None
        translation_path = None
        
        # 若设置 NO_TRANSLATE/DISABLE_TRANSLATION，则无论语言是否不一致都跳过翻译
        if (not NO_TRANSLATE) and detected_language and translator.should_translate(detected_language, summary_language):
            logger.info(f"需要翻译: {detected_language} -> {summary_language}")
            # 更新状态：生成翻译
            tasks[task_id].update({
                "progress": 70,
                "message": "正在生成翻译..."
            })
            save_tasks(tasks)
            await broadcast_task_update(task_id, tasks[task_id])
            
            # 翻译转录文本
            translation_content = await translator.translate_text(script, summary_language, detected_language)
            translation_with_title = f"# {video_title}\n\n{translation_content}\n\nsource: {url}\n"
            
            # 保存翻译到文件
            translation_filename = f"translation_{safe_title}_{short_id}.md"
            translation_path = TEMP_DIR / translation_filename
            async with aiofiles.open(translation_path, "w", encoding="utf-8") as f:
                await f.write(translation_with_title)
        else:
            logger.info(f"不需要翻译: detected_language={detected_language}, summary_language={summary_language}, should_translate={translator.should_translate(detected_language, summary_language) if detected_language else 'N/A'}")
        
        # 保存转录文本到文件（直接使用原始转录，无优化/摘要）
        script_filename = f"transcript_{task_id}.md"
        script_path = TEMP_DIR / script_filename
        async with aiofiles.open(script_path, "w", encoding="utf-8") as f:
            await f.write(script_with_title)
        
        # 重命名为新规则：transcript_标题_短ID.md
        new_script_filename = f"transcript_{safe_title}_{short_id}.md"
        new_script_path = TEMP_DIR / new_script_filename
        try:
            if script_path.exists():
                script_path.rename(new_script_path)
                script_path = new_script_path
        except Exception as _:
            # 如重命名失败，继续使用原路径
            pass

        # 可选：Edit Note（若提供 edit_mode）
        editnote_filename = None
        editnote_path = None
        if edit_mode:
            try:
                tasks[task_id].update({
                    "progress": 85,
                    "message": f"正在生成 Edit Note ({edit_mode})..."
                })
                save_tasks(tasks)
                await broadcast_task_update(task_id, tasks[task_id])

                edit_note = await editor.generate(edit_mode, script)
                editnote_filename = f"editnote_{edit_mode}_{safe_title}_{short_id}.md"
                editnote_path = TEMP_DIR / editnote_filename
                async with aiofiles.open(editnote_path, "w", encoding="utf-8") as f:
                    await f.write(edit_note + f"\n\nsource: {url}\n")
            except Exception as e:
                logger.error(f"生成 Edit Note 失败: {e}")

        # 更新状态：完成
        task_result = {
            "status": "completed",
            "progress": 100,
            "message": "处理完成！",
            "video_title": video_title,
            "script": script_with_title,
            "script_path": str(script_path),
            "short_id": short_id,
            "safe_title": safe_title,
            "detected_language": detected_language,
            "summary_language": summary_language
        }
        
        # 如果有翻译，添加翻译信息
        if translation_content and translation_path:
            task_result.update({
                "translation": translation_with_title,
                "translation_path": str(translation_path),
                "translation_filename": translation_filename
            })
        if editnote_filename and editnote_path:
            task_result.update({
                "edit_note": edit_note,
                "editnote_path": str(editnote_path),
                "editnote_filename": editnote_filename,
                "edit_mode": edit_mode,
            })
        
        tasks[task_id].update(task_result)
        save_tasks(tasks)
        logger.info(f"任务完成，准备广播最终状态: {task_id}")
        await broadcast_task_update(task_id, tasks[task_id])
        logger.info(f"最终状态已广播: {task_id}")
        
        # 从处理列表中移除URL
        processing_urls.discard(url)
        
        # 从活跃任务列表中移除
        if task_id in active_tasks:
            del active_tasks[task_id]
        
        # 不要立即删除临时文件！保留给用户下载
        # 文件会在一定时间后自动清理或用户手动清理
            
    except Exception as e:
        logger.error(f"任务 {task_id} 处理失败: {str(e)}")
        # 从处理列表中移除URL
        processing_urls.discard(url)
        
        # 从活跃任务列表中移除
        if task_id in active_tasks:
            del active_tasks[task_id]
            
        tasks[task_id].update({
            "status": "error",
            "error": str(e),
            "message": f"处理失败: {str(e)}"
        })
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])


async def process_transcript_task(
    task_id: str,
    transcript: str,
    summary_language: str,
    video_title: Optional[str],
    source_language: Optional[str],
    enable_translation: bool,
    generate_summary: bool,
    edit_mode: Optional[str],
):
    """处理 transcript-only 任务。"""

    try:
        tasks[task_id].update({
            "status": "processing",
            "progress": 15,
            "message": "正在处理转录..."
        })
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])

        async def on_update(payload: dict):
            tasks[task_id].update({k: v for k, v in payload.items() if k not in ("warnings",)})
            save_tasks(tasks)
            await broadcast_task_update(task_id, tasks[task_id])

        result = await process_transcript_input(
            transcript=transcript,
            summary_language=summary_language,
            temp_dir=TEMP_DIR,
            on_update=on_update,
            video_title=video_title,
            source_language=source_language,
            skip_translate=(not enable_translation) or NO_TRANSLATE,
            skip_summary=not generate_summary,
            edit_mode=edit_mode,
        )

        transcript_filename = result.get("transcript_file")
        summary_filename = result.get("summary_file")
        translation_filename = result.get("translation_file")
        editnote_filename = result.get("editnote_file")

        script_path = TEMP_DIR / transcript_filename if transcript_filename else None
        summary_path = TEMP_DIR / summary_filename if summary_filename else None
        translation_path = TEMP_DIR / translation_filename if translation_filename else None
        editnote_path = TEMP_DIR / editnote_filename if editnote_filename else None

        script_content = transcript
        if script_path and script_path.exists():
            script_content = script_path.read_text(encoding="utf-8")

        summary_content = None
        if summary_path and summary_path.exists():
            summary_content = summary_path.read_text(encoding="utf-8")

        translation_content = None
        if translation_path and translation_path.exists():
            translation_content = translation_path.read_text(encoding="utf-8")

        edit_note_content = None
        if editnote_path and editnote_path.exists():
            edit_note_content = editnote_path.read_text(encoding="utf-8")

        warnings = result.get("warnings") or []

        tasks[task_id].update({
            "status": "completed",
            "progress": 100,
            "message": "处理完成！" if not warnings else "处理完成（部分步骤失败）",
            "video_title": result.get("video_title") or video_title,
            "script": script_content,
            "script_path": str(script_path) if script_path else None,
            "summary": summary_content,
            "summary_path": str(summary_path) if summary_path else None,
            "translation": translation_content,
            "translation_path": str(translation_path) if translation_path else None,
            "edit_note": edit_note_content,
            "editnote_path": str(editnote_path) if editnote_path else None,
            "raw_script_file": result.get("raw_script_file"),
            "transcript_file": transcript_filename,
            "summary_file": summary_filename,
            "translation_file": translation_filename,
            "editnote_file": editnote_filename,
            "detected_language": result.get("detected_language"),
            "summary_language": summary_language,
            "warnings": warnings,
        })
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])

    except Exception as e:
        logger.error(f"处理 transcript 任务失败: {e}")
        tasks[task_id].update({
            "status": "error",
            "progress": 100,
            "message": f"处理失败: {e}",
            "error": str(e),
        })
        save_tasks(tasks)
        await broadcast_task_update(task_id, tasks[task_id])
    finally:
        if task_id in active_tasks:
            del active_tasks[task_id]


@app.get("/api/task-status/{task_id}")
async def get_task_status(task_id: str):
    """
    获取任务状态
    """
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return tasks[task_id]

@app.get("/api/task-stream/{task_id}")
async def task_stream(task_id: str):
    """
    SSE实时任务状态流
    """
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    async def event_generator():
        # 创建任务专用的队列
        queue = asyncio.Queue()
        
        # 将队列添加到连接列表
        if task_id not in sse_connections:
            sse_connections[task_id] = []
        sse_connections[task_id].append(queue)
        
        try:
            # 立即发送当前状态
            current_task = tasks.get(task_id, {})
            yield f"data: {json.dumps(current_task, ensure_ascii=False)}\n\n"
            
            # 持续监听状态更新
            while True:
                try:
                    # 等待状态更新，超时时间30秒发送心跳
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {data}\n\n"
                    
                    # 如果任务完成或失败，结束流
                    task_data = json.loads(data)
                    if task_data.get("status") in ["completed", "error"]:
                        break
                        
                except asyncio.TimeoutError:
                    # 发送心跳保持连接
                    yield f"data: {json.dumps({'type': 'heartbeat'}, ensure_ascii=False)}\n\n"
                    
        except asyncio.CancelledError:
            logger.info(f"SSE连接被取消: {task_id}")
        except Exception as e:
            logger.error(f"SSE流异常: {e}")
        finally:
            # 清理连接
            if task_id in sse_connections and queue in sse_connections[task_id]:
                sse_connections[task_id].remove(queue)
                if not sse_connections[task_id]:
                    del sse_connections[task_id]
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET",
            "Access-Control-Allow-Headers": "Cache-Control"
        }
    )

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    """
    直接从temp目录下载文件（简化方案）
    """
    try:
        # 检查文件扩展名安全性
        if not filename.endswith('.md'):
            raise HTTPException(status_code=400, detail="仅支持下载.md文件")
        
        # 检查文件名格式（防止路径遍历攻击）
        if '..' in filename or '/' in filename or '\\' in filename:
            raise HTTPException(status_code=400, detail="文件名格式无效")
            
        file_path = TEMP_DIR / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="文件不存在")
            
        return FileResponse(
            file_path,
            filename=filename,
            media_type="text/markdown"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"下载文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")


@app.delete("/api/task/{task_id}")
async def delete_task(task_id: str):
    """
    取消并删除任务
    """
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    task_data = tasks[task_id]

    # 如果任务还在运行，先取消它
    if task_id in active_tasks:
        task = active_tasks[task_id]
        if not task.done():
            task.cancel()
            logger.info(f"任务 {task_id} 已被取消")
        del active_tasks[task_id]

    # 从处理URL列表中移除
    task_url = task_data.get("url")
    if task_url:
        processing_urls.discard(task_url)

    # 清理关联的临时文件
    def _safe_remove(file_path: Optional[str]):
        if not file_path:
            return
        try:
            Path(file_path).unlink(missing_ok=True)
        except Exception as exc:
            logger.debug(f"删除文件失败 {file_path}: {exc}")

    for path_key in ["script_path", "translation_path", "editnote_path"]:
        _safe_remove(task_data.get(path_key))

    raw_filename = task_data.get("raw_script_file")
    if raw_filename:
        try:
            (TEMP_DIR / raw_filename).unlink(missing_ok=True)
        except Exception as exc:
            logger.debug(f"删除原始转录文件失败 {raw_filename}: {exc}")

    # 移除SSE连接队列
    if task_id in sse_connections:
        sse_connections.pop(task_id, None)

    # 删除任务记录
    del tasks[task_id]
    save_tasks(tasks)
    return {"message": "任务已取消并删除"}

@app.get("/api/tasks/active")
async def get_active_tasks():
    """
    获取当前活跃任务列表（用于调试）
    """
    active_count = len(active_tasks)
    processing_count = len(processing_urls)
    return {
        "active_tasks": active_count,
        "processing_urls": processing_count,
        "task_ids": list(active_tasks.keys())
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
