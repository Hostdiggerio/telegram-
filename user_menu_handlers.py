# user_menu_handlers.py (Version 4.1 - Polished UX)

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from database_manager import get_or_create_user, set_user_model, PLANS
from settings_handler import show_tuning_menu, SELECTING_SETTING
from fast_config import ADMIN_CONTACT_USERNAME # <-- NEW: Import config variable
from conversation_manager import clear_user_context, get_context_stats

logger = logging.getLogger(__name__)

# =================================================================
# MODEL SELECTION LOGIC (Now lives here)
# =================================================================

IMAGE_SUPPORTED_MODELS = ["mistral-large-latest", "mistral-medium-latest"]
MODELS_PER_PAGE = 6

# A dictionary to hold our partitioned models
PARTITIONED_MODELS = {
    "General & Chat": {
        "mistral-large-latest": "Mistral Large (Most Capable)",
        "mistral-medium-latest": "Mistral Medium (Balanced)",
        "mistral-small-latest": "Mistral Small (Fast & Economical)",
    },
    "Coding & Development": {
        "codestral-latest": "Codestral (Code Generation)",
        "devstral-medium-latest": "Devstral Medium (Software Engineering)",
    },
    "Specialized & Multilingual": {
        "mistral-saba-latest": "Mistral Saba (Middle East/South Asia)",
        "voxtral-mini-latest": "Voxtral (Audio Optimized)",
    },
    "Open Source Models": {
        "open-mixtral-8x22b": "Open Mixtral 8x22B",
        "open-mixtral-8x7b": "Open Mixtral 8x7B",
        "open-mistral-7b": "Open Mistral 7B",
    },
    "Legacy & Specialized": {
        "mistral-large-2407": "Mistral Large (2407)",
        "mistral-small-2409": "Mistral Small (2409)",
        "mistral-small-2501": "Mistral Small (2501)",
        "mistral-small-2503": "Mistral Small (2503)",
    }
}

# Flatten the models for backward compatibility
AVAILABLE_MODELS = {}
for category, models in PARTITIONED_MODELS.items():
    AVAILABLE_MODELS.update(models)
# =================================================================
# USER MENU HANDLERS
# =================================================================

