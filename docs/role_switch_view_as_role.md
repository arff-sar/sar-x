# Role Switch (View-As-Role) Security Notes

## Purpose
Role switch provides a **temporary, session-scoped effective role** for UI/authorization preview and safe operational testing.

## What It Does
- Lets only allow-listed user(s) select an acting role for current session.
- Applies selected role through `get_effective_role()` and `has_permission(...)` checks.
- Updates menu visibility, route guards, and action permissions according to effective role.

## What It Does NOT Do
- Does not update `kullanici.rol` in DB.
- Does not reseed roles/permissions.
- Does not persist role override after logout.

## Access Restriction
- Feature is only enabled for `mehmetcinocevi@gmail.com` (configurable allow-list key: `ROLE_SWITCH_ALLOWED_USERS`).
- Non-allow-listed users do not see the menu and receive `403` on `/role-switch`.

## Core Concepts
- **Base role**: persistent DB role (`kullanici.rol`).
- **Acting role**: selected temporary role in session (`temporary_role_override`).
- **Effective role**: resolved role used for authorization (`acting` if valid, otherwise `base`).

## Session Override Rules
- Override key is validated against dynamic active roles.
- Invalid/inactive/deleted override values are auto-cleared at request start.
- `__default__` clears override and returns to base role.

## Why Control-Plane Is Blocked in Impersonation
When `acting role != base role`, control-plane endpoints are blocked (403) to avoid risky admin mutations during simulation.
Examples:
- role/permission matrix changes
- user role assignment flows
- approval and site/settings mutation endpoints

## Developer Rules for New Endpoints
- Use `@permission_required(...)` and `has_permission(...)` for access decisions.
- Avoid direct role string checks (`current_user.rol == ...`) for authorization.
- If endpoint mutates control-plane/admin policy state, ensure it is covered by impersonation block policy (`should_block_control_plane`).

## Developer Rules for Templates
- Prefer `has_permission(...)` for buttons/menus/action visibility.
- Role-derived properties (`is_sahip`, `is_airport_manager`) are acceptable only when they represent scope/layout semantics, not fine-grained action authorization.
- Do not add new raw `rol == '...'` checks.

## Logging / Audit Fields
Role switch audit events include:
- `real_user_id`
- `real_user_email`
- `base_role`
- `acting_role`
- `effective_role`
- `request_id`

Event names:
- `auth.role_switch.started`
- `auth.role_switch.changed`
- `auth.role_switch.ended`
