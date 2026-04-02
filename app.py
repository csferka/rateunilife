import os
from datetime import datetime

import pymysql
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from sqlalchemy import or_

from config import Config
from models import Comment, Post, Report, Tag, User, Vote, db

# Install pymysql as MySQLdb for compatibility when MySQL is enabled.
pymysql.install_as_MySQLdb()

login_manager = LoginManager()
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)

    register_routes(app)
    register_error_handlers(app)

    with app.app_context():
        db.create_all()
        ensure_default_admin()

    return app


def ensure_default_admin():
    if User.query.count() == 0:
        admin = User(username='admin', email='admin@example.com', is_admin=True)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()


def register_routes(app):
    @app.route('/')
    def index():
        category = request.args.get('category', '').strip().lower()
        tag_name = request.args.get('tag', '').strip().lower()
        search = request.args.get('search', '').strip()
        sort = request.args.get('sort', 'recent').strip().lower()

        query = Post.query

        valid_categories = {'professor', 'course', 'campus', 'general'}
        if category in valid_categories:
            query = query.filter_by(category=category)

        if tag_name:
            query = query.join(Post.tags).filter(Tag.name == tag_name)

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

        all_tags = Tag.query.order_by(Tag.name.asc()).all()

        return render_template(
            'index.html',
            posts=posts,
            tags=all_tags,
            current_category=category or None,
            current_tag=tag_name or None,
            search=search or None,
            current_sort=sort
        )

    @app.route('/post/new', methods=['GET', 'POST'])
    @login_required
    def create_post():
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            content = request.form.get('content', '').strip()
            category = request.form.get('category', '').strip().lower()
            is_anonymous = request.form.get('is_anonymous') == 'on'
            tags = request.form.get('tags', '')

            if not title or not content or category not in {'professor', 'course', 'campus', 'general'}:
                flash('Please fill in all required fields with a valid category.', 'danger')
                return redirect(url_for('create_post'))

            post = Post(
                author_id=current_user.id,
                title=title,
                content=content,
                category=category,
                is_anonymous=is_anonymous
            )
            db.session.add(post)
            db.session.flush()

            sync_post_tags(post, tags)
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

            if not title or not content or category not in {'professor', 'course', 'campus', 'general'}:
                flash('Please fill in all required fields with a valid category.', 'danger')
                return redirect(url_for('edit_post', post_id=post_id))

            post.title = title
            post.content = content
            post.category = category
            post.is_anonymous = request.form.get('is_anonymous') == 'on'
            post.updated_at = datetime.utcnow()
            sync_post_tags(post, request.form.get('tags', ''))

            db.session.commit()
            flash('Post updated successfully.', 'success')
            return redirect(url_for('view_post', post_id=post_id))

        tags_string = ', '.join(tag.name for tag in post.tags)
        return render_template('create_post.html', post=post, tags_string=tags_string, edit_mode=True)

    @app.route('/post/<int:post_id>/delete', methods=['POST'])
    @login_required
    def delete_post(post_id):
        post = Post.query.get_or_404(post_id)

        if post.author_id != current_user.id and not current_user.is_admin:
            flash('You do not have permission to delete this post.', 'danger')
            return redirect(url_for('view_post', post_id=post_id))

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
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            user = User.query.filter_by(username=username).first()

            if user and user.check_password(password):
                login_user(user)
                next_page = request.args.get('next')
                flash(f'Welcome back, {username}.', 'success')
                return redirect(next_page or url_for('index'))

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

        tags = Tag.query.filter(Tag.name.contains(query)).order_by(Tag.name.asc()).limit(10).all()
        return jsonify([{'name': tag.name} for tag in tags])


def sync_post_tags(post, raw_tags):
    tag_names = []
    seen = set()
    for value in raw_tags.split(','):
        cleaned = value.strip().lower().lstrip('#')
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            tag_names.append(cleaned)

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
