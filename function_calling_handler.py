# function_calling_handler.py

import logging
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters
from telegram.helpers import escape_markdown

from database_manager import get_user_functions, add_custom_function, delete_custom_function

logger = logging.getLogger(__name__)

# --- State Definitions ---
SELECTING_ACTION, GETTING_NAME, GETTING_DESCRIPTION, GETTING_SCHEMA, CONFIRM_DELETE = range(5)

# --- Main Menu ---
async def functions_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Displays the main menu for managing custom functions."""
    query = update.callback_query
    if query: 
        await query.answer()

    if not update.effective_user:
        return ConversationHandler.END
    
    user_id = update.effective_user.id
    user_functions = get_user_functions(user_id)

    text = "🛠️ *Custom Functions Manager*\n\n"
    if not user_functions:
        text += "You have not defined any custom functions yet\\."
    else:
        text += "Here are your currently defined functions:\n"
        for func in user_functions:
            # --- FIX: Escape the function name for MarkdownV2 ---
            safe_name = escape_markdown(func['name'], version=2)
            text += f"  \\- `{safe_name}`\n"

    keyboard = [
        [InlineKeyboardButton("➕ Add New Function", callback_data='functions:add')],
    ]
    if user_functions:
        keyboard.append([InlineKeyboardButton("➖ Delete a Function", callback_data='functions:delete_menu')])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back to AI Settings", callback_data='functions:back_to_settings')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    else:
        # Handle re-entry from a message handler
        if update.message:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')

    return SELECTING_ACTION

# --- Add Function Flow ---
async def ask_for_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the process of adding a new function by asking for its name."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "🔧 *Add New Function*\n\n"
            "Please enter the name of the function \\(no spaces, use underscore if needed\\):",
            parse_mode='MarkdownV2'
        )

    # Store the starting action in context for later
    if context.user_data is not None:
        context.user_data['action'] = 'add_function'
    
    return GETTING_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the function name and ask for description."""
    if not update.message or not update.message.text:
        if update.message:
            await update.message.reply_text("Please provide a valid function name.")
        return GETTING_NAME
        
    function_name = update.message.text.strip()
    if context.user_data is not None:
        context.user_data['function_name'] = function_name
    
    await update.message.reply_text(
        f"✅ Function name: `{function_name}`\n\n"
        "Now, please provide a description of what this function does:",
        parse_mode='MarkdownV2'
    )
    return GETTING_DESCRIPTION

async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the function description and ask for JSON schema."""
    if not update.message or not update.message.text:
        if update.message:
            await update.message.reply_text("Please provide a valid description.")
        return GETTING_DESCRIPTION
        
    description = update.message.text.strip()
    if context.user_data is not None:
        context.user_data['function_description'] = description
        
    await update.message.reply_text(
        f"✅ Description saved\n\n"
        "Finally, please provide the JSON schema for the function parameters\\. "
        "This should be a valid JSON object describing the parameters your function accepts\\\\. "
        "\n\nExample:"
        "```json\n{"
        "  \\\"type\\\": \\\"object\\\","
        "  \\\"properties\\\": {"
        "    \\\"message\\\": {"
        "      \\\"type\\\": \\\"string\\\","
        "      \\\"description\\\": \\\"The message to send\\\""
        "    }"
        "  },"
        "  \\\"required\\\": [\\\"message\\\"]"
        "}```",
        parse_mode='MarkdownV2'
    )
    return GETTING_SCHEMA

async def get_schema_and_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the schema and save the complete function to database."""
    if not update.message or not update.message.text:
        if update.message:
            await update.message.reply_text("Please provide a valid JSON schema.")
        return GETTING_SCHEMA
        
    schema_text = update.message.text.strip()
    
    # Validate JSON
    try:
        json.loads(schema_text)
    except json.JSONDecodeError:
        if update.message:
            await update.message.reply_text("Invalid JSON format. Please try again with valid JSON.")
        return GETTING_SCHEMA

    # Get stored data
    if not update.effective_user:
        return ConversationHandler.END
        
    user_id = update.effective_user.id
    if context.user_data is None:
        return ConversationHandler.END
        
    name = context.user_data.get('function_name')
    description = context.user_data.get('function_description')
    
    if not name or not description:
        if update.message:
            await update.message.reply_text("Error: Missing function data. Please start over.")
        return ConversationHandler.END

    # Save to database
    success = add_custom_function(user_id, name, description, schema_text)
    if success:
        if update.message:
            await update.message.reply_text("✅ Function added successfully! You can now use it in your conversations.")
    else:
        if update.message:
            await update.message.reply_text("❌ Error saving function. Please try again.")

    # Check if we should return to functions menu or main settings
    if context.user_data and "functions:back_from" in context.user_data:
        action = context.user_data["functions:back_from"]
        if update.message:
            await update.message.reply_text("Returning to settings menu...")
        return ConversationHandler.END
    else:
        return ConversationHandler.END

# --- Delete Function Flow ---
async def show_delete_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show menu with functions that can be deleted."""
    query = update.callback_query
    if query:
        await query.answer()

    if not update.effective_user:
        return ConversationHandler.END
        
    user_id = update.effective_user.id
    user_functions = get_user_functions(user_id)

    if not user_functions:
        if query:
            await query.edit_message_text(
                "You don't have any custom functions to delete\\.",
                parse_mode='MarkdownV2'
            )
        return ConversationHandler.END
    else:
        if query:
            await query.edit_message_text(
                "Select a function to delete:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"🗑️ {func['name']}", 
                                        callback_data=f'functions:confirm_delete:{func["function_id"]}')]
                    for func in user_functions
                ] + [[InlineKeyboardButton("⬅️ Back", callback_data='functions:main_menu')]])
            )

    return CONFIRM_DELETE

async def confirm_delete_function(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Confirm and delete the selected function."""
    query = update.callback_query
    if query:
        await query.answer()

    if not update.effective_user or not query or not query.data:
        return ConversationHandler.END
        
    function_id = int(query.data.split(':')[2])
    user_id = update.effective_user.id

    success = delete_custom_function(function_id, user_id)
    if success:
        if query:
            await query.edit_message_text("✅ Function deleted successfully\\.", parse_mode='MarkdownV2')
    else:
        if query:
            await query.edit_message_text("❌ Error deleting function\\.", parse_mode='MarkdownV2')

    return ConversationHandler.END

# --- Navigation ---
async def back_to_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Return to main settings menu."""
    return ConversationHandler.END

async def cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the current operation."""
    if update.message:
        await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END