from datetime import datetime

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from flask_babel import gettext as _
from models import Comment, Post, Report, Vote, db
from utils import get_media_kind, normalize_university_slug, remove_media_file, save_uploaded_media, sync_post_tags

posts_bp = Blueprint("posts", __name__)


@posts_bp.route("/post/new", methods=["GET", "POST"])
@login_required
def create_post():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category = request.form.get("category", "").strip().lower()
        university = request.form.get("university", "").strip()
        is_anonymous = True
        tags = request.form.get("tags", "")
        media_file = request.files.get("media")
        normalized_university = normalize_university_slug(university)

        if (
            not title
            or not content
            or category not in {"professor", "course", "campus", "general"}
            or not normalized_university
        ):
            flash(_("Please fill in all required fields with a valid category and university."), "danger")
            return redirect(url_for("posts.create_post"))

        if len(content) > 2000:
            flash(_("Post content must be 2000 characters or fewer."), "danger")
            return redirect(url_for("posts.create_post"))

        if media_file and media_file.filename and not get_media_kind(media_file.filename):
            flash(
                _("Unsupported media format. Use images (png/jpg/jpeg/gif/webp) or videos (mp4/webm/mov/m4v)."),
                "danger",
            )
            return redirect(url_for("posts.create_post"))

        media_path, media_type = save_uploaded_media(media_file, current_app.config["UPLOAD_FOLDER"])

        post = Post(
            author_id=current_user.id,
            title=title,
            content=content,
            category=category,
            is_anonymous=is_anonymous,
            media_path=media_path,
            media_type=media_type,
        )
        db.session.add(post)
        db.session.flush()

        sync_post_tags(post, tags, normalized_university)
        db.session.commit()

        flash(_("Your post has been published."), "success")
        return redirect(url_for("posts.view_post", post_id=post.id))

    return render_template("create_post.html", edit_mode=False)


@posts_bp.route("/post/<int:post_id>")
def view_post(post_id):
    post = Post.query.get_or_404(post_id)
    comments = Comment.query.filter_by(post_id=post_id).order_by(Comment.created_at.desc()).all()

    user_vote = None
    if current_user.is_authenticated:
        vote = Vote.query.filter_by(user_id=current_user.id, post_id=post_id).first()
        if vote:
            user_vote = vote.vote_type

    return render_template("post_detail.html", post=post, comments=comments, user_vote=user_vote)


@posts_bp.route("/post/<int:post_id>/edit", methods=["GET", "POST"])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)

    if post.author_id != current_user.id and not current_user.is_admin:
        flash(_("You do not have permission to edit this post."), "danger")
        return redirect(url_for("posts.view_post", post_id=post_id))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category = request.form.get("category", "").strip().lower()
        university = request.form.get("university", "").strip()
        media_file = request.files.get("media")
        normalized_university = normalize_university_slug(university)

        if (
            not title
            or not content
            or category not in {"professor", "course", "campus", "general"}
            or not normalized_university
        ):
            flash(_("Please fill in all required fields with a valid category and university."), "danger")
            return redirect(url_for("posts.edit_post", post_id=post_id))

        if len(content) > 2000:
            flash(_("Post content must be 2000 characters or fewer."), "danger")
            return redirect(url_for("posts.edit_post", post_id=post_id))

        if media_file and media_file.filename and not get_media_kind(media_file.filename):
            flash(
                _("Unsupported media format. Use images (png/jpg/jpeg/gif/webp) or videos (mp4/webm/mov/m4v)."),
                "danger",
            )
            return redirect(url_for("posts.edit_post", post_id=post_id))

        post.title = title
        post.content = content
        post.category = category
        post.is_anonymous = True
        post.updated_at = datetime.utcnow()

        if request.form.get("remove_media") == "on":
            remove_media_file(post.media_path, current_app.root_path)
            post.media_path = None
            post.media_type = None

        if media_file and media_file.filename:
            remove_media_file(post.media_path, current_app.root_path)
            media_path, media_type = save_uploaded_media(media_file, current_app.config["UPLOAD_FOLDER"])
            post.media_path = media_path
            post.media_type = media_type

        sync_post_tags(post, request.form.get("tags", ""), normalized_university)

        db.session.commit()
        flash(_("Post updated successfully."), "success")
        return redirect(url_for("posts.view_post", post_id=post_id))

    tags_string = ", ".join(tag.name for tag in post.tags if not tag.name.startswith("uni-"))
    return render_template(
        "create_post.html",
        post=post,
        tags_string=tags_string,
        university_value=post.university_label,
        edit_mode=True,
    )


