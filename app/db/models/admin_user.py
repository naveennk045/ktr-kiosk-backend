from sqlalchemy import Boolean, Column, DateTime, Integer, String, func, text

from app.db.session import Base


class AdminUser(Base):
    """
    Dashboard (KTR One) login. There is no sign-up API: rows are added directly in the
    database, with ``password_hash`` produced by ``scripts/admin_user.py``.
    """

    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Stored lower-case; login is case-insensitive.
    username = Column(String(64), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(128), nullable=True)
    role = Column(String(32), nullable=False, server_default=text("'admin'"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<AdminUser(id={self.id}, username={self.username!r})>"
