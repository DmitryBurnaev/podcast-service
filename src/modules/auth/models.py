import secrets
from datetime import datetime

from common.models import BaseModel
from core.database import db
from modules.auth.hasher import PBKDF2PasswordHasher


class User(BaseModel):
    __tablename__ = "auth_users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(length=128), index=True, nullable=False, unique=True)
    password = db.Column(db.String(length=256), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    is_superuser = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<User #{self.id} {self.email}>"

    @classmethod
    def make_password(cls, raw_password: str):
        hasher = PBKDF2PasswordHasher()
        return hasher.encode(raw_password)

    def verify_password(self, raw_password: str):
        hasher = PBKDF2PasswordHasher()
        verified, _ = hasher.verify(raw_password, encoded=str(self.password))
        return verified

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def display_name(self) -> str:
        return self.email

    @classmethod
    async def get_active(cls, user_id: int) -> "User":
        return await cls.async_get(id=user_id, is_active=True)


class UserInvite(BaseModel):
    __tablename__ = "auth_invites"
    TOKEN_MAX_LENGTH = 32

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("auth_users.id"), unique=True)
    email = db.Column(db.String(length=32), unique=True)
    token = db.Column(db.String(length=32), unique=True, nullable=False, index=True)
    is_applied = db.Column(db.Boolean, default=False, nullable=False)
    expired_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("auth_users.id"), nullable=False)

    def __repr__(self):
        return f"<UserInvite #{self.id} {self.token}>"

    @classmethod
    def generate_token(cls):
        return secrets.token_urlsafe()[: cls.TOKEN_MAX_LENGTH]


class UserSession(BaseModel):
    __tablename__ = "auth_sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("auth_users.id"), unique=True)
    refresh_token = db.Column(db.String(length=256))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    expired_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<UserSession #{self.id} {self.user_id}>"