@posts_bp.route("/post/<int:post_id>/delete", methods=["POST"])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)

    if post.author_id != current_user.id and not current_user.is_admin:
        flash(_("You do not have permission to delete this post."), "danger")
        return redirect(url_for("posts.view_post", post_id=post_id))

    remove_media_file(post.media_path, current_app.root_path)
    db.session.delete(post)
    db.session.commit()
    flash(_("Post deleted successfully."), "success")
    return redirect(url_for("main.index"))


@posts_bp.route("/post/<int:post_id>/comment", methods=["POST"])
@login_required
def add_comment(post_id):
    Post.query.get_or_404(post_id)
    content = request.form.get("content", "").strip()

    if not content:
        flash(_("Comment cannot be empty."), "danger")
        return redirect(url_for("posts.view_post", post_id=post_id))

    comment = Comment(post_id=post_id, author_id=current_user.id, content=content)
    db.session.add(comment)
    db.session.commit()

    flash(_("Comment added successfully."), "success")
    return redirect(url_for("posts.view_post", post_id=post_id))


@posts_bp.route("/post/<int:post_id>/vote", methods=["POST"])
@login_required
def vote_post(post_id):
    post = Post.query.get_or_404(post_id)

    try:
        vote_type = int(request.form.get("vote_type", "0"))
    except ValueError:
        return jsonify({"error": _("Invalid vote type.")}), 400

    if vote_type not in {1, -1}:
        return jsonify({"error": _("Invalid vote type.")}), 400

    existing_vote = Vote.query.filter_by(user_id=current_user.id, post_id=post_id).first()
    user_vote = vote_type
    message = _("Your vote has been recorded.")

    if existing_vote:
        if existing_vote.vote_type == vote_type:
            db.session.delete(existing_vote)
            user_vote = None
            message = _("Your vote has been removed.")
        else:
            existing_vote.vote_type = vote_type
            message = _("Your vote has been updated.")
    else:
        db.session.add(Vote(user_id=current_user.id, post_id=post_id, vote_type=vote_type))

    db.session.commit()
    refreshed_post = db.session.get(Post, post.id)
    return jsonify(
        {
            "success": True,
            "vote_count": refreshed_post.vote_count,
            "user_vote": user_vote,
            "message": message,
        }
    )


@posts_bp.route("/post/<int:post_id>/report", methods=["GET", "POST"])
@login_required
def report_post(post_id):
    post = Post.query.get_or_404(post_id)

    if request.method == "POST":
        reason = request.form.get("reason", "").strip()

        if not reason:
            flash(_("Please provide a reason for reporting."), "danger")
            return redirect(url_for("posts.view_post", post_id=post_id))

        existing_report = Report.query.filter_by(reporter_id=current_user.id, post_id=post_id, status="pending").first()
        if existing_report:
            flash(_("You have already reported this post."), "warning")
            return redirect(url_for("posts.view_post", post_id=post_id))

        report = Report(reporter_id=current_user.id, post_id=post_id, reason=reason)
        db.session.add(report)
        db.session.commit()

        flash(_("Thank you. An admin will review this report."), "success")
        return redirect(url_for("posts.view_post", post_id=post_id))

    return render_template("report_post.html", post=post)
