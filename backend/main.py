import json
import os
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
from db import db_cursor, init_db, row_to_feedback, seed_feedbacks_if_empty


def _resolve_images_dir() -> Path:
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "images",    # repo root: images/ (main.py lives in backend/)
        here / "images",           # fallback: images/ alongside main.py
    ]
    for path in candidates:
        if path.is_dir():
            return path
    # Neither exists yet (e.g. first run) — create the repo-root images/ folder,
    # since that's where uploads/static images are expected to live relative to
    # backend/ when it's used as the working/build directory.
    target = Path(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "images"))
    )
    target.mkdir(parents=True, exist_ok=True)
    return target


IMAGES_DIR = _resolve_images_dir()
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


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


@app.get("/api/health")
def health():
    return {"status": "ok"}


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
                payload.title, payload.date, payload.tag, payload.excerpt, payload.thumb,
                payload.text, payload.author, payload.role,
                json.dumps(list(payload.media)),
                position,
            ),
        )
        new_id = cur.lastrowid
        cur.execute("SELECT * FROM feedbacks WHERE id = ?", (new_id,))
        row = cur.fetchone()
    return row_to_feedback(row)


@app.put("/api/feedbacks/{feedback_id}", response_model=FeedbackOut)
def update_feedback(feedback_id: int, payload: FeedbackIn, _=Depends(get_current_user)):
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
                payload.title, payload.date, payload.tag, payload.excerpt, payload.thumb,
                payload.text, payload.author, payload.role,
                json.dumps(list(payload.media)),
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