async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greets the user and shows the main interactive menu."""
    user = get_or_create_user(update.effective_user)
    user_id = user['user_id']
    user_mention = f"[{escape_markdown(user['first_name'], version=2)}](tg://user?id={user['user_id']})"
    # Check if this is a new user for special launch message
    is_new_user = user['daily_images_used'] == 0 and user['daily_tokens_used'] == 0
    
    welcome_text = (
        f"👋 Hi there, {user_mention}\\! Welcome to *Nebula AI*\\!\n\n"
        f"🚀 **SPECIAL LAUNCH\\!** 🚀\n"
        f"🎉 You now have **FULL PREMIUM ACCESS** \\- completely FREE\\!\n\n"
        f"✨ **What you get:**\n"
        f"• 🖼️ **Unlimited image generation**\n"
        f"• 💬 **Unlimited AI conversations**\n"
        f"• 🧠 **Access to ALL AI models**\n"
        f"• 🛠️ **All premium features unlocked**\n"
        f"• 🎮 **Interactive modes \\(Image, Code, Web Search\\)**\n\n"
        f"🧪 **This is a test launch** \\- help us improve\\!\n"
        f"Found a bug or have feedback? Use the \"📞 Report Issue\" button below\\.\n\n"
        f"🚀 **Ready to explore?** Choose an option below\\!"
    )
    
    keyboard = [
        [InlineKeyboardButton("👤 My Account", callback_data='user:account')],
        [InlineKeyboardButton("⚙️ AI Settings", callback_data='user:settings')],  # Always available now
        [InlineKeyboardButton("🎮 Modes", callback_data='user:modes'), InlineKeyboardButton("🧠 Context", callback_data='user:context_menu')],
        [InlineKeyboardButton("❓ Help & About", callback_data='user:help_menu'), InlineKeyboardButton("📞 Report Issue", callback_data='user:report_issue')],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
        except Exception as e:
            # Handle duplicate message or parsing errors
            if "Message is not modified" in str(e):
                logger.warning(f"Attempted to edit message with same content for user {user_id}")
                return
            elif "Can't parse entities" in str(e):
                logger.error(f"MarkdownV2 parsing error in start_command_handler: {e}")
                # Fall back to plain text without markdown
                try:
                    await update.callback_query.edit_message_text(welcome_text.replace('*', '').replace('_', '').replace('`', ''), reply_markup=reply_markup)
                except Exception as fallback_error:
                    logger.error(f"Fallback edit also failed: {fallback_error}")
            else:
                logger.error(f"Unexpected error in start_command_handler: {e}")
                raise
    elif update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='MarkdownV2')


# --- NEW: Interactive Help Menu ---

async def help_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main help menu with different topics."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    
    help_text = "❓ *Help & About*\n\nChoose a topic below for more information\\."
    keyboard = [
        [InlineKeyboardButton("🖼️ Image Creation Guide", callback_data='user:help_images')],
        [InlineKeyboardButton("✨ Premium Features", callback_data='user:help_features')],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='user:main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    except Exception as e:
        user_id = update.effective_user.id if update.effective_user else "unknown"
        if "Message is not modified" in str(e):
            logger.warning(f"Attempted to edit message with same content for user {user_id}")
            return
        elif "Can't parse entities" in str(e):
            logger.error(f"MarkdownV2 parsing error in help_menu_handler: {e}")
            try:
                await query.edit_message_text(help_text.replace('*', '').replace('_', '').replace('`', ''), reply_markup=reply_markup)
            except Exception as fallback_error:
                logger.error(f"Fallback edit failed: {fallback_error}")
        else:
            logger.error(f"Unexpected error in help_menu_handler: {e}")
            raise


async def help_images_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comprehensive guide for image creation - covers both /image and /imagemode."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    
    help_text = (
        "🖼️ *Complete Image Creation Guide*\n\n"
        "🎯 **Two Ways to Create Images:**\n\n"
        "**1\\. Single Image \\(`/image`\\)**\n"
        "• Use: `/image your description here`\n"
        "• Creates one image per command\n"
        "• Example: `/image sunset over mountains`\n\n"
        "**2\\. Image Mode \\(`/imagemode`\\)**\n"
        "• Use: `/imagemode` to enter creative mode\n"
        "• Every message becomes an image prompt\n"
        "• No need to repeat `/image` command\n"
        "• Type `/imagemode` again to exit\n\n"
        "✨ **Pro Tips for Better Images:**\n"
        "• Be descriptive: `golden sunset with purple clouds`\n"
        "• Add styles: `watercolor painting of a forest`\n"
        "• Include mood: `peaceful lake scene, misty morning`\n"
        "• Specify details: `modern kitchen, warm lighting`\n\n"
        "🔧 **Great Examples:**\n"
        "• `cyberpunk city with neon lights`\n"
        "• `cute corgi puppy playing in grass`\n"
        "• `vintage car on mountain road`\n\n"
        "📋 **Requirements:**\n"
        "• Depends on your plan's daily limits\n"
        "• Premium Plus: Must select 🖼️ model in settings"
    )
    
    keyboard = [[InlineKeyboardButton("⬅️ Back to Help Menu", callback_data='user:help_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    except Exception as e:
        user_id = update.effective_user.id if update.effective_user else "unknown"
        if "Message is not modified" in str(e):
            logger.warning(f"Attempted to edit message with same content for user {user_id}")
            return
        elif "Can't parse entities" in str(e):
            logger.error(f"MarkdownV2 parsing error in help_images_handler: {e}")
            try:
                await query.edit_message_text(help_text.replace('*', '').replace('_', '').replace('`', ''), reply_markup=reply_markup)
            except Exception as fallback_error:
                logger.error(f"Fallback edit failed: {fallback_error}")
        else:
            logger.error(f"Unexpected error in help_images_handler: {e}")
            raise


async def help_features_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display comprehensive feature information with RAG explanation."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    
    help_text = (
        "🎯 *Advanced Features & Capabilities*\n\n"
        "📚 **Document Intelligence \\(RAG\\)**\n"
        "• Upload ANY document \\(PDF, DOC, TXT, MD\\)\n"
        "• AI automatically reads and indexes content\n"
        "• Search using natural language questions\n"
        "• Get precise answers from YOUR documents\n"
        "• *Example*: Upload a manual, ask \"How do I reset the password?\"\n\n"
        "🎨 **Image Generation Mode**\n"
        "• Use `/imagemode` to enter creative mode\n"
        "• Everything you type becomes an image prompt\n"
        "• Perfect for rapid visual prototyping\n"
        "• Type `/imagemode` again to exit\n\n"
        "🧠 **Smart Tool Selection**\n"
        "• `/websearch` \\- Real\\-time web information\n"
        "• `/code` \\- Execute and analyze code\n"
        "• Auto\\-selects best tools for your question\n\n"
        "⚙️ **Advanced Settings \\(Premium Plus\\)**\n"
        "• Switch between 20\\+ AI models\n"
        "• Control creativity \\(temperature\\)\n"
        "• Custom system prompts\n"
        "• Add your own functions\n\n"
        "🔊 **Multi\\-Media Support**\n"
        "• Voice messages \\(auto\\-transcribed\\)\n"
        "• Image analysis and OCR\n"
        "• Document auto\\-processing"
    )
    
    keyboard = [
        [InlineKeyboardButton("📚 Learn About Document Intelligence", callback_data='user:help_rag')],
        [InlineKeyboardButton("⬅️ Back to Help Menu", callback_data='user:help_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    except Exception as e:
        user_id = update.effective_user.id if update.effective_user else "unknown"
        if "Message is not modified" in str(e):
            logger.warning(f"Attempted to edit message with same content for user {user_id}")
            return
        elif "Can't parse entities" in str(e):
            logger.error(f"MarkdownV2 parsing error in help_features_handler: {e}")
            try:
                await query.edit_message_text(help_text.replace('*', '').replace('_', '').replace('`', ''), reply_markup=reply_markup)
            except Exception as fallback_error:
                logger.error(f"Fallback edit failed: {fallback_error}")
        else:
            logger.error(f"Unexpected error in help_features_handler: {e}")
            raise

async def help_rag_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comprehensive RAG (Retrieval Augmented Generation) explanation."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    
    rag_text = (
        "📚 *What is RAG \\(Document Intelligence\\)?*\n\n"
        "**RAG** \\= Retrieval Augmented Generation\n"
        "It's like giving the AI access to YOUR personal knowledge base\\!\n\n"
        "🔍 **How It Works:**\n"
        "1️⃣ Upload documents \\(PDF, Word, TXT, etc\\.\\)\n"
        "2️⃣ AI breaks them into searchable chunks\n"
        "3️⃣ Creates smart indexes for instant search\n"
        "4️⃣ When you ask questions, AI finds relevant parts\n"
        "5️⃣ Generates answers using YOUR document content\n\n"
        "✨ **What Makes It Powerful:**\n"
        "• Searches by *meaning*, not just keywords\n"
        "• Understands context and relationships\n"
        "• Gives precise, sourced answers\n"
        "• Works with ANY document type\n\n"
        "💡 **Perfect For:**\n"
        "• Research papers & articles\n"
        "• Company policies & manuals\n"
        "• Legal documents & contracts\n"
        "• Technical documentation\n"
        "• Personal notes & books\n\n"
        "🚀 **Getting Started:**\n"
        "1\\. Simply upload any document \\(drag & drop\\)\n"
        "2\\. Wait for \"Document uploaded successfully\\!\"\n"
        "3\\. Use `/doc your question here`\n"
        "4\\. Get intelligent answers from YOUR content\\!\n\n"
        "*Example*: `/doc what are the main conclusions?`"
    )
    
    keyboard = [[InlineKeyboardButton("⬅️ Back to Features", callback_data='user:help_features')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text(rag_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    except Exception as e:
        user_id = update.effective_user.id if update.effective_user else "unknown"
        if "Message is not modified" in str(e):
            logger.warning(f"Attempted to edit message with same content for user {user_id}")
            return
        elif "Can't parse entities" in str(e):
            logger.error(f"MarkdownV2 parsing error in help_rag_handler: {e}")
            try:
                await query.edit_message_text(rag_text.replace('*', '').replace('_', '').replace('`', ''), reply_markup=reply_markup)
            except Exception as fallback_error:
                logger.error(f"Fallback edit failed: {fallback_error}")
        else:
            logger.error(f"Unexpected error in help_rag_handler: {e}")
            raise

# --- END NEW HELP MENU ---


async def subscribe_info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows a detailed and polished comparison of subscription plans."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    plans_info = {'premium': {'price': '5 USD'}, 'premium_plus': {'price': '10 USD'}}

    text = (
        "💎 *Upgrade Your Plan*\n\n"
        "Unlock higher limits and advanced features to get the most out of Nebula AI\\. All payments are handled securely with the admin\\.\n\n"
        "─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─\n\n"
        "⭐️ **Premium Plan**\n"
        f"*Price: {plans_info['premium']['price']} per month*\n"
        "The ideal choice for power users who need more resources\\.\n\n"
        f"✅ *Daily Images:* **{PLANS['premium']['daily_images']}**\n"
        f"✅ *Daily Chat Tokens:* **{PLANS['premium']['daily_tokens_limit']:,}**\n"
        "✅ *Access to Web Search*\n\n"
        "─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─\n\n"
        "✨ **Premium Plus Plan**\n"
        f"*Price: {plans_info['premium_plus']['price']} per month*\n"
        "The ultimate package for professionals and enthusiasts who want full control\\.\n\n"
        "✅ *Daily Images:* **Unlimited** 🖼️\n"
        "✅ *Daily Chat Tokens:* **Unlimited** 🤖\n"
        "✅ *All Premium Features* PLUS:\n"
        "✅ *AI Model Selection:* Choose from 20\\+ specialized models\\.\n"
        "✅ *Parameter Tuning:* Control AI creativity, verbosity, and more\\.\n"
        "✅ *Custom Functions:* Define your own tools for the AI\\.\n\n"
        "─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─\n\n"
        "Ready to upgrade? Click below to generate a purchase ticket\\."
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ Confirm & Create Purchase Ticket", callback_data='user:create_ticket')],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='user:main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    except Exception as e:
        # Handle duplicate message or parsing errors
        user_id = update.effective_user.id if update.effective_user else "unknown"
        if "Message is not modified" in str(e):
            logger.warning(f"Attempted to edit message with same content for user {user_id}")
            return
        elif "Can't parse entities" in str(e):
            logger.error(f"MarkdownV2 parsing error in subscribe_info_handler: {e}")
            # Fall back to plain text without markdown
            try:
                await query.edit_message_text(text.replace('*', '').replace('_', '').replace('`', ''), reply_markup=reply_markup)
            except Exception as fallback_error:
                logger.error(f"Fallback edit also failed: {fallback_error}")
        else:
            logger.error(f"Unexpected error in subscribe_info_handler: {e}")
            raise


async def create_purchase_ticket_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the final confirmation and provides the user with their ticket."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    final_text = (
        "Great\\! Your purchase ticket has been created\\. A message with your User ID is below\\.\n\n"
        f"Please **forward that message** to the admin \\(@{ADMIN_CONTACT_USERNAME}\\) to complete your purchase\\."
    )

    keyboard = [
        [InlineKeyboardButton(f"Contact Admin (@{ADMIN_CONTACT_USERNAME})", url=f"https://t.me/{ADMIN_CONTACT_USERNAME}")],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='user:main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.edit_message_text(final_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    except Exception as e:
        # Handle duplicate message or parsing errors
        user_id = update.effective_user.id if update.effective_user else "unknown"
        if "Message is not modified" in str(e):
            logger.warning(f"Attempted to edit message with same content for user {user_id}")
            # Still send the ticket message even if edit fails
        elif "Can't parse entities" in str(e):
            logger.error(f"MarkdownV2 parsing error in create_purchase_ticket_handler: {e}")
            # Fall back to plain text without markdown
            try:
                await query.edit_message_text(final_text.replace('*', '').replace('_', '').replace('`', ''), reply_markup=reply_markup)
            except Exception as fallback_error:
                logger.error(f"Fallback edit also failed: {fallback_error}")
        else:
            logger.error(f"Unexpected error in create_purchase_ticket_handler: {e}")
            raise

    if not update.effective_user:
        return
    user_id = update.effective_user.id
    copy_paste_message = f"Hi, I would like to upgrade my plan\\! My User ID is:\n`{user_id}`"
    try:
        await context.bot.send_message(chat_id=user_id, text=copy_paste_message, parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Failed to send ticket message: {e}")
        # Try without markdown
        try:
            await context.bot.send_message(chat_id=user_id, text=copy_paste_message.replace('\\', '').replace('`', ''))
        except Exception as fallback_error:
            logger.error(f"Failed to send fallback ticket message: {fallback_error}")

async def account_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_or_create_user(update.effective_user)
    plan_details = PLANS[user['plan_name']]
    expiry_date_str = "Never"
    if user['subscription_expiry_date']:
        expiry_date_str = datetime.fromisoformat(user['subscription_expiry_date']).strftime("%Y-%m-%d")
    images_limit_str = "Unlimited" if plan_details['daily_images'] == -1 else str(plan_details['daily_images'])
    tokens_limit_str = "Unlimited" if plan_details['daily_tokens_limit'] == -1 else f"{plan_details['daily_tokens_limit']:,}"
    status_text = (
        f"👤 *My Account Status*\n\n"
        f"**Plan:** `{user['plan_name'].upper()}`\n"
        f"**Subscription Expires:** `{expiry_date_str}`\n\n"
        f"__Daily Usage__:\n"
        f"🖼️ Images: `{user['daily_images_used']} / {images_limit_str}`\n"
        f"🤖 Chat Tokens: `{user['daily_tokens_used']:,} / {tokens_limit_str}`"
    )
    keyboard = [[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='user:main_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(status_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    elif update.message:
        await update.message.reply_text(status_text, reply_markup=reply_markup, parse_mode='MarkdownV2')

async def settings_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the AI settings menu for premium_plus users."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    
    user = get_or_create_user(update.effective_user)
    current_model_name = AVAILABLE_MODELS.get(user['current_model'], user['current_model'])

    text = (
        f"⚙️ *AI Settings Panel*\n\n"
        f"Here you can customize your AI experience\\. This is a *Premium Plus* feature\\.\n\n"
        f"*Current Model:* `{escape_markdown(current_model_name, version=2)}`"
    )
    keyboard = [
        [InlineKeyboardButton("🔄 Change Active Model", callback_data='models:change:0')],
        [InlineKeyboardButton("🔧 Tune Parameters", callback_data='settings:tune')],
        [InlineKeyboardButton("🛠️ Custom Functions", callback_data='settings:functions')],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='user:main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    except Exception as e:
        user_id = update.effective_user.id if update.effective_user else "unknown"
        if "Message is not modified" in str(e):
            logger.warning(f"Attempted to edit message with same content for user {user_id}")
            return
        elif "Can't parse entities" in str(e):
            logger.error(f"MarkdownV2 parsing error in settings_menu_handler: {e}")
            try:
                await query.edit_message_text(text.replace('*', '').replace('_', '').replace('`', ''), reply_markup=reply_markup)
            except Exception as fallback_error:
                logger.error(f"Fallback edit failed: {fallback_error}")
        else:
            logger.error(f"Unexpected error in settings_menu_handler: {e}")
            raise


async def start_tuning_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for the parameter tuning conversation."""
    await show_tuning_menu(update, context)
    return SELECTING_SETTING


