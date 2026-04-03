import os
import re
import secrets
import time
import uuid
from datetime import datetime
from math import ceil

import pymysql
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from sqlalchemy import inspect, or_, text
from werkzeug.utils import secure_filename

from config import Config
from models import Comment, Post, Report, Tag, User, Vote, UNIVERSITY_TAG_PREFIX, db

# Install pymysql as MySQLdb for compatibility when MySQL is enabled.
pymysql.install_as_MySQLdb()

login_manager = LoginManager()
login_manager.login_view = 'login'
LOGIN_ATTEMPTS = {}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'webm', 'mov', 'm4v'}


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.config.setdefault('POSTS_PER_PAGE', int(os.environ.get('POSTS_PER_PAGE', '8')))
    app.config.setdefault('MAX_CONTENT_LENGTH', int(os.environ.get('MAX_CONTENT_LENGTH', str(30 * 1024 * 1024))))
    app.config.setdefault('UPLOAD_FOLDER', os.path.join(app.root_path, 'static', 'uploads'))
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    register_security(app)

    register_routes(app)
    register_error_handlers(app)

    with app.app_context():
        db.create_all()
        ensure_runtime_schema()
        ensure_default_admin()

    return app


def ensure_default_admin():
    if User.query.count() == 0:
        admin = User(username='admin', email='admin@example.com', is_admin=True)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()


def get_csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


def register_security(app):
    @app.context_processor
    def inject_csrf_token():
        return {'csrf_token': get_csrf_token}

    @app.before_request
    def validate_csrf():
        if app.config.get('TESTING'):
            return
        if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            return

        sent_token = (
            request.form.get('_csrf_token')
            or request.headers.get('X-CSRF-Token')
            or request.headers.get('X-CSRFToken')
        )
        if not sent_token or sent_token != session.get('_csrf_token'):
            abort(400)

    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy'] = (
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
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response


def is_rate_limited(key, limit=7, window_seconds=300):
    now = time.time()
    attempts = LOGIN_ATTEMPTS.get(key, [])
    recent_attempts = [stamp for stamp in attempts if now - stamp < window_seconds]
    LOGIN_ATTEMPTS[key] = recent_attempts
    return len(recent_attempts) >= limit


def record_failed_attempt(key):
    LOGIN_ATTEMPTS.setdefault(key, []).append(time.time())


def clear_failed_attempts(key):
    LOGIN_ATTEMPTS.pop(key, None)


def ensure_runtime_schema():
    inspector = inspect(db.engine)
    if 'posts' not in inspector.get_table_names():
        return

    post_columns = {column['name'] for column in inspector.get_columns('posts')}
    alter_statements = []

    if 'media_path' not in post_columns:
        alter_statements.append("ALTER TABLE posts ADD COLUMN media_path VARCHAR(255)")
    if 'media_type' not in post_columns:
        alter_statements.append("ALTER TABLE posts ADD COLUMN media_type VARCHAR(20)")

    if not alter_statements:
        return

    with db.engine.begin() as connection:
        for statement in alter_statements:
            connection.execute(text(statement))


def get_media_kind(filename):
    if not filename or '.' not in filename:
        return None
    extension = filename.rsplit('.', 1)[1].lower()
    if extension in ALLOWED_IMAGE_EXTENSIONS:
        return 'image', extension
    if extension in ALLOWED_VIDEO_EXTENSIONS:
        return 'video', extension
    return None


def save_uploaded_media(file_storage, upload_folder):
    if not file_storage or not file_storage.filename:
        return None, None

    kind_info = get_media_kind(file_storage.filename)
    if not kind_info:
        return None, None

    media_type, extension = kind_info
    filename = secure_filename(f"{uuid.uuid4().hex}.{extension}")
    absolute_path = os.path.join(upload_folder, filename)
    file_storage.save(absolute_path)
    return f"uploads/{filename}", media_type


def remove_media_file(media_path, app_root):
    if not media_path:
        return
    absolute_path = os.path.join(app_root, 'static', media_path)
    if os.path.exists(absolute_path):
        os.remove(absolute_path)


