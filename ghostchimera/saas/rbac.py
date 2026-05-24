"""Role-based access checks for SaaS mode."""

from __future__ import annotations

from .models import Role

PERMISSIONS: dict[str, set[Role]] = {
    "org:read": {Role.VIEWER, Role.OPERATOR, Role.ADMIN, Role.OWNER},
    "workspace:read": {Role.VIEWER, Role.OPERATOR, Role.ADMIN, Role.OWNER},
    "run:create": {Role.OPERATOR, Role.ADMIN, Role.OWNER},
    "run:approve": {Role.ADMIN, Role.OWNER},
    "secret:manage": {Role.ADMIN, Role.OWNER},
    "member:manage": {Role.OWNER},
    "audit:read": {Role.ADMIN, Role.OWNER},
    "worker:manage": {Role.ADMIN, Role.OWNER},
}


def has_permission(role: Role | str, permission: str) -> bool:
    role_value = role if isinstance(role, Role) else Role(str(role))
    return role_value in PERMISSIONS.get(permission, set())


def require_permission(role: Role | str, permission: str) -> None:
    if not has_permission(role, permission):
        raise PermissionError(f"role {role!s} is not allowed to perform {permission}")
