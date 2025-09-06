# settings_handler.py

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.helpers import escape_markdown

from database_manager import get_or_create_user, set_user_system_prompt, set_user_temperature, set_user_top_p, set_user_max_tokens

logger = logging.getLogger(__name__)

# --- State Definitions for ConversationHandler ---
SELECTING_SETTING, GETTING_SYSTEM_PROMPT, GETTING_TEMPERATURE, GETTING_TOP_P, GETTING_MAX_TOKENS = range(5)

# --- Helper to display the main tuning menu ---
async def show_tuning_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main parameter tuning menu with current values."""
    query = update.callback_query
    if query: await query.answer()

    user = get_or_create_user(update.effective_user)
    
    # Safely get current settings, providing defaults if they are None
    system_prompt_display = user['system_prompt'] or "Not Set"
    temp_display = user['temperature'] if user['temperature'] is not None else 0.7
    top_p_display = user['top_p'] if user['top_p'] is not None else 1.0
    max_tokens_display = user['max_tokens'] if user['max_tokens'] is not None else 4096

    # Escape the system prompt for markdown
    safe_prompt = escape_markdown(system_prompt_display, version=2)

    # --- FIX: Escape the '.' in float values for MarkdownV2 ---
    temp_display_str = f"{temp_display:.1f}".replace('.', '\\.')
    top_p_display_str = f"{top_p_display:.1f}".replace('.', '\\.')

    text = (
        f"🔧 *Parameter Tuning*\n\n"
        f"Here you can adjust the AI's behavior\\. Changes will apply to all future messages\\.\n\n"
        f"รร*Current Settings*ษษ\n"
        f"`System Prompt:` {safe_prompt}\n"
        f"`Temperature  :` {temp_display_str}\n"
        f"`Top P        :` {top_p_display_str}\n"
        f"`Max Tokens   :` {max_tokens_display}"
    )
    
    keyboard = [
        [InlineKeyboardButton("📝 Edit System Prompt", callback_data='settings:set_prompt')],
        [
            InlineKeyboardButton("🌡️ Set Temperature", callback_data='settings:set_temp'),
            InlineKeyboardButton("🎲 Set Top P", callback_data='settings:set_top_p')
        ],
        [InlineKeyboardButton("📦 Set Max Tokens", callback_data='settings:set_max_tokens')],
        [InlineKeyboardButton("⬅️ Back to AI Settings", callback_data='settings:back_to_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    else:
        # This case handles reentry after a value has been set
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')

# --- Conversation Flow ---

async def ask_for_system_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Asks the user to enter a new system prompt."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Please send the new system prompt\\. This is the core instruction the AI will follow\\. "
        "Send /cancel to go back, or send 'none' to clear the current prompt\\."
    )
    return GETTING_SYSTEM_PROMPT

async def save_system_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the user's new system prompt."""
    user_id = update.effective_user.id
    prompt_text = update.message.text
    
    if prompt_text.lower() == 'none':
        set_user_system_prompt(user_id, "")
        await update.message.reply_text("✅ System prompt cleared\\.")
    else:
        set_user_system_prompt(user_id, prompt_text)
        await update.message.reply_text("✅ System prompt updated\\.")
    
    await show_tuning_menu(update, context)
    return SELECTING_SETTING

async def ask_for_temperature(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Asks for a new temperature value."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Please send a new temperature value between 0\\.0 and 2\\.0\\. "
        "Higher values mean more creativity, lower values mean more predictability \\(e\\.g\\., `0.8`\\)\\. Send /cancel to go back\\.",
        parse_mode='MarkdownV2'
    )
    return GETTING_TEMPERATURE

async def save_temperature(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the new temperature value."""
    try:
        temp = float(update.message.text)
        if 0.0 <= temp <= 2.0:
            set_user_temperature(update.effective_user.id, temp)
            await update.message.reply_text(f"✅ Temperature set to {f'{temp:.1f}'.replace('.', '\\.')}\\.", parse_mode='MarkdownV2')
            await show_tuning_menu(update, context)
            return SELECTING_SETTING
        else:
            await update.message.reply_text("Invalid range\\. Please send a number between 0\\.0 and 2\\.0\\.")
            return GETTING_TEMPERATURE
    except ValueError:
        await update.message.reply_text("That's not a valid number\\. Please try again\\.")
        return GETTING_TEMPERATURE

async def ask_for_top_p(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Asks for a new Top P value."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Please send a new Top P value between 0\\.0 and 1\\.0\\. "
        "This is an alternative to temperature sampling \\(e\\.g\\., `0.9`\\)\\. Send /cancel to go back\\.",
        parse_mode='MarkdownV2'
    )
    return GETTING_TOP_P

async def save_top_p(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the new Top P value."""
    try:
        top_p = float(update.message.text)
        if 0.0 <= top_p <= 1.0:
            set_user_top_p(update.effective_user.id, top_p)
            await update.message.reply_text(f"✅ Top P set to {f'{top_p:.1f}'.replace('.', '\\.')}\\.", parse_mode='MarkdownV2')
            await show_tuning_menu(update, context)
            return SELECTING_SETTING
        else:
            await update.message.reply_text("Invalid range\\. Please send a number between 0\\.0 and 1\\.0\\.")
            return GETTING_TOP_P
    except ValueError:
        await update.message.reply_text("That's not a valid number\\. Please try again\\.")
        return GETTING_TOP_P

async def ask_for_max_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Asks for a new max_tokens value."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Please send a new max tokens value \\(e\\.g\\., `2048`\\)\\. This controls the maximum length of the AI's response\\. "
        "A lower value can prevent long, rambling answers\\. Must be a whole number greater than 0\\. Send /cancel to go back\\.",
        parse_mode='MarkdownV2'
    )
    return GETTING_MAX_TOKENS

async def save_max_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the new max_tokens value."""
    try:
        max_tokens = int(update.message.text)
        if max_tokens > 0:
            set_user_max_tokens(update.effective_user.id, max_tokens)
            await update.message.reply_text(f"✅ Max Tokens set to {max_tokens}\\.")
            await show_tuning_menu(update, context)
            return SELECTING_SETTING
        else:
            await update.message.reply_text("Invalid value\\. Please send a whole number greater than 0\\.")
            return GETTING_MAX_TOKENS
    except ValueError:
        await update.message.reply_text("That's not a valid number\\. Please try again\\.")
        return GETTING_MAX_TOKENS

async def end_tuning_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ends the tuning conversation and returns to the main settings menu."""
    # This function will be defined in user_menu_handlers.py
    from user_menu_handlers import settings_menu_handler 
    await settings_menu_handler(update, context)
    return ConversationHandler.END

async def cancel_setting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the current setting input and returns to the tuning menu."""
    await show_tuning_menu(update, context)
    return SELECTING_SETTING 