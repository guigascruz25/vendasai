import os
import re
import json
import uuid
import pathlib
import traceback
from datetime import timedelta
from functools import wraps

from flask import (Flask, jsonify, request, render_template,
                   redirect, url_for, session, g, Response, stream_with_context)
from flask_cors import CORS
from flask_compress import Compress
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from db import (init_db, get_user_by_username, get_all_users, create_user,
                delete_user, update_user_password,
                save_document, get_all_documents, toggle_document, delete_document,
                save_chat_message, get_chat_history, clear_chat_history,
                get_config, save_config)
from rag import build_system_prompt, extract_pdf_text

import anthropic


# ── App setup ─────────────────────────────────────────────────────────
def _cfg(key, default=""):
    env_path = pathlib.Path(__file__).resolve().parent / ".env"
    env_vars = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line)
            if m:
                env_vars[m.group(1)] = m.group(2).strip()
    return os.environ.get(key) or env_vars.get(key, default)


app = Flask(__name__)
app.config["SECRET_KEY"] = _cfg("SECRET_KEY", "vendasai-secret-fallback")
app.config["SESSION_PERMANENT"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  # 30 MB max upload

CORS(app)
Compress(app)
init_db()

UPLOAD_FOLDER = pathlib.Path(__file__).resolve().parent / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)


def get_anthropic_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY") or get_config().get("anthropic_api_key") or _cfg("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=api_key)


# ── Auth decorators ───────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("page_login", next=request.path))
        g.user_id = session["user_id"]
        g.username = session["username"]
        g.role = session["role"]
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("page_login"))
        if session.get("role") != "admin":
            return redirect(url_for("page_chat"))
        g.user_id = session["user_id"]
        g.username = session["username"]
        g.role = "admin"
        return f(*args, **kwargs)
    return decorated


# ── Error handler ─────────────────────────────────────────────────────
@app.errorhandler(Exception)
def handle_exception(e):
    print(f"[ERROR] {traceback.format_exc()}")
    return jsonify({"error": "Erro interno", "detail": str(e)}), 500


# ── Auth routes ───────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def page_login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        next_url = request.form.get("next", "/")
        user = get_user_by_username(username)
        if user and check_password_hash(user["password"], password):
            session.permanent = True
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(next_url or "/")
        error = "Usuário ou senha incorretos."
    next_url = request.args.get("next", "/")
    return render_template("login.html", error=error, next=next_url)


@app.route("/logout")
def page_logout():
    session.clear()
    return redirect(url_for("page_login"))


# ── Page routes ───────────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    return redirect(url_for("page_chat"))


@app.route("/chat")
@login_required
def page_chat():
    history = get_chat_history(g.user_id, limit=50)
    return render_template("chat.html", active="chat", history=history)


@app.route("/admin")
@admin_required
def page_admin():
    return redirect(url_for("page_admin_docs"))


@app.route("/admin/docs")
@admin_required
def page_admin_docs():
    docs = get_all_documents()
    return render_template("admin_docs.html", active="docs", docs=docs)


@app.route("/admin/users")
@admin_required
def page_admin_users():
    users = get_all_users()
    return render_template("admin_users.html", active="users", users=users)


@app.route("/admin/config")
@admin_required
def page_admin_config():
    cfg = get_config()
    return render_template("admin_config.html", active="config", cfg=cfg)


# ── API: Chat ─────────────────────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    data = request.get_json() or {}
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "Mensagem vazia"}), 400

    save_chat_message(g.user_id, "user", user_message)

    history = get_chat_history(g.user_id, limit=12)
    messages = [{"role": r["role"], "content": r["content"]} for r in history]

    system = build_system_prompt()
    client = get_anthropic_client()

    def generate():
        full_response = ""
        try:
            with client.messages.stream(
                model="claude-opus-4-5",
                max_tokens=1024,
                system=system,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield f"data: {json.dumps({'text': text})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            if full_response:
                save_chat_message(g.user_id, "assistant", full_response)
            yield f"data: {json.dumps({'done': True})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.route("/api/chat/clear", methods=["POST"])
@login_required
def api_chat_clear():
    clear_chat_history(g.user_id)
    return jsonify({"ok": True})


# ── API: Documents ────────────────────────────────────────────────────
@app.route("/admin/docs/upload", methods=["POST"])
@admin_required
def api_upload_doc():
    if "file" not in request.files:
        return jsonify({"error": "Nenhum arquivo enviado"}), 400
    f = request.files["file"]
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Apenas arquivos PDF são aceitos"}), 400

    original_name = secure_filename(f.filename)
    stored_name = f"{uuid.uuid4().hex}.pdf"
    filepath = UPLOAD_FOLDER / stored_name
    f.save(str(filepath))

    text, pages = extract_pdf_text(str(filepath))
    category = request.form.get("category", "geral")

    save_document(
        filename=original_name,
        stored_name=stored_name,
        file_size=filepath.stat().st_size,
        page_count=pages,
        extracted_text=text,
        category=category,
        uploaded_by=g.user_id
    )
    return jsonify({"ok": True, "pages": pages, "chars": len(text)})


@app.route("/admin/docs/<int:doc_id>/toggle", methods=["POST"])
@admin_required
def api_toggle_doc(doc_id):
    toggle_document(doc_id)
    return jsonify({"ok": True})


@app.route("/admin/docs/<int:doc_id>/delete", methods=["POST"])
@admin_required
def api_delete_doc(doc_id):
    stored_name = delete_document(doc_id)
    if stored_name:
        filepath = UPLOAD_FOLDER / stored_name
        if filepath.exists():
            filepath.unlink()
    return jsonify({"ok": True})


# ── API: Users ────────────────────────────────────────────────────────
@app.route("/admin/users/add", methods=["POST"])
@admin_required
def api_add_user():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    role = data.get("role", "member")
    if not username or not password:
        return jsonify({"error": "Usuário e senha são obrigatórios"}), 400
    try:
        create_user(username, password, role)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": "Usuário já existe"}), 400


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def api_delete_user(user_id):
    if user_id == g.user_id:
        return jsonify({"error": "Não é possível remover seu próprio usuário"}), 400
    delete_user(user_id)
    return jsonify({"ok": True})


@app.route("/admin/users/<int:user_id>/password", methods=["POST"])
@admin_required
def api_change_user_password(user_id):
    data = request.get_json() or {}
    new_pw = data.get("password", "").strip()
    if not new_pw or len(new_pw) < 4:
        return jsonify({"error": "Senha deve ter pelo menos 4 caracteres"}), 400
    update_user_password(user_id, new_pw)
    return jsonify({"ok": True})


# ── API: Config ───────────────────────────────────────────────────────
@app.route("/admin/config/save", methods=["POST"])
@admin_required
def api_save_config():
    data = request.get_json() or {}
    allowed = {"anthropic_api_key", "system_prompt", "max_context_chars"}
    filtered = {k: v for k, v in data.items() if k in allowed}
    save_config(filtered)
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)