async def show_paginated_model_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays a paginated list of available models organized by category."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    
    # Get the category from the callback data, default to first category
    category_index = int(query.data.split(':')[-1]) if ':' in query.data else 0
    categories = list(PARTITIONED_MODELS.keys())
    
    if category_index >= len(categories):
        category_index = 0
    
    current_category = categories[category_index]
    models_in_category = list(PARTITIONED_MODELS[current_category].items())
    
    # Create keyboard with models in current category
    keyboard = []
    for model_id, model_name in models_in_category:
        if model_id in IMAGE_SUPPORTED_MODELS:
            model_name += " 🖼️"
        keyboard.append([InlineKeyboardButton(model_name, callback_data=f'models:set:{model_id}')])
    
    # Navigation buttons for categories
    nav_buttons = []
    if category_index > 0: 
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev Category", callback_data=f'models:change:{category_index-1}'))
    if category_index < len(categories) - 1: 
        nav_buttons.append(InlineKeyboardButton("Next Category ➡️", callback_data=f'models:change:{category_index+1}'))
    if nav_buttons: 
        keyboard.append(nav_buttons)
    
    # Category indicator and back button
    keyboard.append([InlineKeyboardButton(f"📁 {current_category}", callback_data='models:category_info')])
    keyboard.append([InlineKeyboardButton("⬅️ Back to Settings", callback_data='user:settings')])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"Please select your new active model from the **{current_category}** category:", 
        reply_markup=reply_markup
    )


