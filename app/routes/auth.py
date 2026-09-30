"""
Авторизация FlowForge = Telegram OIDC. Единственный способ входа.

Почему не старый Telegram Login Widget (data-onauth + HMAC от bot-токена):
он официально помечен Telegram как legacy. Актуальный путь — полноценный
OpenID Connect: Authorization Code Flow + PKCE, id_token подписан
(RS256/ES256/EdDSA) и проверяется через JWKS endpoint Telegram
(iss/aud/exp сверяются как положено), state защищает от CSRF,
code_verifier/code_challenge (PKCE) — от перехвата кода авторизации.

Настройка один раз в @BotFather:
  Bot Settings → Web Login → "Switch to OpenID Connect Login"
  (переключение НЕОБРАТИМО — старый Login Widget для этого бота
  перестанет работать) → зарегистрировать redirect_uri → получить
  Client ID и Client Secret (это НЕ токен бота, отдельный секрет).
"""
import base64
import hashlib
import secrets
from urllib.parse import urlencode

import requests
from flask import Blueprint, abort, current_app, redirect, render_template, session, url_for
from flask_login import login_user, logout_user, login_required, current_user
from jose import jwt as jose_jwt
from jose.exceptions import JOSEError

from app import db
from app.models.user import User
from app.services.i18n import t

auth_bp = Blueprint("auth", __name__)

_TELEGRAM_AUTH_URL = "https://oauth.telegram.org/auth"
_TELEGRAM_TOKEN_URL = "https://oauth.telegram.org/token"
_TELEGRAM_JWKS_URL = "https://oauth.telegram.org/.well-known/jwks.json"
_TELEGRAM_ISSUER = "https://oauth.telegram.org"


def _make_pkce_pair() -> tuple[str, str]:
    """code_verifier — секрет, который никогда не покидает наш сервер до
    обмена кода на токен; code_challenge — его SHA256, уходит в URL."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


@auth_bp.route("/login")
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("login.html", bot_username=current_app.config["TELEGRAM_BOT_USERNAME"])


@auth_bp.route("/telegram/start")
def telegram_start():
    verifier, challenge = _make_pkce_pair()
    state = secrets.token_urlsafe(32)

    # Храним верификатор и state в server-side сессии (подписанной cookie),
    # а не передаём их клиенту явно — так браузер пользователя никогда не
    # видит code_verifier целиком.
    session["tg_pkce_verifier"] = verifier
    session["tg_oauth_state"] = state

    params = {
        "client_id": current_app.config["TELEGRAM_CLIENT_ID"],
        "redirect_uri": current_app.config["TELEGRAM_REDIRECT_URI"],
        "response_type": "code",
        "scope": "openid profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return redirect(f"{_TELEGRAM_AUTH_URL}?{urlencode(params)}")


@auth_bp.route("/telegram/callback")
def telegram_callback():
    error = _query_arg("error")
    if error:
        return render_template("login.html", error=t("auth.telegram_returned_error", error=error))

    returned_state = _query_arg("state")
    expected_state = session.pop("tg_oauth_state", None)
    if not expected_state or returned_state != expected_state:
        abort(400, t("auth.state_mismatch"))

    code = _query_arg("code")
    verifier = session.pop("tg_pkce_verifier", None)
    if not code or not verifier:
        abort(400, t("auth.missing_code"))

    token_response = requests.post(
        _TELEGRAM_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": current_app.config["TELEGRAM_REDIRECT_URI"],
            "client_id": current_app.config["TELEGRAM_CLIENT_ID"],
            "code_verifier": verifier,
        },
        auth=(
            current_app.config["TELEGRAM_CLIENT_ID"],
            current_app.config["TELEGRAM_CLIENT_SECRET"],
        ),
        timeout=10,
    )
    if not token_response.ok:
        current_app.logger.warning("Telegram token exchange failed: %s", token_response.text)
        return render_template("login.html", error=t("auth.token_exchange_failed"))

    id_token = token_response.json().get("id_token")
    if not id_token:
        return render_template("login.html", error=t("auth.missing_id_token"))

    try:
        claims = _verify_id_token(id_token)
    except JOSEError as exc:
        current_app.logger.warning("id_token verification failed: %s", exc)
        return render_template("login.html", error=t("auth.token_verification_failed"))

    user = _get_or_create_user(claims)
    login_user(user, remember=True)
    return redirect(url_for("main.dashboard"))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.index"))


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def _query_arg(name: str) -> str | None:
    from flask import request
    return request.args.get(name)


def _verify_id_token(id_token: str) -> dict:
    """
    Полная OIDC-проверка: подпись через JWKS Telegram, issuer, audience,
    expiry. Без этого шага доверять содержимому токена нельзя — он мог
    быть подделан кем угодно, кто знает формат payload'а.
    """
    jwks = requests.get(_TELEGRAM_JWKS_URL, timeout=10).json()
    return jose_jwt.decode(
        id_token,
        jwks,
        algorithms=["RS256", "ES256", "EdDSA"],
        audience=current_app.config["TELEGRAM_CLIENT_ID"],
        issuer=_TELEGRAM_ISSUER,
    )


def _get_or_create_user(claims: dict) -> User:
    telegram_id = str(claims["sub"])
    user = User.query.filter_by(telegram_id=telegram_id).first()

    display_name = " ".join(
        filter(None, [claims.get("given_name"), claims.get("family_name")])
    ) or claims.get("preferred_username", t("user.default_display_name"))

    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=claims.get("preferred_username"),
            display_name=display_name,
            avatar_url=claims.get("picture"),
        )
        db.session.add(user)
    else:
        # Обновляем профиль на каждый вход — ник/аватар в Telegram могли измениться.
        user.username = claims.get("preferred_username", user.username)
        user.display_name = display_name or user.display_name
        user.avatar_url = claims.get("picture", user.avatar_url)

    import datetime as dt
    user.last_login_at = dt.datetime.utcnow()
    db.session.commit()
    return user
