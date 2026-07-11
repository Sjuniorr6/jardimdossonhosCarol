import json
import os
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from auth import (
    create_access_token,
    create_user,
    get_current_user,
    get_user_by_username,
    seed_default_admin,
    verify_password,
)
from db import DATA_DIR, DB_PATH, db_cursor, init_db, normalize_images, row_to_feedback, seed_feedbacks_if_empty


BUNDLED_IMAGES_DIR = Path(__file__).resolve().parent / "images"


def _resolve_images_dir() -> Path:
    # Com volume montado, uploads SEMPRE vão pro volume (ignora IMAGES_DIR errado no Railway).
    if DATA_DIR:
        return DATA_DIR / "images"
    if os.environ.get("IMAGES_DIR"):
        return Path(os.environ["IMAGES_DIR"])
    target = BUNDLED_IMAGES_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target


IMAGES_DIR = _resolve_images_dir()
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def _seed_bundled_images(dest: Path) -> None:
    """Copia imagens do Git (hero, logo…) pro volume na 1ª vez."""
    if not BUNDLED_IMAGES_DIR.is_dir() or BUNDLED_IMAGES_DIR.resolve() == dest.resolve():
        return
    for item in BUNDLED_IMAGES_DIR.iterdir():
        if not item.is_file() or item.name.startswith("upload_"):
            continue
        out = dest / item.name
        if not out.exists():
            shutil.copy2(item, out)


class FeedbackIn(BaseModel):
    title: str
    date: str
    tag: str
    excerpt: str
    thumb: str
    text: str
    author: str
    role: str
    media: List[str] = []
    position: Optional[int] = None


class FeedbackOut(FeedbackIn):
    id: int
    position: int


