from .admin import admin_bp
from .auth import auth_bp
from .community import community_bp
from .main import main_bp
from .posts import posts_bp
from .profile import profile_bp

__all__ = ["admin_bp", "auth_bp", "community_bp", "main_bp", "posts_bp", "profile_bp"]