async def set_new_model_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets the user's new model choice and returns to the settings menu."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    model_id = query.data.split(":")[2]
    if not update.effective_user:
        return
    user_id = update.effective_user.id
    set_user_model(user_id, model_id)
    await settings_menu_handler(update, context)

# =================================================================
# MODES MENU HANDLERS
# =================================================================

async def modes_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the interactive modes menu with current status."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    
    user_id = update.effective_user.id if update.effective_user else 0
    
    # Check current modes status
    image_mode_on = ('image_mode_users' in context.bot_data and 
                     user_id in context.bot_data['image_mode_users'])
    code_mode_on = ('code_mode_users' in context.bot_data and 
                    user_id in context.bot_data['code_mode_users'])
    websearch_mode_on = ('websearch_mode_users' in context.bot_data and 
                        user_id in context.bot_data['websearch_mode_users'])
    
    # Build status indicators
    image_status = "🟢 ON" if image_mode_on else "🔴 OFF"
    code_status = "🟢 ON" if code_mode_on else "🔴 OFF" 
    websearch_status = "🟢 ON" if websearch_mode_on else "🔴 OFF"
    
    # Determine current mode text with enhanced status
    active_modes = []
    if image_mode_on: active_modes.append("🎨 Image")
    if code_mode_on: active_modes.append("💻 Code") 
    if websearch_mode_on: active_modes.append("🌐 Web Search")
    
    if active_modes:
        current_mode = f"🟢 **Currently Active**: {escape_markdown(', '.join(active_modes), version=2)} Mode"
        status_emoji = "🟢"
        status_text = "You're in a specialized mode\\! Every message you send will be processed accordingly\\."
    else:
        current_mode = "💬 **Normal Chat Mode**"
        status_emoji = "⚡"
        status_text = "Smart mode with web search and code interpreter automatically selected\\."
    
    text = (
        f"🎮 *Interactive Modes Control Panel*\n\n"
        f"{current_mode}\n"
        f"{status_emoji} {status_text}\n\n"
        f"────────────────────────\n\n"
        f"🎨 **Image Generation Mode** {escape_markdown(image_status, version=2)}\n"
        f"   • Turn every message into stunning images\n"
        f"   • Perfect for creative brainstorming\n\n"
        f"💻 **Code Development Mode** {escape_markdown(code_status, version=2)}\n"
        f"   • Every message becomes a coding task  \n"
        f"   • Write, debug, and explain code\n\n"
        f"🌐 **Web Research Mode** {escape_markdown(websearch_status, version=2)}\n"
        f"   • Search the web for real\\-time information\n"
        f"   • Get current news, weather, and data\n\n"
        f"💡 *Tip: Only one mode can be active at a time*"
    )
    
    keyboard = [
        [InlineKeyboardButton(f"🎨 Image Mode ({image_status})", callback_data='modes:toggle:image')],
        [InlineKeyboardButton(f"💻 Code Mode ({code_status})", callback_data='modes:toggle:code')], 
        [InlineKeyboardButton(f"🌐 Web Search Mode ({websearch_status})", callback_data='modes:toggle:websearch')],
        [InlineKeyboardButton("🔄 Turn Off All Modes", callback_data='modes:off_all')],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='user:main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    except Exception as e:
        # Handle duplicate message or parsing errors
        if "Message is not modified" in str(e):
            logger.warning(f"Attempted to edit message with same content for user {user_id}")
            return
        elif "Can't parse entities" in str(e):
            logger.error(f"MarkdownV2 parsing error: {e}")
            # Fall back to plain text without markdown
            try:
                await query.edit_message_text(text.replace('*', '').replace('_', '').replace('`', ''), reply_markup=reply_markup)
            except Exception as fallback_error:
                logger.error(f"Fallback edit also failed: {fallback_error}")
        else:
            logger.error(f"Unexpected error in modes_menu_handler: {e}")
            raise

async def toggle_mode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle specific modes on/off."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    
    user_id = update.effective_user.id if update.effective_user else 0
    mode = query.data.split(':')[2]  # modes:toggle:image -> 'image'
    
    # Initialize mode sets if needed
    for mode_type in ['image_mode_users', 'code_mode_users', 'websearch_mode_users']:
        if mode_type not in context.bot_data:
            context.bot_data[mode_type] = set()
    
    if mode == 'image':
        if user_id in context.bot_data['image_mode_users']:
            context.bot_data['image_mode_users'].remove(user_id)
            status_msg = "🎨 **Image Mode: OFF**\n\n✅ Back to normal chat!"
        else:
            # Turn off other modes first
            context.bot_data['code_mode_users'].discard(user_id)
            context.bot_data['websearch_mode_users'].discard(user_id)
            context.bot_data['image_mode_users'].add(user_id)
            status_msg = (
                "🎨 **Image Generation Mode: ACTIVATED** ✅\n\n"
                "🌟 **What's Changed:**\n"
                "• Every message you send will create an image\n"
                "• No need to use `/image` command anymore\n"
                "• Be descriptive for amazing results!\n\n"
                "🎯 **Examples to try:**\n"
                "• *\"sunset over snow-covered mountains\"*\n"
                "• *\"futuristic cyberpunk city at night\"*\n"
                "• *\"cute puppy playing in a garden\"*\n\n"
                "💡 **Quick Exit:** Go to 🎮 Modes or type `/imagemode`"
            )
    
    elif mode == 'code':
        if user_id in context.bot_data['code_mode_users']:
            context.bot_data['code_mode_users'].remove(user_id)
            status_msg = "💻 **Code Mode: OFF**\n\n✅ Back to normal chat!"
        else:
            # Turn off other modes first
            context.bot_data['image_mode_users'].discard(user_id)
            context.bot_data['websearch_mode_users'].discard(user_id)
            context.bot_data['code_mode_users'].add(user_id)
            status_msg = (
                "💻 **Code Development Mode: ACTIVATED** ✅\n\n"
                "⚡ **What's Changed:**\n"
                "• Every message becomes a coding task\n"
                "• Get help with programming, debugging, and algorithms\n"
                "• Code execution and analysis available\n\n"
                "🛠️ **What you can ask:**\n"
                "• *\"Create a Python function to calculate fibonacci\"*\n"
                "• *\"Debug this JavaScript code: [paste code]\"*\n"
                "• *\"Explain how bubble sort works\"*\n\n"
                "💡 **Quick Exit:** Go to 🎮 Modes menu"
            )
    
    elif mode == 'websearch':
        if user_id in context.bot_data['websearch_mode_users']:
            context.bot_data['websearch_mode_users'].remove(user_id)
            status_msg = "🌐 **Web Search Mode: OFF**\n\n✅ Back to normal chat!"
        else:
            # Turn off other modes first  
            context.bot_data['image_mode_users'].discard(user_id)
            context.bot_data['code_mode_users'].discard(user_id)
            context.bot_data['websearch_mode_users'].add(user_id)
            status_msg = (
                "🌐 **Web Research Mode: ACTIVATED** ✅\n\n"
                "🔍 **What's Changed:**\n"
                "• Every message searches the web for real-time information\n"
                "• Get the latest news, data, and current events\n"
                "• Perfect for research and fact-checking\n\n"
                "📰 **Great questions to ask:**\n"
                "• *\"What's the latest news about AI?\"*\n"
                "• *\"Current weather in Tokyo\"*\n"
                "• *\"Stock price of Tesla today\"*\n\n"
                "💡 **Quick Exit:** Go to 🎮 Modes menu"
            )
    else:
        # Default fallback for unknown modes
        status_msg = "❌ Unknown mode. Please try again."
    
    # Show confirmation message
    keyboard = [
        [InlineKeyboardButton("🎮 Back to Modes Menu", callback_data='user:modes')],
        [InlineKeyboardButton("🏠 Main Menu", callback_data='user:main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(status_msg, reply_markup=reply_markup, parse_mode='Markdown')

async def turn_off_all_modes_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Turn off all active modes."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    
    user_id = update.effective_user.id if update.effective_user else 0
    
    # Initialize and clear all modes
    for mode_type in ['image_mode_users', 'code_mode_users', 'websearch_mode_users']:
        if mode_type not in context.bot_data:
            context.bot_data[mode_type] = set()
        context.bot_data[mode_type].discard(user_id)
    
    text = (
        "🔄 **All Modes Turned OFF**\n\n"
        "✅ You're back to normal chat mode!\n"
        "💬 Your messages will use smart detection with web search and code interpreter."
    )
    
    keyboard = [
        [InlineKeyboardButton("🎮 Back to Modes Menu", callback_data='user:modes')],
        [InlineKeyboardButton("🏠 Main Menu", callback_data='user:main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def image_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle image generation cancel button."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    await query.edit_message_text(
        "❌ **Image Generation Cancelled**\n\n"
        "💡 You can try again anytime with `/image` or activate Image Mode in 🎮 Modes!",
        parse_mode='Markdown'
    ) 

# =================================================================
# CONTEXT MANAGEMENT HANDLERS
# =================================================================

async def context_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the context management menu."""
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    
    user_id = update.effective_user.id
    stats = get_context_stats(user_id)
    
    menu_text = (
        f"🧠 *Context Management*\n\n"
        f"📊 **Current Status:**\n"
        f"💬 Messages in Memory: {stats.get('messages', 0)}\n"
        f"🏷️ Current Topic: {escape_markdown(stats.get('current_topic', 'None'), version=2)}\n"
        f"⏰ Last Reset: {escape_markdown(stats.get('last_reset', 'Never'), version=2)}\n\n"
        f"🤖 **What is Context?**\n"
        f"Context is the conversation history I remember to give you relevant responses\\. "
        f"Sometimes when you change topics, old context can cause confusion\\.\n\n"
        f"✨ **Auto\\-Reset Triggers:**\n"
        f"• Say \"new topic\" or \"change subject\"\n"
        f"• Major topic shifts are detected automatically\n\n"
        f"Choose an action below:"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔄 Reset Context", callback_data='context:reset')],
        [InlineKeyboardButton("🆕 New Conversation", callback_data='context:new_convo')],
        [InlineKeyboardButton("📊 View Details", callback_data='context:details')],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='user:main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(menu_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    except Exception as e:
        if "Message is not modified" in str(e):
            logger.warning(f"Attempted to edit message with same content for user {user_id}")
            return
        elif "Can't parse entities" in str(e):
            logger.error(f"MarkdownV2 parsing error in context_menu_handler: {e}")
            try:
                await query.edit_message_text(menu_text.replace('*', '').replace('_', '').replace('`', ''), reply_markup=reply_markup)
            except Exception as fallback_error:
                logger.error(f"Fallback edit failed: {fallback_error}")
        else:
            logger.error(f"Unexpected error in context_menu_handler: {e}")
            raise

async def context_reset_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset conversation context via button."""
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    
    user_id = update.effective_user.id
    success = clear_user_context(user_id)
    
    if success:
        result_text = (
            "🔄 **Context Reset Complete\\!**\n\n"
            "✨ Your conversation history has been cleared\\. I'll start fresh from your next message\\!\n\n"
            "💡 **What happened:**\n"
            "• All previous messages removed from memory\n"
            "• Topic keywords cleared\n"
            "• Fresh context established\n\n"
            "Ready for a new conversation\\!"
        )
    else:
        result_text = (
            "ℹ️ **Nothing to Reset**\n\n"
            "You don't have any conversation history yet\\.\n\n"
            "Start chatting and I'll remember our conversation\\!"
        )
    
    keyboard = [
        [InlineKeyboardButton("🆕 Start New Conversation", callback_data='context:new_convo')],
        [InlineKeyboardButton("🧠 Back to Context Menu", callback_data='user:context_menu')],
        [InlineKeyboardButton("🏠 Main Menu", callback_data='user:main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(result_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    except Exception as e:
        if "Message is not modified" in str(e):
            logger.warning(f"Attempted to edit message with same content for user {user_id}")
            return
        elif "Can't parse entities" in str(e):
            logger.error(f"MarkdownV2 parsing error in context_reset_handler: {e}")
            try:
                await query.edit_message_text(result_text.replace('*', '').replace('_', '').replace('`', ''), reply_markup=reply_markup)
            except Exception as fallback_error:
                logger.error(f"Fallback edit failed: {fallback_error}")
        else:
            logger.error(f"Unexpected error in context_reset_handler: {e}")
            raise

async def context_new_convo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a completely new conversation via button."""
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    
    user_id = update.effective_user.id
    clear_user_context(user_id)
    
    result_text = (
        "🆕 **New Conversation Started\\!**\n\n"
        "✨ Clean slate\\! What would you like to talk about?\n\n"
        "🎯 **Perfect for:**\n"
        "• Switching to completely different topics\n"
        "• Starting fresh after long conversations\n"
        "• When you want focused responses\n\n"
        "🚀 **Ready to chat\\!** Send me any message to begin\\."
    )
    
    keyboard = [
        [InlineKeyboardButton("🧠 Back to Context Menu", callback_data='user:context_menu')],
        [InlineKeyboardButton("🏠 Main Menu", callback_data='user:main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(result_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    except Exception as e:
        if "Message is not modified" in str(e):
            logger.warning(f"Attempted to edit message with same content for user {user_id}")
            return
        elif "Can't parse entities" in str(e):
            logger.error(f"MarkdownV2 parsing error in context_new_convo_handler: {e}")
            try:
                await query.edit_message_text(result_text.replace('*', '').replace('_', '').replace('`', ''), reply_markup=reply_markup)
            except Exception as fallback_error:
                logger.error(f"Fallback edit failed: {fallback_error}")
        else:
            logger.error(f"Unexpected error in context_new_convo_handler: {e}")
            raise

async def context_details_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed context information."""
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    
    user_id = update.effective_user.id
    stats = get_context_stats(user_id)
    
    details_text = (
        f"📊 **Detailed Context Information**\n\n"
        f"💬 **Messages in Memory:** {stats.get('messages', 0)}\n"
        f"🏷️ **Current Topic:** {escape_markdown(stats.get('current_topic', 'None'), version=2)}\n"
        f"⏰ **Last Reset:** {escape_markdown(stats.get('last_reset', 'Never'), version=2)}\n\n"
        f"🧠 **How Smart Context Works:**\n\n"
        f"**Automatic Detection:**\n"
        f"• Analyzes keywords in your messages\n"
        f"• Detects topic changes \\(70\\% threshold\\)\n"
        f"• Automatically resets when topics shift\n\n"
        f"**Manual Control:**\n"
        f"• Use buttons for instant reset\n"
        f"• Say \"new topic\" for auto\\-reset\n"
        f"• Perfect for topic switching\n\n"
        f"**Memory Management:**\n"
        f"• Keeps recent \\+ relevant messages\n"
        f"• Removes outdated context\n"
        f"• Prevents topic confusion\n\n"
        f"💡 **Tip:** The system learns what's relevant to keep our conversation focused\\!"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔄 Reset Now", callback_data='context:reset')],
        [InlineKeyboardButton("🆕 New Conversation", callback_data='context:new_convo')],
        [InlineKeyboardButton("🧠 Back to Context Menu", callback_data='user:context_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(details_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    except Exception as e:
        if "Message is not modified" in str(e):
            logger.warning(f"Attempted to edit message with same content for user {user_id}")
            return
        elif "Can't parse entities" in str(e):
            logger.error(f"MarkdownV2 parsing error in context_details_handler: {e}")
            try:
                await query.edit_message_text(details_text.replace('*', '').replace('_', '').replace('`', ''), reply_markup=reply_markup)
            except Exception as fallback_error:
                logger.error(f"Fallback edit failed: {fallback_error}")
        else:
            logger.error(f"Unexpected error in context_details_handler: {e}")
            raise

# =================================================================
# ISSUE REPORTING SYSTEM
# =================================================================

async def report_issue_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the issue reporting menu."""
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    
    report_text = (
        f"📞 **Report Issue or Feedback**\n\n"
        f"🧪 Since this is our **test launch**, your feedback is super valuable\\!\n\n"
        f"🐛 **What you can report:**\n"
        f"• Bugs or errors you encountered\n"
        f"• Features that aren't working\n"
        f"• Suggestions for improvements\n"
        f"• General feedback about the bot\n\n"
        f"📝 **How it works:**\n"
        f"1\\. Click \"Send Report\" below\n"
        f"2\\. Type your message \\(describe the issue/feedback\\)\n"
        f"3\\. Your message goes directly to @{ADMIN_CONTACT_USERNAME}\n\n"
        f"💬 **Be specific\\!** Include what you were doing when the issue happened\\."
    )
    
    keyboard = [
        [InlineKeyboardButton("📝 Send Report", callback_data='report:start')],
        [InlineKeyboardButton("💬 Contact Admin Directly", url=f"https://t.me/{ADMIN_CONTACT_USERNAME}")],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='user:main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(report_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    except Exception as e:
        if "Message is not modified" in str(e):
            logger.warning(f"Attempted to edit message with same content")
            return
        elif "Can't parse entities" in str(e):
            logger.error(f"MarkdownV2 parsing error in report_issue_handler: {e}")
            try:
                await query.edit_message_text(report_text.replace('*', '').replace('_', '').replace('`', ''), reply_markup=reply_markup)
            except Exception as fallback_error:
                logger.error(f"Fallback edit failed: {fallback_error}")
        else:
            logger.error(f"Unexpected error in report_issue_handler: {e}")
            raise

async def start_report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the report conversation."""
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    
    # Set user state for report
    if context.user_data is None:
        context.user_data = {}
    context.user_data['reporting_issue'] = True
    
    instruction_text = (
        f"📝 **Ready to Send Your Report\\!**\n\n"
        f"✍️ **Type your message now:**\n"
        f"• Describe the issue or feedback\n"
        f"• Be as detailed as possible\n"
        f"• Include what you were doing when it happened\n\n"
        f"📤 Your next message will be sent directly to @{escape_markdown(ADMIN_CONTACT_USERNAME, version=2)}\\!\n\n"
        f"❌ **Cancel anytime** by clicking below\\."
    )
    
    keyboard = [
        [InlineKeyboardButton("❌ Cancel Report", callback_data='report:cancel')],
        [InlineKeyboardButton("🏠 Main Menu", callback_data='user:main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(instruction_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    except Exception as e:
        if "Message is not modified" in str(e):
            logger.warning(f"Attempted to edit message with same content")
            return
        elif "Can't parse entities" in str(e):
            logger.error(f"MarkdownV2 parsing error in start_report_handler: {e}")
            try:
                await query.edit_message_text(instruction_text.replace('*', '').replace('_', '').replace('`', ''), reply_markup=reply_markup)
            except Exception as fallback_error:
                logger.error(f"Fallback edit failed: {fallback_error}")
        else:
            logger.error(f"Unexpected error in start_report_handler: {e}")
            raise

async def cancel_report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the report process."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    
    # Clear user state
    if context.user_data and 'reporting_issue' in context.user_data:
        del context.user_data['reporting_issue']
    
    cancel_text = (
        f"❌ **Report Cancelled**\n\n"
        f"No worries\\! You can report issues anytime\\.\n\n"
        f"💡 **Remember:** You can always contact @{escape_markdown(ADMIN_CONTACT_USERNAME, version=2)} directly if needed\\!"
    )
    
    keyboard = [
        [InlineKeyboardButton("📞 Try Again", callback_data='user:report_issue')],
        [InlineKeyboardButton("🏠 Main Menu", callback_data='user:main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(cancel_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    except Exception as e:
        if "Message is not modified" in str(e):
            logger.warning(f"Attempted to edit message with same content")
            return
        elif "Can't parse entities" in str(e):
            logger.error(f"MarkdownV2 parsing error in cancel_report_handler: {e}")
            try:
                await query.edit_message_text(cancel_text.replace('*', '').replace('_', '').replace('`', ''), reply_markup=reply_markup)
            except Exception as fallback_error:
                logger.error(f"Fallback edit failed: {fallback_error}")
        else:
            logger.error(f"Unexpected error in cancel_report_handler: {e}")
            raise 