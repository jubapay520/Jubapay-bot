"""
BaixaTudo - web app para baixar vídeos (YouTube, TikTok, Instagram, Facebook...)
usando yt-dlp. Feito para uso pessoal entre amigos.

Variáveis de ambiente:
  ACCESS_CODE    -> senha que seus amigos digitam no app (recomendado!)
  YTDLP_COOKIES  -> (opcional) conteúdo de um cookies.txt, ajuda com Instagram/YouTube
  MAX_FILESIZE_MB-> (opcional) tamanho máximo do arquivo, padrão 500
  PORT           -> porta HTTP (o Render/Railway define sozinho)
"""
import os
import re
import shutil
import tempfile
import secrets
import asyncio
from pathlib import Path

import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

ACCESS_CODE = os.getenv("ACCESS_CODE", "")
MAX_FILESIZE = int(os.getenv("MAX_FILESIZE_MB", "500")) * 1024 * 1024
COOKIES = os.getenv("YTDLP_COOKIES", "")
MAX_PARALLEL = int(os.getenv("MAX_PARALLEL", "3"))

BASE = Path(__file__).parent
app = FastAPI(title="BaixaTudo", docs_url=None, redoc_url=None)
sem = asyncio.Semaphore(MAX_PARALLEL)

_cookie_file = None
if COOKIES.strip():
    fd, _cookie_file = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "w") as f:
        f.write(COOKIES.replace("\\n", "\n"))

URL_RE = re.compile(r"^https?://", re.I)

# Formatos compatíveis com iPhone: H.264 (avc1) + AAC em MP4.
VIDEO_FORMAT = (
    "bv*[vcodec^=avc1][height<=1080]+ba[ext=m4a]/"
    "b[ext=mp4][vcodec^=avc1]/"
    "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/"
    "b[ext=mp4]/bv*+ba/b"
)


def check_code(code: str | None):
    if ACCESS_CODE and not secrets.compare_digest(code or "", ACCESS_CODE):
        raise HTTPException(401, "Código de acesso incorreto.")


def check_url(url: str | None) -> str:
    url = (url or "").strip()
    m = re.search(r"https?://\S+", url)  # aceita texto colado com link no meio
    if not m:
        raise HTTPException(400, "Cole um link válido (começando com http).")
    return m.group(0)


def base_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": MAX_FILESIZE,
        "socket_timeout": 30,
        "retries": 3,
    }
    if _cookie_file:
        opts["cookiefile"] = _cookie_file
    return opts


def friendly_error(e: Exception) -> str:
    msg = str(e)
    low = msg.lower()
    if "sign in to confirm" in low or ("bot" in low and "youtube" in low):
        return "O YouTube bloqueou o servidor (pede login). Configure YTDLP_COOKIES no servidor."
    if "login" in low or "private" in low or "rate-limit" in low:
        return "Esse vídeo exige login ou é privado. Configure YTDLP_COOKIES no servidor."
    if "unsupported url" in low:
        return "Esse site/link não é suportado."
    if "max_filesize" in low or "larger than max" in low:
        return "Vídeo grande demais."
    return "Não consegui baixar: " + re.sub(r"\x1b\[[0-9;]*m", "", msg)[:200]


def _safe_name(title: str, ext: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\n\r\t]+', " ", title or "video").strip()[:80] or "video"
    return f"{name}.{ext}"


def _info(url: str) -> dict:
    with yt_dlp.YoutubeDL(base_opts() | {"skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("_type") == "playlist" and info.get("entries"):
        info = next(e for e in info["entries"] if e)
    return {
        "title": info.get("title") or "Vídeo",
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or info.get("channel"),
        "site": info.get("extractor_key"),
    }


def _download(url: str, mode: str, workdir: str) -> tuple[str, str]:
    opts = base_opts() | {
        "outtmpl": os.path.join(workdir, "%(id)s.%(ext)s"),
    }
    if mode == "audio":
        opts |= {
            "format": "ba[ext=m4a]/ba/b",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
    else:
        opts |= {"format": VIDEO_FORMAT, "merge_output_format": "mp4"}

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    if info.get("_type") == "playlist" and info.get("entries"):
        info = next(e for e in info["entries"] if e)

    files = [p for p in Path(workdir).iterdir() if p.is_file() and not p.name.endswith(".part")]
    if not files:
        raise RuntimeError("arquivo não gerado (talvez maior que o limite)")
    f = max(files, key=lambda p: p.stat().st_size)
    return str(f), _safe_name(info.get("title"), f.suffix.lstrip("."))


@app.post("/api/info")
async def api_info(request: Request):
    data = await request.json()
    check_code(data.get("code"))
    url = check_url(data.get("url"))
    try:
        return await asyncio.to_thread(_info, url)
    except Exception as e:
        raise HTTPException(422, friendly_error(e))


@app.post("/api/download")
async def api_download(request: Request):
    data = await request.json()
    check_code(data.get("code"))
    url = check_url(data.get("url"))
    mode = "audio" if data.get("mode") == "audio" else "video"

    workdir = tempfile.mkdtemp(prefix="bt_")
    cleanup = BackgroundTask(shutil.rmtree, workdir, ignore_errors=True)
    try:
        async with sem:
            path, name = await asyncio.to_thread(_download, url, mode, workdir)
    except Exception as e:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(422, friendly_error(e))

    media = "audio/mpeg" if path.endswith(".mp3") else "video/mp4"
    return FileResponse(path, media_type=media, filename=name, background=cleanup)


@app.get("/api/health")
def health():
    return {"ok": True, "yt_dlp": yt_dlp.version.__version__, "needs_code": bool(ACCESS_CODE)}


@app.exception_handler(HTTPException)
async def http_exc(_, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
