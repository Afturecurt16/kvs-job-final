from config import MAX_ADMIN_IDS


async def is_max_admin(user_id: int) -> bool:
    """Return whether a MAX user may access the miniapp administration API."""
    return user_id in MAX_ADMIN_IDS
