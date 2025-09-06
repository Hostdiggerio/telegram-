# admin_panel.py

import logging
from telegram import Update
from telegram.ext import ContextTypes
from functools import wraps

# =================================================================
# IMPORTANT: Set your Telegram User ID here!
ADMIN_USER_ID = 6130335505  # <--- YOUR ID
# =================================================================

logger = logging.getLogger(__name__)

# This decorator is still very useful, so we keep it.
def admin_only(func):
    """A decorator to restrict command access to the ADMIN_USER_ID."""
    @wraps(func)
    async def restricted_func(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user.id != ADMIN_USER_ID:
            logger.warning(f"Unauthorized access denied for user {update.effective_user.id}.")
            # Optionally send a message, or just ignore.
            return
        return await func(update, context, *args, **kwargs)
    return restricted_func