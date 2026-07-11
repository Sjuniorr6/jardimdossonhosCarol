import os
import sqlite3
import json
from pathlib import Path
from contextlib import contextmanager

def _resolve_db_path() -> Path:
    if os.environ.get("DB_PATH"):
        return Path(os.environ["DB_PATH"])
    if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"):
        return Path(os.environ["RAILWAY_VOLUME_MOUNT_PATH"]) / "jardim.db"
    if Path("/app/data").is_dir():
        return Path("/app/data/jardim.db")
    return Path(__file__).parent / "jardim.db"


DB_PATH = _resolve_db_path()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_cursor():
    conn = get_connection()
    try:
        yield conn.cursor()
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS feedbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                tag TEXT NOT NULL,
                excerpt TEXT NOT NULL,
                thumb TEXT NOT NULL,
                text TEXT NOT NULL,
                author TEXT NOT NULL,
                role TEXT NOT NULL,
                media_json TEXT NOT NULL DEFAULT '[]',
                position INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)


def seed_feedbacks_if_empty():
    seed = [
        {
            "title": "5 aninhos do Antony",
            "date": "14 de junho de 2026",
            "tag": "Aniversário",
            "excerpt": "Uma festa simplesmente PERFEITA! Espaço, comida e equipe nota 1000.",
            "thumb": "images/hero-1.jpeg",
            "text": (
                "No dia 14/06/2026 comemoramos os 5 aninhos do meu filho Antony e foi uma festa simplesmente PERFEITA!!!\n\n"
                "O Buffet Jardim dos Sonhos é maravilhoso, espaço aconchegante, bonito e com muitas atrações. "
                "A comida é deliciosa, bem servida, quentinha e de muita qualidade, sem contar com a atenção e simpatia de toda a equipe, "
                "desde os monitores, os garçons, gerente e recreação.\n\nTodos os convidados elogiaram.\n\n"
                "Eu recomendo de olhos fechados o Buffet, espaço, serviço e pessoas, nota 1000.\n\n"
                "O meu muito obrigada, a família Buffet Jardim dos Sonhos por nos proporcionarem um dia incrível e inesquecível.\n\n"
                "⭐⭐⭐⭐⭐"
            ),
            "author": "Alaina Oliveira",
            "role": "Mãe do aniversariante · 4 avaliações",
            "media": ["images/hero-1.jpeg", "images/hero-2.jpeg", "images/hero-3.jpeg"],
        },
        {
            "title": "Festa da Emilly",
            "date": "Junho de 2026",
            "tag": "Aniversário",
            "excerpt": "Ambiente aberto, comida maravilhosa e atendimento incrível — foi perfeito!",
            "thumb": "images/mayara-1.jpeg",
            "text": (
                "🎈 🥳 Segundo ano de festa com o @buffetjardimdossonhos e, mais uma vez, eles superaram todas as expectativas!\n\n"
                "🎂 No 1º aniversário, escolhi porque tinham nota 4.9 no Google, experiência de mais de 30 anos e muitas recomendações! "
                "E realmente: comida incrível, atendimento impecável e um ambiente acolhedor.\n\n"
                "Neste segundo ano não tive dúvidas (e foi ainda melhor)! 💙 🧸 💫\n"
                "É como receber amigos em casa: um espaço onde as pessoas conversam, compartilham e se divertem, "
                "enquanto as crianças têm opções de brincadeiras para todas as idades!\n\n"
                "Cada detalhe mostra o carinho e a dedicação: a casa sempre bem cuidada, a equipe atenciosa, "
                "a comida deliciosa e o acompanhamento de perto no dia da festa 🎉\n\n"
                "Foi um dia de muita alegria e muitos elogios dos convidados. Se Deus permitir, ano que vem estaremos lá novamente. 🙏 ✨"
            ),
            "author": "Mayara Rosa",
            "role": "Mãe da Emilly",
            "media": ["images/mayara-1.jpeg"],
        },
        {
            "title": "Festinha do João",
            "date": "10 de maio de 2026",
            "tag": "Aniversário",
            "excerpt": "Festa linda, equipe feliz, animadores incríveis — dia muito especial.",
            "thumb": "images/card3-1.jpeg",
            "text": (
                "Vou te mandar aqui por escrito!\n\nFoi uma festa linda, tudo muito organizado, a equipe que trabalhou estava feliz, "
                "a limpeza estava excelente, os animadores foram incríveis, foi um dia muito especial, "
                "somos muito gratos por todos que fizeram desse dia ainda mais especial.\n\n"
                "Foi diferenciado por ter os momentos de recreação, a Mari foi muito atenciosa, não temos nenhum ponto negativo.\n\n"
                "⭐⭐⭐⭐⭐"
            ),
            "author": "Beatriz Almeida",
            "role": "Mãe do João",
            "media": ["images/card3-1.jpeg"],
        },
        {
            "title": "Festinha do João",
            "date": "10 de maio de 2026",
            "tag": "Aniversário",
            "excerpt": "Festa linda, equipe feliz, animadores incríveis — dia muito especial.",
            "thumb": "images/card4-1.jpeg",
            "text": (
                "No 1o aniversário, escolhi porque tinham nota 4.9 no Google, experiência de mais de 30 anos e muitas recomendações! "
                "E realmente: comida incrível, atendimento impecável e um ambiente acolhedor.\n\n"
                "Neste segundo ano não tive dúvidas (e foi ainda melhor)! 💙🇬🇧🧸💫 \n\n"
                "É como receber amigos em casa: um espaço onde as pessoas conversam, compartilham e se divertem, "
                "enquanto as crianças têm opções de brincadeiras para todas as idades!\n\n"
                "Cada detalhe mostra o carinho e a dedicação: a casa sempre bem cuidada, a equipe atenciosa, "
                "a comida deliciosa e o acompanhamento de perto no dia da festa 🎉"
            ),
            "author": "Camila Rocha",
            "role": "Paisagista",
            "media": ["images/card4-1.jpeg"],
        },
    ]

    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM feedbacks")
        count = cur.fetchone()["c"]
        if count > 0:
            return
        for i, fb in enumerate(seed):
            cur.execute(
                """
                INSERT INTO feedbacks (title, date, tag, excerpt, thumb, text, author, role, media_json, position)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fb["title"], fb["date"], fb["tag"], fb["excerpt"], fb["thumb"],
                    fb["text"], fb["author"], fb["role"], json.dumps(fb["media"]), i,
                ),
            )


def normalize_images(thumb: str, media: list) -> tuple[str, list]:
    """Garante thumb na galeria e remove duplicatas."""
    seen = set()
    merged = []
    for src in [thumb, *(media or [])]:
        s = (src or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        merged.append(s)
    if not merged:
        return (thumb or "").strip(), []
    new_thumb = (thumb or "").strip() if (thumb or "").strip() in merged else merged[0]
    ordered = [new_thumb] + [m for m in merged if m != new_thumb]
    return new_thumb, ordered


def row_to_feedback(row: sqlite3.Row) -> dict:
    raw = json.loads(row["media_json"] or "[]")
    # Backward compat: older records stored [{"type": "image", "src": "..."}].
    # New records store plain list of image paths/URLs.
    media = []
    for item in raw:
        if isinstance(item, dict):
            src = item.get("src")
            if src:
                media.append(src)
        elif isinstance(item, str):
            media.append(item)

    thumb, media = normalize_images(row["thumb"], media)

    return {
        "id": row["id"],
        "title": row["title"],
        "date": row["date"],
        "tag": row["tag"],
        "excerpt": row["excerpt"],
        "thumb": thumb,
        "text": row["text"],
        "author": row["author"],
        "role": row["role"],
        "media": media,
        "position": row["position"],
    }
