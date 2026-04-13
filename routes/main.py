from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload, selectinload

from models import Post, Tag, Vote, UNIVERSITY_TAG_PREFIX
from utils import available_languages, is_safe_next_url, normalize_university_slug

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    category = request.args.get("category", "").strip().lower()
    tag_name = request.args.get("tag", "").strip().lower()
    university_slug = request.args.get("university", "").strip().lower()
    search = request.args.get("search", "").strip()
    sort = request.args.get("sort", "recent").strip().lower()
    page = request.args.get("page", 1, type=int)
    per_page = current_app.config["POSTS_PER_PAGE"]

    vote_scores = (
        Vote.query.with_entities(
            Vote.post_id.label("post_id"),
            func.coalesce(func.sum(Vote.vote_type), 0).label("score"),
        )
        .group_by(Vote.post_id)
        .subquery()
    )

    query = Post.query.options(joinedload(Post.author), selectinload(Post.tags)).outerjoin(
        vote_scores, Post.id == vote_scores.c.post_id
    )

    valid_categories = {"professor", "course", "campus", "general"}
    if category in valid_categories:
        query = query.filter(Post.category == category)

    if tag_name:
        query = query.filter(Post.tags.any(Tag.name == tag_name))

    normalized_university_slug = normalize_university_slug(university_slug) if university_slug else None
    if normalized_university_slug:
        university_tag_name = f"{UNIVERSITY_TAG_PREFIX}{normalized_university_slug}"
        query = query.filter(Post.tags.any(Tag.name == university_tag_name))

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(Post.title.ilike(search_term), Post.content.ilike(search_term), Post.tags.any(Tag.name.ilike(search_term)))
        )

    if sort == "top":
        query = query.order_by(func.coalesce(vote_scores.c.score, 0).desc(), Post.created_at.desc())
    else:
        query = query.order_by(Post.created_at.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    all_tags = Tag.query.filter(~Tag.name.startswith(UNIVERSITY_TAG_PREFIX)).order_by(Tag.name.asc()).all()
    university_tags = Tag.query.filter(Tag.name.startswith(UNIVERSITY_TAG_PREFIX)).order_by(Tag.name.asc()).all()
    university_filters = [
        {
            "slug": uni_tag.name[len(UNIVERSITY_TAG_PREFIX):],
            "label": uni_tag.name[len(UNIVERSITY_TAG_PREFIX):].replace("-", " ").title(),
        }
        for uni_tag in university_tags
    ]

    return render_template(
        "index.html",
        posts=pagination.items,
        pagination=pagination,
        tags=all_tags,
        university_filters=university_filters,
        current_category=category or None,
        current_tag=tag_name or None,
        current_university=normalized_university_slug,
        search=search or None,
        current_sort=sort,
        page=pagination.page,
        total_pages=pagination.pages,
        current_user=current_user,
    )


@main_bp.route("/api/tags/search")
def search_tags():
    query = request.args.get("q", "").strip().lower()
    if not query:
        return jsonify([])

    tags = (
        Tag.query.filter(Tag.name.contains(query), ~Tag.name.startswith(UNIVERSITY_TAG_PREFIX))
        .order_by(Tag.name.asc())
        .limit(10)
        .all()
    )
    return jsonify([{"name": tag.name} for tag in tags])


@main_bp.route("/set-language/<lang_code>")
def set_language(lang_code):
    languages = available_languages()
    if lang_code in languages:
        session["lang"] = lang_code
        session.permanent = True
        session.modified = True

    next_page = request.args.get("next")
    if is_safe_next_url(next_page):
        return redirect(next_page)
    return redirect(request.referrer or url_for("main.index"))