class UserIn(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=4, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class UploadOut(BaseModel):
    path: str


@asynccontextmanager
async def lifespan(_app: FastAPI):
    print(
        f"[jardim] startup data_dir={DATA_DIR} db={DB_PATH} images={IMAGES_DIR} "
        f"volume={os.environ.get('RAILWAY_VOLUME_MOUNT_PATH')!r}",
        flush=True,
    )
    _seed_bundled_images(IMAGES_DIR)
    init_db()
    seed_default_admin()
    seed_feedbacks_if_empty()
    yield


app = FastAPI(title="Jardim dos Sonhos API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve /images/* directly from the project's images/ folder, so uploaded files
# can be fetched via http (e.g. http://localhost:8000/images/foo.jpg).
app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")


@app.get("/feedback")
def feedback_page():
    return FileResponse(Path(__file__).parent / "feedback.html", media_type="text/html")


@app.get("/admin")
def admin_page():
    return FileResponse(Path(__file__).parent / "admin.html", media_type="text/html")


@app.get("/jardim-dos-sonhos-logo.png")
def logo():
    return FileResponse(IMAGES_DIR / "jardim-dos-sonhos-logo.png", media_type="image/png")


@app.get("/favicon.png")
def favicon_png():
    return FileResponse(IMAGES_DIR / "favicon.png", media_type="image/png")


@app.get("/favicon.ico")
def favicon_ico():
    return FileResponse(IMAGES_DIR / "favicon.png", media_type="image/png")


@app.get("/api/health")
def health():
    volume = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    db_exists = DB_PATH.is_file()
    db_size = DB_PATH.stat().st_size if db_exists else 0
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM feedbacks")
        feedback_count = cur.fetchone()["n"]
    upload_count = sum(1 for p in IMAGES_DIR.glob("upload_*") if p.is_file()) if IMAGES_DIR.is_dir() else 0
    on_volume = bool(volume and DATA_DIR and str(DATA_DIR) == volume)
    return {
        "status": "ok",
        "persistent": on_volume,
        "data_dir": str(DATA_DIR) if DATA_DIR else None,
        "volume_mount": volume,
        "db_path": str(DB_PATH),
        "db_exists": db_exists,
        "db_size_bytes": db_size,
        "feedback_count": feedback_count,
        "images_dir": str(IMAGES_DIR),
        "upload_count": upload_count,
        "env_images_dir": os.environ.get("IMAGES_DIR"),
        "env_db_path": os.environ.get("DB_PATH"),
    }


# ---------- Auth ----------

@app.post("/api/auth/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends()):
    user = get_user_by_username(form.username)
    if not user or not verify_password(form.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha inválidos",
        )
    token = create_access_token(subject=user["username"])
    return TokenOut(access_token=token, username=user["username"])


@app.post("/api/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserIn, _=Depends(get_current_user)):
    if get_user_by_username(payload.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuário já existe",
        )
    user = create_user(payload.username, payload.password)
    return UserOut(**user)


@app.get("/api/auth/me", response_model=UserOut)
def me(current: dict = Depends(get_current_user)):
    return UserOut(id=current["id"], username=current["username"])


# ---------- Uploads ----------

@app.post("/api/uploads", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
async def upload_image(file: UploadFile = File(...), _=Depends(get_current_user)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Extensão não suportada. Use: {', '.join(sorted(ALLOWED_IMAGE_EXTS))}",
        )

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    unique = f"upload_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}{ext}"
    dest = IMAGES_DIR / unique

    written = 0
    with dest.open("wb") as buf:
        while True:
            chunk = await file.read(1024 * 64)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                buf.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Arquivo excede o limite de {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
                )
            buf.write(chunk)

    return UploadOut(path=f"images/{unique}")


# ---------- Feedbacks ----------

@app.get("/api/feedbacks", response_model=List[FeedbackOut])
def list_feedbacks():
    with db_cursor() as cur:
        cur.execute("SELECT * FROM feedbacks ORDER BY position ASC, id ASC")
        rows = cur.fetchall()
    return [row_to_feedback(r) for r in rows]


@app.get("/api/feedbacks/{feedback_id}", response_model=FeedbackOut)
def get_feedback(feedback_id: int):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM feedbacks WHERE id = ?", (feedback_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Feedback não encontrado")
    return row_to_feedback(row)


@app.post("/api/feedbacks", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
def create_feedback(payload: FeedbackIn, _=Depends(get_current_user)):
    thumb, media = normalize_images(payload.thumb, payload.media)
    with db_cursor() as cur:
        if payload.position is None:
            cur.execute("SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM feedbacks")
            position = cur.fetchone()["next_pos"]
        else:
            position = payload.position

        cur.execute(
            """
            INSERT INTO feedbacks (title, date, tag, excerpt, thumb, text, author, role, media_json, position)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.title, payload.date, payload.tag, payload.excerpt, thumb,
                payload.text, payload.author, payload.role,
                json.dumps(media),
                position,
            ),
        )
        new_id = cur.lastrowid
        cur.execute("SELECT * FROM feedbacks WHERE id = ?", (new_id,))
        row = cur.fetchone()
    return row_to_feedback(row)


@app.put("/api/feedbacks/{feedback_id}", response_model=FeedbackOut)
def update_feedback(feedback_id: int, payload: FeedbackIn, _=Depends(get_current_user)):
    thumb, media = normalize_images(payload.thumb, payload.media)
    with db_cursor() as cur:
        cur.execute("SELECT id, position FROM feedbacks WHERE id = ?", (feedback_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Feedback não encontrado")

        position = payload.position if payload.position is not None else row["position"]

        cur.execute(
            """
            UPDATE feedbacks
               SET title=?, date=?, tag=?, excerpt=?, thumb=?, text=?, author=?, role=?,
                   media_json=?, position=?, updated_at=CURRENT_TIMESTAMP
             WHERE id=?
            """,
            (
                payload.title, payload.date, payload.tag, payload.excerpt, thumb,
                payload.text, payload.author, payload.role,
                json.dumps(media),
                position, feedback_id,
            ),
        )
        cur.execute("SELECT * FROM feedbacks WHERE id = ?", (feedback_id,))
        row = cur.fetchone()
    return row_to_feedback(row)


@app.delete("/api/feedbacks/{feedback_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_feedback(feedback_id: int, _=Depends(get_current_user)):
    with db_cursor() as cur:
        cur.execute("SELECT id FROM feedbacks WHERE id = ?", (feedback_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Feedback não encontrado")
        cur.execute("DELETE FROM feedbacks WHERE id = ?", (feedback_id,))
    return None
