"""Shared, environment-backed authentication for the two HTTP services."""

import hashlib
import hmac
import os
import time


COOKIE_NAME = "map_session"


class SessionAuth:
    """Keep the original signed cookie wire format; never ship credentials."""

    def __init__(self, config):
        settings = config.get("auth", {})
        self.username = self._required(settings.get("username_env", "CAPSTONE_ADMIN_USER"))
        self.password = self._required(settings.get("password_env", "CAPSTONE_ADMIN_PASSWORD"))
        self.secret = self._required(settings.get("secret_env", "CAPSTONE_SESSION_SECRET")).encode("utf-8")
        if ":" in self.username:
            raise ValueError("Authentication username must not contain ':'")
        if len(self.secret) < 32:
            raise ValueError("Session secret must contain at least 32 bytes")
        self.max_age = int(settings.get("session_max_age", 12 * 60 * 60))
        if self.max_age <= 0:
            raise ValueError("auth.session_max_age must be positive")
        self.cookie_secure = bool(settings.get("cookie_secure", False))

    @staticmethod
    def _required(name):
        if not isinstance(name, str) or not name:
            raise ValueError("Authentication environment variable names must be strings")
        value = os.environ.get(name)
        if not value:
            raise ValueError("Required authentication environment variable is unset: " + name)
        return value

    def _sign(self, raw):
        return hmac.new(self.secret, raw.encode("utf-8"), hashlib.sha256).hexdigest()

    def make_token(self, now=None):
        timestamp = int(time.time() if now is None else now)
        raw = "{}:{}".format(self.username, timestamp)
        return "{}:{}".format(raw, self._sign(raw))

    def check_token(self, token, now=None):
        if not isinstance(token, str) or len(token) > 1024:
            return False
        try:
            username, timestamp, signature = token.split(":")
            # Canonical integers avoid accepting strange alternate encodings.
            issued = int(timestamp)
            if str(issued) != timestamp:
                return False
            current = time.time() if now is None else now
            if issued > current or current - issued > self.max_age:
                return False
            if not hmac.compare_digest(username.encode("utf-8"), self.username.encode("utf-8")):
                return False
            expected = self._sign(username + ":" + timestamp)
            return hmac.compare_digest(signature, expected)
        except (ValueError, TypeError, OverflowError):
            return False

    def check_password(self, username, password):
        if not isinstance(username, str) or not isinstance(password, str):
            return False
        user_ok = hmac.compare_digest(username.encode("utf-8"), self.username.encode("utf-8"))
        password_ok = hmac.compare_digest(password.encode("utf-8"), self.password.encode("utf-8"))
        return user_ok and password_ok

    def logged_in(self, request):
        return self.check_token(request.cookies.get(COOKIE_NAME, ""))
