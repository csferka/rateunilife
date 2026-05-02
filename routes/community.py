from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from flask_babel import gettext as _
from models import MediaPost, Post, Tag, User, Vote, db
from utils import (
    clear_failed_attempts,
    get_media_kind,
    is_rate_limited,
    normalize_university_slug,
    record_failed_attempt,
    remove_media_file,
    save_uploaded_media,
    university_label_from_slug,
)

community_bp = Blueprint("community", __name__)

UNIVERSITY_PROFILES = {
    "webster-university-tashkent": {
        "priority": {"international": 3, "reputation": 2},
        "learning": {"lectures": 2, "projects": 2},
        "budget": {"5000-10000": 3},
        "language": {"english": 3},
        "field": {"business": 3, "technology": 2, "arts": 2},
    },
    "wiut": {
        "priority": {"reputation": 3, "international": 2},
        "learning": {"lectures": 3, "seminars": 2},
        "budget": {"5000-10000": 2, "2000-5000": 1},
        "language": {"english": 3},
        "field": {"business": 3, "law": 2},
    },
    "inha-tashkent": {
        "priority": {"reputation": 3, "academic": 3},
        "learning": {"projects": 3, "lectures": 2},
        "budget": {"2000-5000": 2},
        "language": {"english": 2},
        "field": {"technology": 3, "engineering": 3},
    },
    "ttpu": {
        "priority": {"affordability": 3, "academic": 2},
        "learning": {"projects": 3, "lectures": 2},
        "budget": {"under-2000": 3, "2000-5000": 2},
        "language": {"uzbek": 2, "english": 1},
        "field": {"technology": 3, "engineering": 3},
    },
    "wsau": {
        "priority": {"international": 3, "reputation": 2},
        "learning": {"seminars": 3, "lectures": 2},
        "budget": {"5000-10000": 2},
        "language": {"english": 3},
        "field": {"business": 2, "law": 3, "social": 2},
    },
}

QUIZ_QUESTIONS = [
    {
        "key": "priority",
        "label": "What matters most to you?",
        "options": [
            ("reputation", "Academic reputation"),
            ("campus", "Campus life"),
            ("affordability", "Affordability"),
            ("international", "International exposure"),
            ("class-size", "Class size"),
        ],
    },
    {
        "key": "learning",
        "label": "How do you prefer to learn?",
        "options": [
            ("lectures", "Lectures"),
            ("projects", "Hands-on projects"),
            ("online", "Online flexibility"),
            ("seminars", "Small seminars"),
        ],
    },
    {
        "key": "budget",
        "label": "What's your budget range?",
        "options": [
            ("under-2000", "Under $2,000/year"),
            ("2000-5000", "$2,000-$5,000/year"),
            ("5000-10000", "$5,000-$10,000/year"),
            ("no-limit", "No limit"),
        ],
    },
    {
        "key": "language",
        "label": "What language do you prefer classes in?",
        "options": [
            ("english", "English only"),
            ("uzbek", "Uzbek only"),
            ("both", "Both English and Uzbek"),
        ],
    },
    {
        "key": "field",
        "label": "What field are you interested in?",
        "options": [
            ("technology", "Technology & Engineering"),
            ("business", "Business & Economics"),
            ("law", "Law & Social Sciences"),
            ("arts", "Arts & Humanities"),
            ("medicine", "Medicine & Health"),
        ],
    },
]


def vote_score_subquery():
    return (
        Vote.query.with_entities(
            Vote.post_id.label("post_id"),
            func.coalesce(func.sum(Vote.vote_type), 0).label("score"),
        )
        .group_by(Vote.post_id)
        .subquery()
    )


def community_base_query(slug):
    return Post.query.options(joinedload(Post.author)).filter(Post.tags.any(Tag.name == f"uni-{slug}"))


def build_match_results(answers):
    raw_scores = []
    for slug, profile in UNIVERSITY_PROFILES.items():
        score = 0
        max_score = 0
        for key, answer in answers.items():
            section = profile.get(key, {})
            score += section.get(answer, 0)
            max_score += max(section.values(), default=0)
        percentage = int(round((score / max_score) * 100)) if max_score else 0
        raw_scores.append(
            {
                "slug": slug,
                "name": university_label_from_slug(slug),
                "score": score,
                "percentage": percentage,
            }
        )
    return sorted(raw_scores, key=lambda item: (item["score"], item["percentage"]), reverse=True)[:3]