def register_routes(app):
    @app.route('/')
    def index():
        category = request.args.get('category', '').strip().lower()
        tag_name = request.args.get('tag', '').strip().lower()
        university_slug = request.args.get('university', '').strip().lower()
        search = request.args.get('search', '').strip()
        sort = request.args.get('sort', 'recent').strip().lower()
        page = request.args.get('page', 1, type=int)

        query = Post.query

        valid_categories = {'professor', 'course', 'campus', 'general'}
        if category in valid_categories:
            query = query.filter_by(category=category)

        if tag_name:
            query = query.join(Post.tags).filter(Tag.name == tag_name)

        normalized_university_slug = normalize_university_slug(university_slug) if university_slug else None
        if normalized_university_slug:
            university_tag_name = f'{UNIVERSITY_TAG_PREFIX}{normalized_university_slug}'
            query = query.join(Post.tags).filter(Tag.name == university_tag_name)

        if search:
            search_term = f'%{search}%'
            query = query.outerjoin(Post.tags).filter(
                or_(
                    Post.title.ilike(search_term),
                    Post.content.ilike(search_term),
                    Tag.name.ilike(search_term)
                )
            )

        posts = query.distinct().all()
        if sort == 'top':
            posts = sorted(posts, key=lambda post: (post.vote_count, post.created_at), reverse=True)
        else:
            posts = sorted(posts, key=lambda post: post.created_at, reverse=True)

        per_page = app.config['POSTS_PER_PAGE']
        total_posts = len(posts)
        total_pages = max(1, ceil(total_posts / per_page))
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        end = start + per_page
        posts = posts[start:end]

        all_tags = Tag.query.filter(~Tag.name.startswith(UNIVERSITY_TAG_PREFIX)).order_by(Tag.name.asc()).all()
        university_tags = Tag.query.filter(
            Tag.name.startswith(UNIVERSITY_TAG_PREFIX)
        ).order_by(Tag.name.asc()).all()
        university_filters = [
            {
                'slug': uni_tag.name[len(UNIVERSITY_TAG_PREFIX):],
                'label': uni_tag.name[len(UNIVERSITY_TAG_PREFIX):].replace('-', ' ').title(),
            }
            for uni_tag in university_tags
        ]

        return render_template(
            'index.html',
            posts=posts,
            tags=all_tags,
            university_filters=university_filters,
            current_category=category or None,
            current_tag=tag_name or None,
            current_university=normalized_university_slug,
            search=search or None,
            current_sort=sort,
            page=page,
            total_pages=total_pages
        )

    @app.route('/post/new', methods=['GET', 'POST'])
    @login_required
    def create_post():
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            content = request.form.get('content', '').strip()
            category = request.form.get('category', '').strip().lower()
            university = request.form.get('university', '').strip()
            is_anonymous = True
            tags = request.form.get('tags', '')
            media_file = request.files.get('media')
            normalized_university = normalize_university_slug(university)

            if (
                not title
                or not content
                or category not in {'professor', 'course', 'campus', 'general'}
                or not normalized_university
            ):
                flash('Please fill in all required fields with a valid category and university.', 'danger')
                return redirect(url_for('create_post'))

            if media_file and media_file.filename and not get_media_kind(media_file.filename):
                flash('Unsupported media format. Use images (png/jpg/jpeg/gif/webp) or videos (mp4/webm/mov/m4v).', 'danger')
                return redirect(url_for('create_post'))

            media_path, media_type = save_uploaded_media(media_file, app.config['UPLOAD_FOLDER'])

            post = Post(
                author_id=current_user.id,
                title=title,
                content=content,
                category=category,
                is_anonymous=is_anonymous,
                media_path=media_path,
                media_type=media_type
            )
            db.session.add(post)
            db.session.flush()

            sync_post_tags(post, tags, normalized_university)
            db.session.commit()

            flash('Your post has been published.', 'success')
            return redirect(url_for('view_post', post_id=post.id))

        return render_template('create_post.html', edit_mode=False)

    @app.route('/post/<int:post_id>')
    def view_post(post_id):
        post = Post.query.get_or_404(post_id)
        comments = Comment.query.filter_by(post_id=post_id).order_by(Comment.created_at.desc()).all()

        user_vote = None
        if current_user.is_authenticated:
            vote = Vote.query.filter_by(user_id=current_user.id, post_id=post_id).first()
            if vote:
                user_vote = vote.vote_type

        return render_template('post_detail.html', post=post, comments=comments, user_vote=user_vote)

    @app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_post(post_id):
        post = Post.query.get_or_404(post_id)

        if post.author_id != current_user.id and not current_user.is_admin:
            flash('You do not have permission to edit this post.', 'danger')
            return redirect(url_for('view_post', post_id=post_id))

        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            content = request.form.get('content', '').strip()
            category = request.form.get('category', '').strip().lower()
            university = request.form.get('university', '').strip()
            media_file = request.files.get('media')
            normalized_university = normalize_university_slug(university)

            if (
                not title
                or not content
                or category not in {'professor', 'course', 'campus', 'general'}
                or not normalized_university
            ):
                flash('Please fill in all required fields with a valid category and university.', 'danger')
                return redirect(url_for('edit_post', post_id=post_id))

            if media_file and media_file.filename and not get_media_kind(media_file.filename):
                flash('Unsupported media format. Use images (png/jpg/jpeg/gif/webp) or videos (mp4/webm/mov/m4v).', 'danger')
                return redirect(url_for('edit_post', post_id=post_id))

            post.title = title
            post.content = content
            post.category = category
            post.is_anonymous = True
            post.updated_at = datetime.utcnow()

            if request.form.get('remove_media') == 'on':
                remove_media_file(post.media_path, app.root_path)
                post.media_path = None
                post.media_type = None

            if media_file and media_file.filename:
                remove_media_file(post.media_path, app.root_path)
                media_path, media_type = save_uploaded_media(media_file, app.config['UPLOAD_FOLDER'])
                post.media_path = media_path
                post.media_type = media_type

            sync_post_tags(post, request.form.get('tags', ''), normalized_university)

            db.session.commit()
            flash('Post updated successfully.', 'success')
            return redirect(url_for('view_post', post_id=post_id))

        tags_string = ', '.join(
            tag.name for tag in post.tags if not tag.name.startswith(UNIVERSITY_TAG_PREFIX)
        )
        return render_template(
            'create_post.html',
            post=post,
            tags_string=tags_string,
            university_value=post.university_label,
            edit_mode=True,
        )

    @app.route('/post/<int:post_id>/delete', methods=['POST'])
    @login_required
    def delete_post(post_id):
        post = Post.query.get_or_404(post_id)

        if post.author_id != current_user.id and not current_user.is_admin:
            flash('You do not have permission to delete this post.', 'danger')
            return redirect(url_for('view_post', post_id=post_id))

        remove_media_file(post.media_path, app.root_path)
        db.session.delete(post)
        db.session.commit()
        flash('Post deleted successfully.', 'success')
        return redirect(url_for('index'))

    @app.route('/post/<int:post_id>/comment', methods=['POST'])
    @login_required
    def add_comment(post_id):
        Post.query.get_or_404(post_id)
        content = request.form.get('content', '').strip()

        if not content:
            flash('Comment cannot be empty.', 'danger')
            return redirect(url_for('view_post', post_id=post_id))

        comment = Comment(post_id=post_id, author_id=current_user.id, content=content)
        db.session.add(comment)
        db.session.commit()

        flash('Comment added successfully.', 'success')
        return redirect(url_for('view_post', post_id=post_id))

    @app.route('/post/<int:post_id>/vote', methods=['POST'])
    @login_required
    def vote_post(post_id):
        post = Post.query.get_or_404(post_id)

        try:
            vote_type = int(request.form.get('vote_type', '0'))
        except ValueError:
            return jsonify({'error': 'Invalid vote type'}), 400

        if vote_type not in {1, -1}:
            return jsonify({'error': 'Invalid vote type'}), 400

        existing_vote = Vote.query.filter_by(user_id=current_user.id, post_id=post_id).first()
        user_vote = vote_type

        if existing_vote:
            if existing_vote.vote_type == vote_type:
                db.session.delete(existing_vote)
                user_vote = None
            else:
                existing_vote.vote_type = vote_type
        else:
            db.session.add(Vote(user_id=current_user.id, post_id=post_id, vote_type=vote_type))

        db.session.commit()

        refreshed_post = db.session.get(Post, post.id)
        return jsonify({'success': True, 'vote_count': refreshed_post.vote_count, 'user_vote': user_vote})

    @app.route('/post/<int:post_id>/report', methods=['GET', 'POST'])
    @login_required
    def report_post(post_id):
        post = Post.query.get_or_404(post_id)

        if request.method == 'POST':
            reason = request.form.get('reason', '').strip()

            if not reason:
                flash('Please provide a reason for reporting.', 'danger')
                return redirect(url_for('view_post', post_id=post_id))

            existing_report = Report.query.filter_by(
                reporter_id=current_user.id,
                post_id=post_id,
                status='pending'
            ).first()

            if existing_report:
                flash('You have already reported this post.', 'warning')
                return redirect(url_for('view_post', post_id=post_id))

            report = Report(reporter_id=current_user.id, post_id=post_id, reason=reason)
            db.session.add(report)
            db.session.commit()

            flash('Thank you. An admin will review this report.', 'success')
            return redirect(url_for('view_post', post_id=post_id))

        return render_template('report_post.html', post=post)

    @app.route('/auth/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('index'))

        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            confirm_password = request.form.get('confirm_password', '')

            if not username or not email or not password:
                flash('All fields are required.', 'danger')
                return redirect(url_for('register'))

            if password != confirm_password:
                flash('Passwords do not match.', 'danger')
                return redirect(url_for('register'))

            if User.query.filter_by(username=username).first():
                flash('Username already exists.', 'danger')
                return redirect(url_for('register'))

            if User.query.filter_by(email=email).first():
                flash('Email already registered.', 'danger')
                return redirect(url_for('register'))

            user = User(username=username, email=email, is_admin=(User.query.count() == 0))
            user.set_password(password)
            db.session.add(user)
            db.session.commit()

            flash('Registration successful. Please log in.', 'success')
            return redirect(url_for('login'))

        return render_template('register.html')

    @app.route('/auth/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('index'))

        if request.method == 'POST':
            client_key = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown')
            if is_rate_limited(client_key):
                flash('Too many failed login attempts. Please wait a few minutes and try again.', 'danger')
                return redirect(url_for('login'))

            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            user = User.query.filter_by(username=username).first()

            if user and user.check_password(password):
                login_user(user)
                session.permanent = True
                clear_failed_attempts(client_key)
                next_page = request.args.get('next')
                flash(f'Welcome back, {username}.', 'success')
                return redirect(next_page or url_for('index'))

            record_failed_attempt(client_key)
            flash('Invalid username or password.', 'danger')

        return render_template('login.html')

    @app.route('/auth/logout')
    @login_required
    def logout():
        logout_user()
        flash('You have been logged out.', 'info')
        return redirect(url_for('index'))

    @app.route('/profile')
    @login_required
    def profile():
        user_posts = Post.query.filter_by(author_id=current_user.id).order_by(Post.created_at.desc()).all()
        user_comments = Comment.query.filter_by(author_id=current_user.id).order_by(Comment.created_at.desc()).all()
        return render_template('profile.html', user_posts=user_posts, user_comments=user_comments)

    @app.route('/admin')
    @login_required
    def admin_dashboard():
        if not current_user.is_admin:
            abort(403)

        pending_reports = Report.query.filter_by(status='pending').order_by(Report.created_at.desc()).all()
        resolved_reports = Report.query.filter(Report.status != 'pending').order_by(Report.created_at.desc()).limit(10).all()
        all_posts = Post.query.order_by(Post.created_at.desc()).all()
        all_users = User.query.order_by(User.created_at.desc()).all()
        stats = {
            'users': User.query.count(),
            'posts': Post.query.count(),
            'comments': Comment.query.count(),
            'reports': Report.query.count(),
            'tags': Tag.query.count(),
        }

        return render_template(
            'admin_dashboard.html',
            pending_reports=pending_reports,
            resolved_reports=resolved_reports,
            all_posts=all_posts,
            all_users=all_users,
            stats=stats
        )

    @app.route('/admin/report/<int:report_id>/resolve', methods=['POST'])
    @login_required
    def resolve_report(report_id):
        if not current_user.is_admin:
            abort(403)

        report = Report.query.get_or_404(report_id)
        action = request.form.get('action')

        if action == 'delete_post':
            post = db.session.get(Post, report.post_id)
            if post:
                db.session.delete(post)
            report.status = 'resolved'
        elif action == 'dismiss':
            report.status = 'dismissed'
        else:
            report.status = 'resolved'

        report.reviewed_at = datetime.utcnow()
        db.session.commit()

        flash('Report has been processed.', 'success')
        return redirect(url_for('admin_dashboard'))

    @app.route('/admin/user/<int:user_id>/toggle_admin', methods=['POST'])
    @login_required
    def toggle_admin(user_id):
        if not current_user.is_admin:
            abort(403)

        user = User.query.get_or_404(user_id)
        if user.id == current_user.id:
            flash('You cannot remove your own admin privileges.', 'danger')
            return redirect(url_for('admin_dashboard'))

        user.is_admin = not user.is_admin
        db.session.commit()

        status = 'granted' if user.is_admin else 'revoked'
        flash(f'Admin privileges {status} for {user.username}.', 'success')
        return redirect(url_for('admin_dashboard'))

    @app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
    @login_required
    def delete_user(user_id):
        if not current_user.is_admin:
            abort(403)

        user = User.query.get_or_404(user_id)
        if user.id == current_user.id:
            flash('You cannot delete your own account.', 'danger')
            return redirect(url_for('admin_dashboard'))

        db.session.delete(user)
        db.session.commit()

        flash(f'User {user.username} has been deleted.', 'success')
        return redirect(url_for('admin_dashboard'))

    @app.route('/api/tags/search')
    def search_tags():
        query = request.args.get('q', '').strip().lower()
        if not query:
            return jsonify([])

        tags = Tag.query.filter(
            Tag.name.contains(query),
            ~Tag.name.startswith(UNIVERSITY_TAG_PREFIX)
        ).order_by(Tag.name.asc()).limit(10).all()
        return jsonify([{'name': tag.name} for tag in tags])


def normalize_university_slug(raw_value):
    cleaned = raw_value.strip().lower()
    if not cleaned:
        return None
    normalized = re.sub(r'[^a-z0-9]+', '-', cleaned).strip('-')
    return normalized or None


def sync_post_tags(post, raw_tags, university_slug):
    tag_names = []
    seen = set()
    for value in raw_tags.split(','):
        cleaned = value.strip().lower().lstrip('#')
        if cleaned.startswith(UNIVERSITY_TAG_PREFIX):
            continue
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            tag_names.append(cleaned)

    if university_slug:
        university_tag_name = f'{UNIVERSITY_TAG_PREFIX}{university_slug}'
        if university_tag_name not in seen:
            tag_names.insert(0, university_tag_name)

    post.tags.clear()
    for tag_name in tag_names:
        tag = Tag.query.filter_by(name=tag_name).first()
        if not tag:
            tag = Tag(name=tag_name)
            db.session.add(tag)
            db.session.flush()
        post.tags.append(tag)


def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('404.html'), 404

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template('403.html'), 403


app = create_app()


if __name__ == '__main__':
    host = os.getenv('HOST', '127.0.0.1')
    port = int(os.getenv('PORT', '5000'))

    print("\n" + "=" * 50)
    print("Rate My Uni Life is running")
    print("=" * 50)
    print(f"Database: {app.config['SQLALCHEMY_DATABASE_URI']}")
    print(f"Access the application at: http://{host}:{port}")
    print("Default admin login: username='admin', password='admin123'")
    print("=" * 50 + "\n")
    app.run(host=host, port=port, debug=True)
