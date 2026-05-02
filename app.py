import os
import secrets
import re

import pymysql
from flask import Flask, abort, render_template, request, session
from markupsafe import Markup, escape

from config import Config
from flask_babel import Babel
from models import TAG_NAME_MAX_LENGTH, Tag, User, db
from routes import admin_bp, auth_bp, community_bp, main_bp, posts_bp, profile_bp
from utils import UNIVERSITY_TAG_PREFIX, available_languages, university_label_from_slug

pymysql.install_as_MySQLdb()

from flask_login import LoginManager
from sqlalchemy import inspect, text

login_manager = LoginManager()
login_manager.login_view = "auth.login"
babel = Babel()


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def get_locale():
    languages = available_languages()
    selected = session.get("lang")
    if selected in languages:
        return selected
    return request.accept_languages.best_match(languages.keys()) or "en"


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.config.setdefault("POSTS_PER_PAGE", int(os.environ.get("POSTS_PER_PAGE", "8")))
    app.config.setdefault("MAX_CONTENT_LENGTH", int(os.environ.get("MAX_CONTENT_LENGTH", str(30 * 1024 * 1024))))
    app.config.setdefault("UPLOAD_FOLDER", os.path.join(app.root_path, "static", "uploads"))
    app.config.setdefault("LANGUAGES", {"en": "EN", "uz": "UZ"})
    app.config.setdefault("BABEL_DEFAULT_LOCALE", "en")
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    babel.init_app(app, locale_selector=get_locale)
    app.jinja_env.filters["format_post_content"] = format_post_content

    register_security(app)
    register_blueprints(app)
    register_context(app)
    register_error_handlers(app)

    with app.app_context():
        db.create_all()
        ensure_runtime_schema()
        ensure_default_admin()
        ensure_community_memberships()

    return app


def format_post_content(value):
    if not value:
        return ""

    normalized = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs = [segment.strip() for segment in re.split(r"\n\s*\n", normalized) if segment.strip()]

    if not paragraphs:
        return ""

    rendered = []
    for paragraph in paragraphs:
        lines = "<br>".join(escape(line) for line in paragraph.split("\n"))
        rendered.append(f"<p>{lines}</p>")

    return Markup("".join(rendered))


def register_blueprints(app):
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(posts_bp)
    app.register_blueprint(community_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(profile_bp)


def register_context(app):
    from flask_babel import gettext as _

    @app.context_processor
    def inject_globals():
        community_tags = (
            Tag.query.filter(Tag.name.startswith(UNIVERSITY_TAG_PREFIX))
            .order_by(Tag.name.asc())
            .all()
        )
        communities = [
            {
                "slug": tag.name[len(UNIVERSITY_TAG_PREFIX):],
                "label": university_label_from_slug(tag.name[len(UNIVERSITY_TAG_PREFIX):]),
            }
            for tag in community_tags
        ]
        return {
            "_": _,
            "csrf_token": get_csrf_token,
            "current_language": get_locale(),
            "languages": app.config["LANGUAGES"],
            "communities": communities,
        }


def get_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def register_security(app):
    @app.before_request
    def validate_csrf():
        if app.config.get("TESTING"):
            return
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return

        sent_token = (
            request.form.get("_csrf_token")
            or request.headers.get("X-CSRF-Token")
            or request.headers.get("X-CSRFToken")
        )
        if not sent_token or sent_token != session.get("_csrf_token"):
            abort(400)

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com 'unsafe-inline'; "
            "script-src 'self' https://cdn.jsdelivr.net https://code.jquery.com; "
            "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        )
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def ensure_runtime_schema():
    inspector = inspect(db.engine)
    if "posts" not in inspector.get_table_names():
        return

    post_columns = {column["name"] for column in inspector.get_columns("posts")}
    alter_statements = []

    if "media_path" not in post_columns:
        alter_statements.append("ALTER TABLE posts ADD COLUMN media_path VARCHAR(255)")
    if "media_type" not in post_columns:
        alter_statements.append("ALTER TABLE posts ADD COLUMN media_type VARCHAR(20)")

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "university_slug" not in user_columns:
        alter_statements.append("ALTER TABLE users ADD COLUMN university_slug VARCHAR(100)")

    if "tags" in inspector.get_table_names():
        tag_name_column = next(
            (column for column in inspector.get_columns("tags") if column["name"] == "name"),
            None,
        )
        current_length = getattr(tag_name_column.get("type"), "length", None) if tag_name_column else None
        if current_length and current_length < TAG_NAME_MAX_LENGTH:
            if db.engine.dialect.name == "mysql":
                alter_statements.append(
                    f"ALTER TABLE tags MODIFY COLUMN name VARCHAR({TAG_NAME_MAX_LENGTH}) NOT NULL"
                )

    if not alter_statements:
        return

    with db.engine.begin() as connection:
        for statement in alter_statements:
            connection.execute(text(statement))


def ensure_default_admin():
    if User.query.count() == 0:
        admin_password = os.environ.get("ADMIN_PASSWORD")
        generated_password = None
        if not admin_password:
            generated_password = secrets.token_urlsafe(16)
            admin_password = generated_password

        admin = User(username="admin", email="admin@example.com", is_admin=True)
        admin.set_password(admin_password)
        db.session.add(admin)
        db.session.commit()

        if generated_password:
            print("\n" + "=" * 50)
            print("Rate My Uni Life default admin password")
            print(generated_password)
            print("=" * 50 + "\n")


def ensure_community_memberships():
    community_tags = {
        tag.name: tag
        for tag in Tag.query.filter(Tag.name.startswith(UNIVERSITY_TAG_PREFIX)).all()
    }
    changed = False

    for user in User.query.filter(User.university_slug.isnot(None)).all():
        if not user.university_slug:
            continue

        community_tag_name = f"{UNIVERSITY_TAG_PREFIX}{user.university_slug}"
        community_tag = community_tags.get(community_tag_name)
        if community_tag is None:
            community_tag = Tag(name=community_tag_name)
            db.session.add(community_tag)
            db.session.flush()
            community_tags[community_tag_name] = community_tag
            changed = True

        if community_tag not in user.communities:
            user.communities.append(community_tag)
            changed = True

    if changed:
        db.session.commit()


def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template("404.html"), 404

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template("403.html"), 403


if __name__ == "__main__":
    app = create_app()
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))

    print("\n" + "=" * 50)
    print("Rate My Uni Life is running")
    print("=" * 50)
    print(f"Database: {app.config['SQLALCHEMY_DATABASE_URI']}")
    print(f"Access the application at: http://{host}:{port}")
    print("=" * 50 + "\n")
    app.run(host=host, port=port, debug=True)
