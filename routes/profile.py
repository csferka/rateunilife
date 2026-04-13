from flask import Blueprint, render_template
from flask_login import current_user, login_required

from models import Comment, Post

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/profile")
@login_required
def profile():
    user_posts = Post.query.filter_by(author_id=current_user.id).order_by(Post.created_at.desc()).all()
    user_comments = Comment.query.filter_by(author_id=current_user.id).order_by(Comment.created_at.desc()).all()
    return render_template("profile.html", user_posts=user_posts, user_comments=user_comments)
