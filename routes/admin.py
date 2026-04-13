from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from flask_babel import gettext as _
from models import Comment, Post, Report, Tag, User, db

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("")
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        abort(403)

    pending_reports = Report.query.filter_by(status="pending").order_by(Report.created_at.desc()).all()
    resolved_reports = Report.query.filter(Report.status != "pending").order_by(Report.created_at.desc()).limit(10).all()
    all_posts = Post.query.order_by(Post.created_at.desc()).all()
    all_users = User.query.order_by(User.created_at.desc()).all()
    stats = {
        "users": User.query.count(),
        "posts": Post.query.count(),
        "comments": Comment.query.count(),
        "reports": Report.query.count(),
        "tags": Tag.query.count(),
    }

    return render_template(
        "admin_dashboard.html",
        pending_reports=pending_reports,
        resolved_reports=resolved_reports,
        all_posts=all_posts,
        all_users=all_users,
        stats=stats,
    )


@admin_bp.route("/report/<int:report_id>/resolve", methods=["POST"])
@login_required
def resolve_report(report_id):
    if not current_user.is_admin:
        abort(403)

    report = Report.query.get_or_404(report_id)
    action = request.form.get("action")

    if action == "delete_post":
        post = db.session.get(Post, report.post_id)
        if post:
            db.session.delete(post)
        report.status = "resolved"
    elif action == "dismiss":
        report.status = "dismissed"
    else:
        report.status = "resolved"

    report.reviewed_at = datetime.utcnow()
    db.session.commit()

    flash(_("Report has been processed."), "success")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/user/<int:user_id>/toggle_admin", methods=["POST"])
@login_required
def toggle_admin(user_id):
    if not current_user.is_admin:
        abort(403)

    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash(_("You cannot remove your own admin privileges."), "danger")
        return redirect(url_for("admin.admin_dashboard"))

    user.is_admin = not user.is_admin
    db.session.commit()

    status = _("granted") if user.is_admin else _("revoked")
    flash(_("Admin privileges %(status)s for %(username)s.", status=status, username=user.username), "success")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/user/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        abort(403)

    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash(_("You cannot delete your own account."), "danger")
        return redirect(url_for("admin.admin_dashboard"))

    db.session.delete(user)
    db.session.commit()

    flash(_("User %(username)s has been deleted.", username=user.username), "success")
    return redirect(url_for("admin.admin_dashboard"))
