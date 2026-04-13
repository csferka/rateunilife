from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user

from flask_babel import gettext as _
from models import User, db
from utils import clear_failed_attempts, is_rate_limited, is_safe_next_url, record_failed_attempt

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not email or not password:
            flash(_("All fields are required."), "danger")
            return redirect(url_for("auth.register"))

        if len(password) < 8:
            flash(_("Password must be at least 8 characters long."), "danger")
            return redirect(url_for("auth.register"))

        if password != confirm_password:
            flash(_("Passwords do not match."), "danger")
            return redirect(url_for("auth.register"))

        if User.query.filter_by(username=username).first():
            flash(_("Username already exists."), "danger")
            return redirect(url_for("auth.register"))

        if User.query.filter_by(email=email).first():
            flash(_("Email already registered."), "danger")
            return redirect(url_for("auth.register"))

        user = User(username=username, email=email, is_admin=(User.query.count() == 0))
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash(_("Registration successful. Please log in."), "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        client_key = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
        if is_rate_limited(client_key):
            flash(_("Too many failed login attempts. Please wait a few minutes and try again."), "danger")
            return redirect(url_for("auth.login"))

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            session.permanent = True
            clear_failed_attempts(client_key)
            next_page = request.args.get("next")
            flash(_("Welcome back, %(username)s.", username=username), "success")
            if is_safe_next_url(next_page):
                return redirect(next_page)
            return redirect(url_for("main.index"))

        record_failed_attempt(client_key)
        flash(_("Invalid username or password."), "danger")

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    if current_user.is_authenticated:
        logout_user()
        flash(_("You have been logged out."), "info")
    return redirect(url_for("main.index"))
