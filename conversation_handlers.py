# conversation_handlers.py (Version 4.0 - Broadcast Feature)

import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, 
    CallbackQueryHandler, MessageHandler, filters
)
from telegram.error import Forbidden, BadRequest
from telegram.helpers import escape_markdown

from admin_panel import admin_only
from database_manager import get_user_by_id, set_user_plan, PLANS, get_all_user_ids, get_bot_statistics, get_full_user_data_for_export, set_user_ban_status, set_user_active_status
from mistral_client_official import (
    list_libraries, create_library, delete_library, list_library_documents,
    upload_document_to_library, list_agents, delete_agent,
    create_websearch_agent, create_code_agent, create_image_agent
)
import io
import csv

logger = logging.getLogger(__name__)

# --- State Definitions ---
# Add new states for the ban/unban flow and library management
SELECTING_ACTION, \
GETTING_USER_ID_FOR_INFO, \
GETTING_USER_ID_FOR_PLAN, \
SELECTING_PLAN, \
GETTING_DURATION, \
GETTING_BROADCAST_MESSAGE, \
GETTING_USER_ID_FOR_BAN, \
CONFIRMING_BAN, \
LIBRARY_MANAGEMENT, \
GETTING_LIBRARY_NAME, \
GETTING_LIBRARY_DESCRIPTION, \
CONFIRMING_LIBRARY_DELETE, \
AGENT_MANAGEMENT = range(13)


