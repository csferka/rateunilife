import json
from functools import lru_cache
from pathlib import Path

from flask import current_app


class Babel:
    """A small Flask-Babel compatible shim for this project.

    It provides the pieces the app needs in environments where Flask-Babel
    is not installed, while keeping the same public API used by the app.
    """

    def __init__(self, app=None, locale_selector=None):
        self.locale_selector = locale_selector
        if app is not None:
            self.init_app(app, locale_selector=locale_selector)

    def init_app(self, app, locale_selector=None):
        if locale_selector is not None:
            self.locale_selector = locale_selector
        app.extensions["babel"] = self

        @app.context_processor
        def inject_babel_helpers():
            return {"_": gettext, "get_locale": get_locale}


def _babel_instance():
    return current_app.extensions.get("babel")


def get_locale():
    babel = _babel_instance()
    if babel and babel.locale_selector:
        selected = babel.locale_selector()
        if selected:
            return selected
    return current_app.config.get("BABEL_DEFAULT_LOCALE", "en")


@lru_cache(maxsize=8)
def _load_catalog(root_path, locale):
    translation_path = Path(root_path) / "translations" / locale / "messages.json"
    if not translation_path.exists():
        return {}
    return json.loads(translation_path.read_text(encoding="utf-8"))


def gettext(message, **variables):
    locale = get_locale()
    translated = _load_catalog(current_app.root_path, locale).get(message, message)
    if variables:
        if "%(" in translated:
            return translated % variables
        return translated.format(**variables)
    return translated


def ngettext(singular, plural, num, **variables):
    message = singular if num == 1 else plural
    return gettext(message, num=num, **variables)


_ = gettext
