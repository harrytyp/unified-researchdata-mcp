#!/bin/bash
# Patch: nomad.app.v1.routers.uploads — admins see ALL uploads in GET /uploads.
# Runs at container start (called from startup.sh) so it survives recreates.
# Idempotent: only patches if the marker line is not yet present.
UPLOADS_PY=/opt/venv/lib/python3.12/site-packages/nomad/app/v1/routers/uploads.py
MARKER="ADMIN_SEES_ALL_PATCHED"

if ! grep -q "$MARKER" "$UPLOADS_PY"; then
    python3 - "$UPLOADS_PY" << 'PYEOF'
import sys

path = sys.argv[1]
src = open(path, encoding='utf-8').read()

old = '''def get_role_query(roles: list[UploadRole], user: User, include_all=False) -> Q:
    """
    Create MongoDB filter query for user with given roles (default: all roles)
    """
    if not roles:
        roles = list(UploadRole)

    group_ids = MongoUserGroup.get_ids_by_user_id(user.user_id, include_all=include_all)

    role_query = Q()
    if UploadRole.main_author in roles:
        role_query |= Q(main_author=user.user_id)
    if UploadRole.coauthor in roles:
        role_query |= Q(coauthors=user.user_id) | Q(coauthor_groups__in=group_ids)
    if UploadRole.reviewer in roles:
        role_query |= Q(reviewers=user.user_id) | Q(reviewer_groups__in=group_ids)

    return role_query
'''

new = '''# ADMIN_SEES_ALL_PATCHED
def get_role_query(roles: list[UploadRole], user: User, include_all=False) -> Q:
    """
    Create MongoDB filter query for user with given roles (default: all roles).

    ADMIN SEES ALL: admins (is_admin) get an empty query matching every upload,
    independent of roles/groups. Non-admins keep the original role-based logic.
    """
    if user is not None and getattr(user, 'is_admin', False):
        return Q()

    if not roles:
        roles = list(UploadRole)

    group_ids = MongoUserGroup.get_ids_by_user_id(user.user_id, include_all=include_all)

    role_query = Q()
    if UploadRole.main_author in roles:
        role_query |= Q(main_author=user.user_id)
    if UploadRole.coauthor in roles:
        role_query |= Q(coauthors=user.user_id) | Q(coauthor_groups__in=group_ids)
    if UploadRole.reviewer in roles:
        role_query |= Q(reviewers=user.user_id) | Q(reviewer_groups__in=group_ids)

    return role_query
'''

assert old in src, 'Original get_role_query not found - check NOMAD version!'
src = src.replace(old, new, 1)
open(path, 'w', encoding='utf-8').write(src)
print('uploads.py: get_role_query patched (admin sees all)')
PYEOF
else
    echo 'uploads.py: admin patch already applied'
fi