# --- Helper to display the main admin menu ---
async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("👤 Get User Info", callback_data='admin:info_user')],
        [InlineKeyboardButton("⭐️ Set User Plan", callback_data='admin:set_plan')],
        [InlineKeyboardButton("📚 Document Library", callback_data='admin:library_manage')],
        [InlineKeyboardButton("🤖 Agent Management", callback_data='admin:agent_manage')],
        [InlineKeyboardButton("🔨 Manage User (Ban/Unban)", callback_data='admin:manage_user')],
        [InlineKeyboardButton("📊 Bot Statistics", callback_data='admin:stats')],
        [InlineKeyboardButton("📢 Broadcast Message", callback_data='admin:broadcast')],
        [InlineKeyboardButton("ექსპორტი მონაცემთა (CSV)", callback_data='admin:export')],
        [InlineKeyboardButton("❌ Close Menu", callback_data='admin:cancel')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    menu_text = "👑 *Admin Control Panel*\n\nPlease choose an action:"
    if update.callback_query:
        await update.callback_query.edit_message_text(menu_text, reply_markup=reply_markup, parse_mode='Markdown')
    elif update.message:
        await update.message.reply_text(menu_text, reply_markup=reply_markup, parse_mode='Markdown')

@admin_only
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await show_admin_menu(update, context)
    return SELECTING_ACTION

# --- Flow 1: Get User Info ---
async def ask_for_user_id_for_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("Okay, please send me the Telegram User ID of the user you want to check.")
    return GETTING_USER_ID_FOR_INFO

async def get_and_show_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        if update.message:
            await update.message.reply_text("Please send a valid user ID.")
        return GETTING_USER_ID_FOR_INFO
    
    try:
        user_id = int(update.message.text)
        user = get_user_by_id(user_id)
        if user:
            expiry_date_str = "Never"
            if user['subscription_expiry_date']:
                expiry_date_str = datetime.fromisoformat(user['subscription_expiry_date']).strftime("%Y-%m-%d %H:%M")

            # Escape all the dynamic parts of the message
            safe_name = escape_markdown(user['first_name'] or "N/A", version=2)
            safe_username = escape_markdown(user['username'] or "N/A", version=2)
            safe_plan = escape_markdown(user['plan_name'].upper(), version=2)
            safe_model = escape_markdown(user['current_model'], version=2)

            info_text = (
                f"👤 *User Info for `{user['user_id']}`*\n\n"
                f"**Name:** {safe_name}\n"
                f"**Username:** @{safe_username}\n"
                f"**Plan:** `{safe_plan}`\n"
                f"**Current Model:** `{safe_model}`\n" # <-- NEW and safe
                f"**Expires:** `{expiry_date_str}`\n"
                f"**Images Used Today:** {user['daily_images_used']}"
            )
            if update.message:
                await update.message.reply_text(info_text, parse_mode='MarkdownV2')
        else:
            if update.message:
                await update.message.reply_text(f"❓ User with ID {user_id} not found.")
    except ValueError:
        if update.message:
            await update.message.reply_text("That doesn't look like a valid User ID. Please send numbers only.")
        return GETTING_USER_ID_FOR_INFO

    await show_admin_menu(update, context)
    return SELECTING_ACTION

# --- Flow 2: Set User Plan ---
async def ask_for_user_id_for_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("Okay, please send me the Telegram User ID of the user you want to modify.")
    return GETTING_USER_ID_FOR_PLAN

async def ask_for_plan_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        if update.message:
            await update.message.reply_text("Please send a valid user ID.")
        return GETTING_USER_ID_FOR_PLAN
    
    try:
        user_id = int(update.message.text)
        if context.user_data is not None:
            context.user_data['target_user_id'] = user_id
        keyboard = [[InlineKeyboardButton(plan.upper(), callback_data=f"set_plan:{plan}")] for plan in PLANS.keys()]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.message:
            await update.message.reply_text(f"Great. Which plan should user `{user_id}` be on?", reply_markup=reply_markup, parse_mode='Markdown')
        return SELECTING_PLAN
    except ValueError:
        if update.message:
            await update.message.reply_text("That doesn't look like a valid User ID. Please send numbers only.")
        return GETTING_USER_ID_FOR_PLAN

async def ask_for_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not query.data:
        return SELECTING_PLAN
    
    await query.answer()
    plan_name = query.data.split(":")[1]
    if context.user_data is not None:
        context.user_data['target_plan_name'] = plan_name
    if plan_name == 'free':
        if context.user_data and 'target_user_id' in context.user_data:
            user_id = context.user_data['target_user_id']
            set_user_plan(user_id, 'free')
            await query.edit_message_text(f"✅ Success! User `{user_id}` has been moved to the 'free' plan.", parse_mode='Markdown')
        await show_admin_menu(update, context)
        return SELECTING_ACTION
    await query.edit_message_text(f"Okay, setting plan to '{plan_name}'. For how many days should this subscription last? (Send a number)")
    return GETTING_DURATION

async def set_plan_with_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        if update.message:
            await update.message.reply_text("Please send a valid number.")
        return GETTING_DURATION
    
    try:
        duration_days = int(update.message.text)
        user_id = context.user_data.get('target_user_id') if context.user_data else None
        plan_name = context.user_data.get('target_plan_name') if context.user_data else None
        if not user_id or not plan_name:
            if update.message:
                await update.message.reply_text("An error occurred, data was lost. Please start over.")
            return ConversationHandler.END
        success = set_user_plan(user_id, plan_name, duration_days)
        if success:
            safe_plan_name = escape_markdown(plan_name, version=2)
            if update.message:
                await update.message.reply_text(f"✅ Success\\! User `{user_id}` now has the '{safe_plan_name}' plan for {duration_days} days\\.", parse_mode='MarkdownV2')
        else:
            if update.message:
                await update.message.reply_text(f"❌ Failed to set plan\\. Make sure the user ID `{user_id}` exists\\.", parse_mode='MarkdownV2')
    except ValueError:
        if update.message:
            await update.message.reply_text("That is not a valid number\\. Please send the number of days\\.", parse_mode='MarkdownV2')
        return GETTING_DURATION
    if context.user_data:
        for key in ['target_user_id', 'target_plan_name']:
            if key in context.user_data: del context.user_data[key]
    await show_admin_menu(update, context)
    return SELECTING_ACTION

# --- Flow 3: Broadcast Message ---
async def ask_for_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("Okay, please send the message you want to broadcast to all users. Standard markdown is supported.")
    return GETTING_BROADCAST_MESSAGE

# --- NEW: Flow for Ban/Unban ---
async def ask_for_user_id_for_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("Please send the User ID of the user you want to ban or unban.")
    return GETTING_USER_ID_FOR_BAN

async def show_ban_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        if update.message:
            await update.message.reply_text("Please send a valid user ID.")
        return GETTING_USER_ID_FOR_BAN
    
    try:
        user_id = int(update.message.text)
        user = get_user_by_id(user_id)
        if not user:
            if update.message:
                await update.message.reply_text(f"User with ID {user_id} not found.")
            return SELECTING_ACTION
        
        if context.user_data is not None:
            context.user_data['target_user_id'] = user_id
        status = "Banned" if user['is_banned'] else "Active"
        
        keyboard = [
            [InlineKeyboardButton("🚫 Ban User", callback_data='admin:ban_confirm:1')],
            [InlineKeyboardButton("✅ Unban User", callback_data='admin:ban_confirm:0')],
            [InlineKeyboardButton("⬅️ Cancel", callback_data='admin:cancel_ban')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.message:
            await update.message.reply_text(f"User: `{user_id}`\nCurrent Status: *{status}*\n\nWhat would you like to do?", reply_markup=reply_markup, parse_mode='Markdown')
        return CONFIRMING_BAN

    except ValueError:
        if update.message:
            await update.message.reply_text("Invalid User ID. Please send numbers only.")
        return GETTING_USER_ID_FOR_BAN

async def set_ban_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not query.data:
        return CONFIRMING_BAN
    
    await query.answer()
    
    user_id = context.user_data.get('target_user_id') if context.user_data else None
    should_ban = int(query.data.split(':')[-1])
    
    if user_id is not None:
        set_user_ban_status(user_id, bool(should_ban))
        action_text = "banned" if should_ban else "unbanned"
        await query.edit_message_text(f"✅ Success! User `{user_id}` has been {action_text}.")
    
    if context.user_data and 'target_user_id' in context.user_data:
        del context.user_data['target_user_id']
    await show_admin_menu(update, context)
    return SELECTING_ACTION

async def cancel_ban_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if context.user_data and 'target_user_id' in context.user_data:
        del context.user_data['target_user_id']
    await show_admin_menu(update, context)
    return SELECTING_ACTION

# --- NEW: Handler for showing statistics ---
async def show_bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return SELECTING_ACTION
    
    await query.answer("Gathering stats...")

    stats = get_bot_statistics()
    
    # Format plan counts for display
    plan_text = ""
    for plan, count in stats['users_per_plan'].items():
        plan_text += f"  `›` {escape_markdown(plan.title(), version=2)}: {count}\n"

    stats_text = (
        f"📊 *Bot Statistics Dashboard*\n\n"
        f"👤 *User Base*\n"
        f"  `›` Total Users: {stats['total_users']}\n"
        f"  `›` Active Users: {stats['active_users']}\n"
        f"  `›` Inactive \\(Blocked\\): {stats['inactive_users']}\n"
        f"  `›` Banned Users: {stats['banned_users']}\n\n"
        f"⭐️ *Plan Distribution*\n{plan_text}\n"
        f"🤖 *Usage Overview*\n"
        f"  `›` Tokens \\(Today\\): {stats['tokens_today']:,}\n"
        f"  `›` Tokens \\(7 days\\): {stats['tokens_past_7_days']:,}\n"
        f"  `›` Images \\(Today\\): {stats['images_today']:,}\n"
        f"  `›` Images \\(7 days\\): {stats['images_past_7_days']:,}\n\n"
        f"🧠 *Most Popular Model*\n"
        f"  `›` {escape_markdown(stats['most_used_model'], version=2)}"
    )
    keyboard = [[InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data='admin:main_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    return SELECTING_ACTION # Stay in the admin menu

async def back_to_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_admin_menu(update, context)
    return SELECTING_ACTION

# --- NEW: Handler for exporting data ---
async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return SELECTING_ACTION
    
    await query.answer("Generating export file...")

    # 1. Get Summary Stats
    summary_stats = get_bot_statistics()
    # 2. Get Full User List
    user_list = get_full_user_data_for_export()
    
    # 3. Create a CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write summary
    writer.writerow(["Nebula AI Bot - Data Export", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    writer.writerow([]) # Spacer
    writer.writerow(["Metric", "Value"])
    for key, value in summary_stats.items():
        if not isinstance(value, dict):
             writer.writerow([key.replace('_', ' ').title(), value])
    writer.writerow([]) # Spacer
    
    # Write user list
    writer.writerow(["User ID", "First Name", "Username", "Plan", "Is Banned", "Is Active", "Last Seen"])
    for user in user_list:
        writer.writerow([user['user_id'], user['first_name'], user['username'], user['plan_name'],
                         "Yes" if user['is_banned'] else "No", 
                         "Yes" if user['is_active'] else "No",
                         user['last_seen']])
    
    output.seek(0)
    
    # 4. Send the file
    csv_bytes = output.getvalue().encode('utf-8')
    file_to_send = InputFile(csv_bytes, filename=f"nebula_ai_export_{datetime.now().strftime('%Y%m%d')}.csv")
    if update.effective_chat:
        await context.bot.send_document(chat_id=update.effective_chat.id, document=file_to_send,
                                    caption="Here is your requested data export.")

    # Since we sent a new message, we just edit the original button message to confirm.
    await query.edit_message_text("✅ Export file sent successfully. Returning to main menu.")
    await asyncio.sleep(1)
    await show_admin_menu(update, context)
    return SELECTING_ACTION

# --- Library Management Handlers ---
async def library_management_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle library management commands"""
    query = update.callback_query
    if not query:
        return SELECTING_ACTION
    
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📚 List Libraries", callback_data='library:list')],
        [InlineKeyboardButton("📁 Create Library", callback_data='library:create')],
        [InlineKeyboardButton("📄 Upload Document", callback_data='library:upload_doc')],
        [InlineKeyboardButton("🗑️ Delete Library", callback_data='library:delete')],
        [InlineKeyboardButton("⬅️ Back", callback_data='admin:main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("📚 Document Library Management", reply_markup=reply_markup)
    return LIBRARY_MANAGEMENT

async def list_libraries_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """List all available libraries"""
    query = update.callback_query
    if not query:
        return LIBRARY_MANAGEMENT
    
    await query.answer("Fetching libraries...")
    
    try:
        libraries = await asyncio.to_thread(list_libraries)
        
        if not libraries:
            text = "📚 *Library Status*\n\nNo libraries found\\. Create one to get started\\."
        else:
            text = f"📚 *Found {len(libraries)} Libraries*\n\n"
            for i, lib in enumerate(libraries, 1):
                # Get document count for each library
                try:
                    docs = await asyncio.to_thread(list_library_documents, lib.id)
                    doc_count = len(docs)
                except:
                    doc_count = "?"
                
                lib_name = escape_markdown(lib.name, version=2)
                lib_desc = escape_markdown(lib.description or "No description", version=2)
                text += f"**{i}\\. {lib_name}**\n"
                text += f"   📄 Documents: {doc_count}\n"
                text += f"   📝 Description: {lib_desc}\n"
                text += f"   🆔 ID: `{lib.id}`\n\n"
        
        keyboard = [[InlineKeyboardButton("⬅️ Back to Library Menu", callback_data='admin:library_manage')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')
        
    except Exception as e:
        logger.error(f"Failed to list libraries: {e}")
        await query.edit_message_text(
            f"❌ Error fetching libraries: {escape_markdown(str(e), version=2)}",
            parse_mode='MarkdownV2'
        )
    
    return LIBRARY_MANAGEMENT

async def ask_for_library_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask for library name to create"""
    query = update.callback_query
    if not query:
        return LIBRARY_MANAGEMENT
    
    await query.answer()
    await query.edit_message_text("📁 *Create New Library*\n\nPlease send the name for the new library:", parse_mode='Markdown')
    return GETTING_LIBRARY_NAME

async def ask_for_library_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Get library name and ask for description"""
    if not update.message or not update.message.text:
        if update.message:
            await update.message.reply_text("Please send a valid library name.")
        return GETTING_LIBRARY_NAME
    
    library_name = update.message.text.strip()
    if context.user_data is not None:
        context.user_data['new_library_name'] = library_name
    
    if update.message:
        await update.message.reply_text(
            f"📝 *Library Name*: `{library_name}`\n\n"
            f"Now please send a description for this library (or send 'skip' to create without description):",
            parse_mode='Markdown'
        )
    return GETTING_LIBRARY_DESCRIPTION

async def create_new_library(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Create the library with name and description"""
    if not update.message or not update.message.text:
        if update.message:
            await update.message.reply_text("Please send a valid description or 'skip'.")
        return GETTING_LIBRARY_DESCRIPTION
    
    description = update.message.text.strip()
    if description.lower() == 'skip':
        description = ""
    
    library_name = context.user_data.get('new_library_name', 'Unnamed Library') if context.user_data else 'Unnamed Library'
    
    try:
        if update.message:
            await update.message.reply_text("📁 Creating library...")
        library = await asyncio.to_thread(create_library, library_name, description)
        
        safe_name = escape_markdown(library_name, version=2)
        if update.message:
            await update.message.reply_text(
                f"✅ *Library Created Successfully\\!*\n\n"
                f"**Name:** {safe_name}\n"
                f"**ID:** `{library.id}`\n"
                f"**Description:** {escape_markdown(description or 'None', version=2)}",
                parse_mode='MarkdownV2'
            )
        
    except Exception as e:
        logger.error(f"Failed to create library: {e}")
        if update.message:
            await update.message.reply_text(f"❌ Error creating library: {e}")
    
    # Clean up
    if context.user_data and 'new_library_name' in context.user_data:
        del context.user_data['new_library_name']
    
    await show_admin_menu(update, context)
    return SELECTING_ACTION

async def show_delete_library_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show libraries that can be deleted"""
    query = update.callback_query
    if not query:
        return LIBRARY_MANAGEMENT
    
    await query.answer()
    
    try:
        libraries = await asyncio.to_thread(list_libraries)
        
        if not libraries:
            await query.edit_message_text(
                "📚 No libraries found to delete.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data='admin:library_manage')
                ]])
            )
            return LIBRARY_MANAGEMENT
        
        keyboard = []
        for lib in libraries:
            safe_name = lib.name[:30] + "..." if len(lib.name) > 30 else lib.name
            keyboard.append([InlineKeyboardButton(
                f"🗑️ {safe_name}",
                callback_data=f'library:confirm_delete:{lib.id}'
            )])
        
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data='admin:library_manage')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🗑️ *Delete Library*\n\n⚠️ **Warning:** This will permanently delete the library and all its documents!\n\nSelect a library to delete:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Failed to list libraries for deletion: {e}")
        await query.edit_message_text(f"❌ Error: {e}")
    
    return CONFIRMING_LIBRARY_DELETE

async def confirm_library_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Confirm and execute library deletion"""
    query = update.callback_query
    if not query or not query.data:
        return CONFIRMING_LIBRARY_DELETE
    
    await query.answer()
    
    library_id = query.data.split(':')[-1]
    
    try:
        # Get library info before deletion
        libraries = await asyncio.to_thread(list_libraries)
        target_lib = next((lib for lib in libraries if lib.id == library_id), None)
        
        if not target_lib:
            await query.edit_message_text("❌ Library not found.")
            await show_admin_menu(update, context)
            return SELECTING_ACTION
        
        # Delete the library
        await asyncio.to_thread(delete_library, library_id)
        
        safe_name = escape_markdown(target_lib.name, version=2)
        await query.edit_message_text(
            f"✅ *Library Deleted*\n\n**Name:** {safe_name}\n**ID:** `{library_id}`",
            parse_mode='MarkdownV2'
        )
        
    except Exception as e:
        logger.error(f"Failed to delete library: {e}")
        await query.edit_message_text(f"❌ Error deleting library: {e}")
    
    await asyncio.sleep(2)
    await show_admin_menu(update, context)
    return SELECTING_ACTION

# --- Agent Management Handlers ---
async def agent_management_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle agent management commands"""
    query = update.callback_query
    if not query:
        return SELECTING_ACTION
    
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🤖 List Agents", callback_data='agent:list')],
        [InlineKeyboardButton("🌐 Create Web Search Agent", callback_data='agent:create_web')],
        [InlineKeyboardButton("💻 Create Code Agent", callback_data='agent:create_code')],
        [InlineKeyboardButton("🖼️ Create Image Agent", callback_data='agent:create_image')],
        [InlineKeyboardButton("🗑️ Delete Agent", callback_data='agent:delete')],
        [InlineKeyboardButton("⬅️ Back", callback_data='admin:main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("🤖 Agent Management", reply_markup=reply_markup)
    return AGENT_MANAGEMENT

async def list_agents_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """List all available agents"""
    query = update.callback_query
    if not query:
        return AGENT_MANAGEMENT
    
    await query.answer("Fetching agents...")
    
    try:
        agents = await asyncio.to_thread(list_agents)
        
        if not agents:
            text = "🤖 *Agent Status*\n\nNo agents found\\."
        else:
            text = f"🤖 *Found {len(agents)} Agents*\n\n"
            for i, agent in enumerate(agents, 1):
                agent_name = escape_markdown(getattr(agent, 'name', 'Unknown'), version=2)
                agent_desc = escape_markdown(getattr(agent, 'description', None) or "No description", version=2)
                text += f"**{i}\\. {agent_name}**\n"
                text += f"   📝 Description: {agent_desc}\n"
                text += f"   🆔 ID: `{agent.id}`\n\n"
        
        keyboard = [[InlineKeyboardButton("⬅️ Back to Agent Menu", callback_data='admin:agent_manage')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')
        
    except Exception as e:
        logger.error(f"Failed to list agents: {e}")
        await query.edit_message_text(f"❌ Error fetching agents: {e}")
    
    return AGENT_MANAGEMENT

async def create_web_search_agent_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Create a web search agent"""
    query = update.callback_query
    if not query:
        return AGENT_MANAGEMENT
    
    await query.answer()
    
    try:
        await query.edit_message_text("🌐 Creating web search agent...")
        agent = await asyncio.to_thread(create_websearch_agent)
        
        await query.edit_message_text(
            f"✅ *Web Search Agent Created*\n\n"
            f"**Name:** {escape_markdown(getattr(agent, 'name', 'Unknown'), version=2)}\n"
            f"**ID:** `{getattr(agent, 'id', 'Unknown')}`\n"
            f"**Description:** {escape_markdown(getattr(agent, 'description', None) or 'No description', version=2)}",
            parse_mode='MarkdownV2'
        )
        
    except Exception as e:
        logger.error(f"Failed to create web search agent: {e}")
        await query.edit_message_text(f"❌ Error creating web search agent: {e}")
    
    await asyncio.sleep(2)
    await show_admin_menu(update, context)
    return SELECTING_ACTION

async def create_code_agent_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Create a code interpreter agent"""
    query = update.callback_query
    if not query:
        return AGENT_MANAGEMENT
    
    await query.answer()
    
    try:
        await query.edit_message_text("💻 Creating code interpreter agent...")
        agent = await asyncio.to_thread(create_code_agent)
        
        await query.edit_message_text(
            f"✅ *Code Interpreter Agent Created*\n\n"
            f"**Name:** {escape_markdown(getattr(agent, 'name', 'Unknown'), version=2)}\n"
            f"**ID:** `{getattr(agent, 'id', 'Unknown')}`\n"
            f"**Description:** {escape_markdown(getattr(agent, 'description', None) or 'No description', version=2)}",
            parse_mode='MarkdownV2'
        )
        
    except Exception as e:
        logger.error(f"Failed to create code interpreter agent: {e}")
        await query.edit_message_text(f"❌ Error creating code interpreter agent: {e}")
    
    await asyncio.sleep(2)
    await show_admin_menu(update, context)
    return SELECTING_ACTION

async def create_image_agent_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Create an image generation agent"""
    query = update.callback_query
    if not query:
        return AGENT_MANAGEMENT
    
    await query.answer()
    
    try:
        await query.edit_message_text("🖼️ Creating image generation agent...")
        agent = await asyncio.to_thread(create_image_agent)
        
        await query.edit_message_text(
            f"✅ *Image Generation Agent Created*\n\n"
            f"**Name:** {escape_markdown(getattr(agent, 'name', 'Unknown'), version=2)}\n"
            f"**ID:** `{getattr(agent, 'id', 'Unknown')}`\n"
            f"**Description:** {escape_markdown(getattr(agent, 'description', None) or 'No description', version=2)}",
            parse_mode='MarkdownV2'
        )
        
    except Exception as e:
        logger.error(f"Failed to create image generation agent: {e}")
        await query.edit_message_text(f"❌ Error creating image generation agent: {e}")
    
    await asyncio.sleep(2)
    await show_admin_menu(update, context)
    return SELECTING_ACTION

async def show_delete_agent_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show agents that can be deleted"""
    query = update.callback_query
    if not query:
        return AGENT_MANAGEMENT
    
    await query.answer()
    
    try:
        agents = await asyncio.to_thread(list_agents)
        
        if not agents:
            await query.edit_message_text(
                "🤖 No agents found to delete.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data='admin:agent_manage')
                ]])
            )
            return AGENT_MANAGEMENT
        
        keyboard = []
        for agent in agents:
            agent_name = getattr(agent, 'name', 'Unknown')
            agent_id = getattr(agent, 'id', 'unknown')
            safe_name = agent_name[:30] + "..." if len(agent_name) > 30 else agent_name
            keyboard.append([InlineKeyboardButton(
                f"🗑️ {safe_name}",
                callback_data=f'agent:confirm_delete:{agent_id}'
            )])
        
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data='admin:agent_manage')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🗑️ *Delete Agent*\n\n⚠️ **Warning:** This will permanently delete the agent!\n\nSelect an agent to delete:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Failed to list agents for deletion: {e}")
        await query.edit_message_text(f"❌ Error: {e}")
    
    return AGENT_MANAGEMENT

async def confirm_agent_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Confirm and execute agent deletion"""
    query = update.callback_query
    if not query or not query.data:
        return AGENT_MANAGEMENT
    
    await query.answer()
    
    agent_id = query.data.split(':')[-1]
    
    try:
        # Get agent info before deletion
        agents = await asyncio.to_thread(list_agents)
        target_agent = next((agent for agent in agents if getattr(agent, 'id', None) == agent_id), None)
        
        if not target_agent:
            await query.edit_message_text("❌ Agent not found.")
            await show_admin_menu(update, context)
            return SELECTING_ACTION
        
        # Delete the agent
        await asyncio.to_thread(delete_agent, agent_id)
        
        safe_name = escape_markdown(getattr(target_agent, 'name', 'Unknown'), version=2)
        await query.edit_message_text(
            f"✅ *Agent Deleted*\n\n**Name:** {safe_name}\n**ID:** `{agent_id}`",
            parse_mode='MarkdownV2'
        )
        
    except Exception as e:
        logger.error(f"Failed to delete agent: {e}")
        await query.edit_message_text(f"❌ Error deleting agent: {e}")
    
    await asyncio.sleep(2)
    await show_admin_menu(update, context)
    return SELECTING_ACTION


# --- MODIFIED: Update Broadcast to track inactive users ---
async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        if update.message:
            await update.message.reply_text("Please send a valid broadcast message.")
        return GETTING_BROADCAST_MESSAGE
    
    broadcast_message = update.message.text
    await update.message.reply_text("Sending broadcast... This may take a moment.")
    user_ids = get_all_user_ids()
    success_count, failure_count = 0, 0
    for user_id in user_ids:
        try:
            if broadcast_message:
                await context.bot.send_message(chat_id=user_id, text=broadcast_message, parse_mode='Markdown')
            success_count += 1
            # If a message succeeds, we know they are active
            set_user_active_status(user_id, True) 
        except Forbidden:
            # This user has blocked the bot. Mark them as inactive.
            set_user_active_status(user_id, False)
            failure_count += 1
        except BadRequest:
            # Other errors (e.g., chat not found), also likely inactive
            set_user_active_status(user_id, False)
            failure_count += 1
        await asyncio.sleep(0.1) # Rate limit
    
    report_text = f"📢 *Broadcast Complete!*\n\n✅ Sent successfully to: {success_count} users\n❌ Failed for: {failure_count} users (marked as inactive)"
    if update.message:
        await update.message.reply_text(report_text, parse_mode='Markdown')
    await show_admin_menu(update, context)
    return SELECTING_ACTION

# --- Exit Point ---
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handles both command-based and callback-based cancellations.
    """
    query = update.callback_query
    
    # If the cancel was triggered by a button press (a callback query)
    if query:
        await query.answer()
        await query.edit_message_text("Admin panel closed.")
    # If the cancel was triggered by the /cancel command (a message)
    elif update.message:
        await update.message.reply_text("Admin panel closed.")
        
    # Clean up any temporary data stored in context
    if context.user_data:
        for key in ['target_user_id', 'target_plan_name']:
            if key in context.user_data:
                del context.user_data[key]
            
    return ConversationHandler.END

# --- The Master Conversation Handler ---
admin_conversation_handler = ConversationHandler(
    entry_points=[CommandHandler("admin", admin_command)],
    states={
        SELECTING_ACTION: [
            CallbackQueryHandler(ask_for_user_id_for_info, pattern='^admin:info_user$'),
            CallbackQueryHandler(ask_for_user_id_for_plan, pattern='^admin:set_plan$'),
            CallbackQueryHandler(ask_for_broadcast_message, pattern='^admin:broadcast$'),
            CallbackQueryHandler(show_bot_stats, pattern='^admin:stats$'),
            CallbackQueryHandler(export_data, pattern='^admin:export$'),
            CallbackQueryHandler(ask_for_user_id_for_ban, pattern='^admin:manage_user$'),
            CallbackQueryHandler(library_management_handler, pattern='^admin:library_manage$'),
            CallbackQueryHandler(agent_management_handler, pattern='^admin:agent_manage$'),
            CallbackQueryHandler(back_to_admin_menu, pattern='^admin:main_menu$'),
            CallbackQueryHandler(cancel_conversation, pattern='^admin:cancel$'),
        ],
        GETTING_USER_ID_FOR_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_and_show_user_info)],
        GETTING_USER_ID_FOR_PLAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_for_plan_name)],
        SELECTING_PLAN: [CallbackQueryHandler(ask_for_duration, pattern='^set_plan:')],
        GETTING_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_plan_with_duration)],
        GETTING_BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_broadcast)],
        GETTING_USER_ID_FOR_BAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, show_ban_options)],
        CONFIRMING_BAN: [
            CallbackQueryHandler(set_ban_status, pattern='^admin:ban_confirm:'),
            CallbackQueryHandler(cancel_ban_flow, pattern='^admin:cancel_ban$')
        ],
        LIBRARY_MANAGEMENT: [
            CallbackQueryHandler(list_libraries_handler, pattern='^library:list$'),
            CallbackQueryHandler(ask_for_library_name, pattern='^library:create$'),
            CallbackQueryHandler(show_delete_library_menu, pattern='^library:delete$'),
            CallbackQueryHandler(library_management_handler, pattern='^admin:library_manage$'),
        ],
        GETTING_LIBRARY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_for_library_description)],
        GETTING_LIBRARY_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_new_library)],
        CONFIRMING_LIBRARY_DELETE: [
            CallbackQueryHandler(confirm_library_deletion, pattern='^library:confirm_delete:'),
            CallbackQueryHandler(library_management_handler, pattern='^admin:library_manage$')
        ],
        AGENT_MANAGEMENT: [
            CallbackQueryHandler(list_agents_handler, pattern='^agent:list$'),
            CallbackQueryHandler(create_web_search_agent_handler, pattern='^agent:create_web$'),
            CallbackQueryHandler(create_code_agent_handler, pattern='^agent:create_code$'),
            CallbackQueryHandler(create_image_agent_handler, pattern='^agent:create_image$'),
            CallbackQueryHandler(show_delete_agent_menu, pattern='^agent:delete$'),
            CallbackQueryHandler(confirm_agent_deletion, pattern='^agent:confirm_delete:'),
            CallbackQueryHandler(agent_management_handler, pattern='^admin:agent_manage$'),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel_conversation)],
    allow_reentry=True
) 