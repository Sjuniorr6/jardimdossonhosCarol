import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from db import db_cursor

SECRET_KEY = os.environ.get("JARDIM_SECRET", "change-me-in-prod-super-secret-key-jardim-dos-sonhos")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 hours

DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "admin@01"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def _prep(password: str) -> bytes:
    # bcrypt has a hard 72-byte limit; truncate transparently.
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prep(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prep(plain), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_user_by_username(username: str) -> Optional[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row["id"], "username": row["username"], "password_hash": row["password_hash"]}


def create_user(username: str, password: str) -> dict:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, hash_password(password)),
        )
        user_id = cur.lastrowid
        return {"id": user_id, "username": username}


def seed_default_admin():
    if get_user_by_username(DEFAULT_ADMIN_USER) is None:
        create_user(DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD)


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    creds_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciais inválidas",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if not username:
            raise creds_exc
    except JWTError:
        raise creds_exc

    user = get_user_by_username(username)
    if user is None:
        raise creds_exc
    return user