@community_bp.route("/university/<slug>")
def university_feed(slug):
    slug = normalize_university_slug(slug)
    if not slug:
        return redirect(url_for("main.index"))

    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip().lower()
    sort = request.args.get("sort", "recent").strip().lower()
    page = request.args.get("page", 1, type=int)

    score_subquery = vote_score_subquery()
    query = community_base_query(slug).outerjoin(score_subquery, Post.id == score_subquery.c.post_id)

    if category in {"professor", "course", "campus", "general"}:
        query = query.filter(Post.category == category)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            func.lower(Post.title).like(func.lower(search_term))
            | func.lower(Post.content).like(func.lower(search_term))
            | Post.tags.any(Tag.name.ilike(search_term))
        )

    if sort == "top":
        query = query.order_by(func.coalesce(score_subquery.c.score, 0).desc(), Post.created_at.desc())
    else:
        query = query.order_by(Post.created_at.desc())

    pagination = query.paginate(page=page, per_page=current_app.config["POSTS_PER_PAGE"], error_out=False)

    community_tag = f"uni-{slug}"
    community_post_ids = community_base_query(slug).with_entities(Post.id).subquery()
    top_tags = (
        db.session.query(Tag.name, func.count(Tag.id).label("usage_count"))
        .join(Tag.posts)
        .filter(Post.id.in_(db.select(community_post_ids.c.id)), Tag.name != community_tag)
        .group_by(Tag.name)
        .order_by(func.count(Tag.id).desc(), Tag.name.asc())
        .limit(6)
        .all()
    )
    post_count = community_base_query(slug).count()
    community_tag_name = f"uni-{slug}"
    member_count = User.query.join(User.communities).filter(Tag.name == community_tag_name).count()
    is_member = bool(
        current_user.is_authenticated
        and (
            current_user.has_joined_community(slug)
            or getattr(current_user, "university_slug", None) == slug
        )
    )

    leaderboard = (
        community_base_query(slug)
        .outerjoin(score_subquery, Post.id == score_subquery.c.post_id)
        .order_by(func.coalesce(score_subquery.c.score, 0).desc(), Post.created_at.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "university_feed.html",
        university_slug=slug,
        university_name=university_label_from_slug(slug),
        posts=pagination.items,
        pagination=pagination,
        post_count=post_count,
        member_count=member_count,
        top_tags=top_tags,
        leaderboard=leaderboard,
        current_category=category or None,
        current_sort=sort,
        search=search or None,
        is_member=is_member,
    )


@community_bp.route("/university/<slug>/join", methods=["POST"])
@login_required
def join_community(slug):
    slug = normalize_university_slug(slug)
    if not slug:
        return redirect(url_for("main.index"))

    if current_user.has_joined_community(slug):
        flash(_("You already joined the %(university)s community.", university=university_label_from_slug(slug)), "info")
        return redirect(url_for("community.university_feed", slug=slug))

    community_tag_name = f"uni-{slug}"
    community_tag = Tag.query.filter_by(name=community_tag_name).first()
    if community_tag is None:
        community_tag = Tag(name=community_tag_name)
        db.session.add(community_tag)
        db.session.flush()

    current_user.communities.append(community_tag)
    if not current_user.university_slug:
        # Preserve the first joined community as the user's home community.
        current_user.university_slug = slug

    db.session.commit()
    flash(_("You joined the %(university)s community.", university=university_label_from_slug(slug)), "success")
    return redirect(url_for("community.university_feed", slug=slug))


@community_bp.route("/university/<slug>/gallery")
def gallery(slug):
    slug = normalize_university_slug(slug)
    if not slug:
        return redirect(url_for("main.index"))

    media_posts = (
        MediaPost.query.filter_by(university_slug=slug)
        .options(joinedload(MediaPost.author))
        .order_by(MediaPost.created_at.desc())
        .all()
    )
    return render_template(
        "gallery.html",
        university_slug=slug,
        university_name=university_label_from_slug(slug),
        media_posts=media_posts,
        max_upload_mb=max(1, int((current_app.config.get("MAX_CONTENT_LENGTH") or (30 * 1024 * 1024)) / (1024 * 1024))),
    )


@community_bp.route("/university/<slug>/gallery/upload", methods=["POST"])
@login_required
def upload_gallery_media(slug):
    slug = normalize_university_slug(slug)
    if not slug:
        return redirect(url_for("main.index"))

    rate_key = f"media_upload_{current_user.id}"
    if is_rate_limited(rate_key, limit=1, window_seconds=600):
        flash(_("You can upload only one media item every 10 minutes."), "danger")
        return redirect(url_for("community.gallery", slug=slug))

    media_file = request.files.get("media")
    caption = request.form.get("caption", "").strip()
    anonymous_choice = request.form.get("is_anonymous", "on")

    if not media_file or not media_file.filename:
        flash(_("Please choose a photo or video to upload."), "danger")
        return redirect(url_for("community.gallery", slug=slug))

    kind_info = get_media_kind(media_file.filename)
    if not kind_info:
        flash(_("Unsupported media format. Use images (png/jpg/jpeg/gif/webp) or videos (mp4/webm/mov/m4v)."), "danger")
        return redirect(url_for("community.gallery", slug=slug))

    media_path, media_type = save_uploaded_media(media_file, current_app.config["UPLOAD_FOLDER"])
    media_post = MediaPost(
        author_id=current_user.id,
        university_slug=slug,
        caption=caption[:300] if caption else None,
        media_path=media_path,
        media_type=media_type,
        is_anonymous=anonymous_choice == "on",
    )
    db.session.add(media_post)
    db.session.commit()
    record_failed_attempt(rate_key)

    flash(_("Your media has been added to the community gallery."), "success")
    return redirect(url_for("community.gallery", slug=slug))


@community_bp.route("/media/<int:media_id>/delete", methods=["POST"])
@login_required
def delete_media(media_id):
    media_post = MediaPost.query.get_or_404(media_id)
    if media_post.author_id != current_user.id and not current_user.is_admin:
        flash(_("You do not have permission to delete this media."), "danger")
        return redirect(url_for("community.gallery", slug=media_post.university_slug))

    remove_media_file(media_post.media_path, current_app.root_path)
    if media_post.author_id == current_user.id:
        clear_failed_attempts(f"media_upload_{current_user.id}")
    slug = media_post.university_slug
    db.session.delete(media_post)
    db.session.commit()
    flash(_("Media deleted successfully."), "success")
    return redirect(url_for("community.gallery", slug=slug))


@community_bp.route("/match", methods=["GET", "POST"])
def match():
    results = None
    answers = {}
    if request.method == "POST":
        answers = {question["key"]: request.form.get(question["key"], "") for question in QUIZ_QUESTIONS}
        if all(answers.values()):
            results = build_match_results(answers)
        else:
            flash(_("Please answer all quiz questions before submitting."), "danger")

    return render_template("match.html", questions=QUIZ_QUESTIONS, results=results, answers=answers)
