# fast_main.py (Version 2.3: Polished UX)

import logging
import os
import asyncio
import time
import re
from datetime import datetime
from dataclasses import dataclass
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, ConversationHandler
from telegram.request import HTTPXRequest
from telegram.helpers import escape_markdown

from fast_config import TELEGRAM_BOT_TOKEN, ADMIN_CONTACT_USERNAME
from mistral_client_official import send_prompt as mistral_send_prompt
from mistral_client_official import transcribe_audio
from mistral_client_official import (
    query_document_library, create_document_library_agent, 
    list_libraries, create_websearch_agent, create_code_agent, 
    create_image_agent, list_agents, create_library, upload_document_to_library
)
from typing import List, Union, Optional
from database_manager import (
    initialize_database, get_or_create_user, check_user_limits, 
    increment_image_usage, update_token_usage, get_user_functions
)
from conversation_handlers import admin_conversation_handler
from conversation_manager import get_conversation_history, add_to_conversation_history, clear_user_context, get_context_stats
from user_menu_handlers import (
    start_command_handler,
    account_command_handler,
    create_purchase_ticket_handler,
    settings_menu_handler,
    show_paginated_model_options,
    set_new_model_handler,
    help_menu_handler,            
    help_images_handler,          
    help_features_handler,        
    help_rag_handler, 
    modes_menu_handler,           # <-- NEW
    toggle_mode_handler,          # <-- NEW  
    turn_off_all_modes_handler,   # <-- NEW
    image_cancel_handler,         # <-- NEW
    context_menu_handler,         # <-- NEW
    context_reset_handler,        # <-- NEW
    context_new_convo_handler,    # <-- NEW
    context_details_handler,      # <-- NEW
    report_issue_handler,         # <-- NEW
    start_report_handler,         # <-- NEW
    cancel_report_handler,        # <-- NEW
    start_tuning_handler,
    IMAGE_SUPPORTED_MODELS
)
from settings_handler import (
    SELECTING_SETTING, GETTING_SYSTEM_PROMPT, GETTING_TEMPERATURE, GETTING_TOP_P, GETTING_MAX_TOKENS,
    ask_for_system_prompt, save_system_prompt,
    ask_for_temperature, save_temperature,
    ask_for_top_p, save_top_p,
    ask_for_max_tokens, save_max_tokens,
    end_tuning_conversation, cancel_setting
)
from function_calling_handler import (
    SELECTING_ACTION as FC_SELECTING_ACTION,
    GETTING_NAME as FC_GETTING_NAME,
    GETTING_DESCRIPTION as FC_GETTING_DESCRIPTION,
    GETTING_SCHEMA as FC_GETTING_SCHEMA,
    CONFIRM_DELETE as FC_CONFIRM_DELETE,
    functions_menu,
    ask_for_name, get_name,
    get_description, get_schema_and_save,
    show_delete_menu, confirm_delete_function,
    back_to_settings, cancel_flow
)
import json

# --- Setup ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Increase worker count if you want to handle more simultaneous requests
WORKER_COUNT = 8

# =================================================================
# TEXT FORMATTING HELPER FUNCTIONS
# =================================================================

async def send_formatted_message(message, text: str, parse_mode_preference: str = 'Markdown'):
    """
    Safely send a message with proper formatting, handling code blocks and markdown.
    Falls back to plain text if formatting fails.
    """
    if not text.strip():
        return
    
    # Check if text contains markdown elements
    has_code_blocks = '```' in text
    has_markdown = ('**' in text or '*' in text or '_' in text or 
                   '##' in text or '[' in text or '](' in text)
    
    # For AI responses with markdown, try regular Markdown first (works best for **bold**, ### headers, [links](url))
    if has_markdown or has_code_blocks:
        try:
            await message.reply_text(text, parse_mode='Markdown')
            return
        except Exception as e:
            logger.warning(f"Markdown formatting failed: {e}")
            # If markdown fails, try to clean up common problematic characters
            cleaned_text = text.replace('_', '\\_').replace('*', '\\*')
            try:
                await message.reply_text(cleaned_text, parse_mode='Markdown')
                return
            except Exception as e2:
                logger.warning(f"Cleaned Markdown also failed: {e2}")
    
    # For interface messages that prefer MarkdownV2 (like our own bot messages)
    if parse_mode_preference == 'MarkdownV2' and not has_markdown and not has_code_blocks:
        try:
            escaped_text = escape_markdown(text, version=2)
            await message.reply_text(escaped_text, parse_mode='MarkdownV2')
            return
        except Exception as e:
            logger.warning(f"MarkdownV2 escaping failed: {e}")
    
    # Fallback to plain text
    await message.reply_text(text)

async def send_long_message(message, text: str, max_length: int = 4096):
    """
    Send a long message by splitting it properly while preserving formatting.
    """
    if len(text) <= max_length:
        await send_formatted_message(message, text)
        return
    
    # Split long messages while trying to preserve code blocks
    parts = []
    current_part = ""
    in_code_block = False
    
    lines = text.split('\n')
    for line in lines:
        if line.startswith('```'):
            in_code_block = not in_code_block
        
        if len(current_part + line + '\n') > max_length and current_part:
            if in_code_block:
                # Close code block for this part
                parts.append(current_part + '\n```')
                current_part = '```\n' + line + '\n'
            else:
                parts.append(current_part.rstrip())
                current_part = line + '\n'
        else:
            current_part += line + '\n'
    
    if current_part.strip():
        parts.append(current_part.rstrip())
    
    # Send each part
    for part in parts:
        await send_formatted_message(message, part)

# A simple data structure to hold a job's information.
@dataclass
class Job:
    update: Update
    prompt: str
    tools: List[Union[str, dict]]

# --- Core Component (Official Mistral API) ---
logger.info("Using Official Mistral API Client...")

# --- Worker Logic ---
async def worker(name: str, queue: asyncio.Queue):
    """Worker now uses the user's selected model for each job."""
    logger.info(f"Worker {name} started.")
    while True:
        job = await queue.get()
        user_id = job.update.effective_user.id
        
        # --- NEW: Get the full user record, including the model ---
        user = get_or_create_user(job.update.effective_user)
        active_model = user['current_model']
        temperature = user['temperature']
        top_p = user['top_p']
        system_prompt = user['system_prompt']
        max_tokens = user['max_tokens']
        
        logger.info(f"Worker {name} picked up job for user {user_id} (Model: {active_model}): '{job.prompt[:30]}...'")

        try:
            # Enhanced error handling with retry mechanism
            max_retries = 3
            retry_count = 0
            result = None
            
            # Initialize variables outside the loop
            prompt_to_send = job.prompt
            context_reset_message = None
            
            while retry_count < max_retries and result is None:
                try:
                    history = get_conversation_history(user_id)
                    
                    # --- Enhanced: Add user prompts to history with smart context management ---
                    if "image_generation" not in job.tools:
                        context_reset_message = add_to_conversation_history(user_id, "user", job.prompt)

                    # --- NEW: Prepend text to image prompts to ensure tool use ---
                    if "image_generation" in job.tools:
                        prompt_to_send = f"Generate a high-quality, detailed image of: {job.prompt}"
                        logger.info(f"Modified image prompt for API: '{prompt_to_send}'")

                    # Pass the user's chosen model and parameters to the official client
                    result = await asyncio.to_thread(
                        mistral_send_prompt, 
                        prompt_to_send, # Use the potentially modified prompt
                        history=history, 
                        tools=job.tools,
                        model=active_model,
                        temperature=temperature,
                        top_p=top_p,
                        system_prompt=system_prompt,
                        max_tokens=max_tokens
                    )
                    
                except Exception as api_error:
                    retry_count += 1
                    if retry_count < max_retries:
                        logger.warning(f"API call failed (attempt {retry_count}/{max_retries}): {api_error}")
                        await asyncio.sleep(2 ** retry_count)  # Exponential backoff
                        if job.update.message:
                            await job.update.message.reply_text(
                                f"🔄 Retrying... (attempt {retry_count + 1}/{max_retries})",
                                parse_mode='Markdown'
                            )
                    else:
                        raise api_error

            if result:
                if isinstance(result, str) and result.endswith('.png'):
                    increment_image_usage(user_id)
                    try:
                        with open(result, 'rb') as photo: await job.update.message.reply_photo(photo)
                    finally: os.remove(result)
                
                elif isinstance(result, dict) and result.get("type") == "tool_calls":
                    response_text = "🛠️ *Function Call Requested*\\n\\n"
                    response_text += "The AI wants to call the following function(s)\\. Please execute them and provide the results\\.\\n\\n"
                    
                    for call in result.get("content", []):
                        func_name = call.get("function", {}).get("name")
                        func_args = call.get("function", {}).get("arguments")
                        response_text += f"**Function:** `{escape_markdown(func_name, version=2)}`\\n"
                        response_text += f"**Arguments:**\\n```json\\n{func_args}\\n```\\n\\n"
                    
                    add_to_conversation_history(user_id, "assistant", response_text)
                    await job.update.message.reply_text(response_text, parse_mode='MarkdownV2')

                elif isinstance(result, str):
                    # Token Calculation and Update, now using the correct prompt length
                    token_count = len(prompt_to_send) // 4 + len(result) // 4
                    update_token_usage(user_id, token_count)
                    
                    add_to_conversation_history(user_id, "assistant", result)
                    
                    # Send context reset notification if one occurred
                    if context_reset_message:
                        await send_formatted_message(job.update.message, context_reset_message)
                    
                    await send_long_message(job.update.message, result)
            else:
                error_text = (
                    "⚠️ **No Response Received**\n\n"
                    "The AI didn't return a response. This might be due to:\n"
                    "• Content filtering\n"
                    "• Server overload\n"
                    "• Network issues\n\n"
                    "💡 **Try**: Rephrase your request or try again in a moment."
                )
                await send_formatted_message(job.update.message, error_text, 'Markdown')
        except Exception as e:
            logger.error(f"Worker {name} encountered an error: {e}", exc_info=True)
            
            # Provide specific error messages based on error type
            error_msg = "😔 **Oops! Something went wrong.**\n\n"
            
            if "rate limit" in str(e).lower():
                error_msg += (
                    "🚦 **Rate Limit Reached**\n"
                    "Please wait a moment before trying again.\n\n"
                    "💡 **Tip**: Premium users have higher limits!"
                )
            elif "api key" in str(e).lower() or "unauthorized" in str(e).lower():
                error_msg += (
                    "🔑 **Authentication Issue**\n"
                    "There's a problem with the API connection.\n\n"
                    "🛠️ **Admin**: Please check the API key configuration."
                )
            elif "timeout" in str(e).lower():
                error_msg += (
                    "⏰ **Request Timeout**\n"
                    "The request took too long to process.\n\n"
                    "💡 **Try**: A simpler request or try again later."
                )
            elif "network" in str(e).lower() or "connection" in str(e).lower():
                error_msg += (
                    "🌐 **Connection Issue**\n"
                    "Unable to reach the AI service.\n\n"
                    "💡 **Try**: Check your internet connection and retry."
                )
            else:
                error_msg += (
                    "🔧 **Technical Issue**\n"
                    "An unexpected error occurred.\n\n"
                    "💡 **Try**: Rephrase your request or contact support if this persists."
                )
                
            if job.update.message:
                await job.update.message.reply_text(error_msg, parse_mode='Markdown')
        finally:
            queue.task_done()
            logger.info(f"Worker {name} finished job for user {user_id}.")


# --- Job Queueing Logic ---
def validate_and_sanitize_input(text: str, max_length: int = 4000) -> tuple[bool, str, str]:
    """
    Validates and sanitizes user input.
    Returns (is_valid, cleaned_text, error_message)
    """
    if not text or not text.strip():
        return False, "", "❌ **Empty Input**\n\nPlease provide some text to process."
    
    # Remove excessive whitespace
    cleaned = " ".join(text.strip().split())
    
    # Check length
    if len(cleaned) > max_length:
        return False, "", f"❌ **Input Too Long**\n\nPlease keep your message under {max_length:,} characters.\n\n**Current length**: {len(cleaned):,} characters"
    
    # Check for minimum length for certain operations
    if len(cleaned) < 3:
        return False, "", "❌ **Input Too Short**\n\nPlease provide at least 3 characters."
    
    # Basic content filtering - prevent potential abuse
    prohibited_patterns = [
        r'(?i)\b(spam|test|aaa+|111+)\b' if len(cleaned) < 20 else None,
        r'(.)\1{20,}',  # Repeated characters
    ]
    
    import re
    for pattern in prohibited_patterns:
        if pattern and re.search(pattern, cleaned):
            return False, "", "❌ **Invalid Input**\n\nPlease provide meaningful content to process."
    
    return True, cleaned, ""

async def queue_job_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, tools: List[Union[str, dict]]):
    """
    Enhanced handler with input validation and error handling.
    """
    # Safety check for update object
    if not update or not update.effective_user:
        logger.error("Invalid update object received")
        return
        
    user = get_or_create_user(update.effective_user)
    
    # The new check_user_limits is simpler and more reliable.
    can_proceed, message = check_user_limits(user, tools)
    if not can_proceed:
        if update.message:
            await update.message.reply_text(message, parse_mode='Markdown')
        logger.warning(f"Request blocked for user {user['user_id']}. Reason: Limit reached.")
        return

    # --- NEW: Fetch and add user's custom functions to the tools list ---
    custom_functions = get_user_functions(user['user_id'])
    for func in custom_functions:
        try:
            schema = json.loads(func['schema_json'])
            # Type annotation to help Pyright understand this is a valid tool
            tool_dict: dict = {
                "type": "function",
                "function": {
                    "name": func['name'],
                    "description": func['description'],
                    "parameters": schema
                }
            }
            tools.append(tool_dict)
        except json.JSONDecodeError:
            logger.warning(f"Skipping invalid function schema for user {user['user_id']} (Func ID: {func['function_id']})")


    queue = context.application.bot_data['job_queue']
    
    # Get the raw prompt
    raw_prompt = " ".join(context.args) if context.args else (update.message.text if update.message else "")
    
    # Check if we need args (only for direct /image command, not for image mode)
    if not raw_prompt:
        if 'image_generation' in tools and context.args is not None:  # This means it's a /image command
            if update.message:
                await update.message.reply_text(
                    "📝 **Image Description Required**\n\n"
                    "Please provide a description after the `/image` command.\n\n"
                    "**Example**: `/image a beautiful sunset over mountains`\n"
                    "**Tip**: Be descriptive for better results!",
                    parse_mode='Markdown'
                )
            return
        raw_prompt = "Hello"  # Fallback for other cases
    
    # Validate and sanitize the input
    is_valid, clean_prompt, error_message = validate_and_sanitize_input(raw_prompt)
    if not is_valid:
        if update.message:
            await update.message.reply_text(error_message, parse_mode='Markdown')
        logger.warning(f"Invalid input from user {user['user_id']}: {raw_prompt[:100]}...")
        return
    
    # Use the cleaned prompt
    prompt = clean_prompt
    
    # Show thinking message with mode indication
    thinking_msg = "🤔 Thinking..."
    if 'image_generation' in tools:
        thinking_msg = "🎨 Creating your image..."
    elif 'web_search' in tools and len(tools) == 1:
        thinking_msg = "🌐 Searching the web..."
    elif 'code_interpreter' in tools and len(tools) == 1:
        thinking_msg = "💻 Processing your code..."
        
    logger.info(f"Queueing prompt from user {user['user_id']} ({user['plan_name']} plan): '{prompt[:50]}...' with tools: {tools}")
    
    if update.message:
        await update.message.reply_text(thinking_msg, parse_mode='Markdown')
    await queue.put(Job(update=update, prompt=prompt, tools=tools))


# =================================================================
# ISSUE REPORTING MESSAGE HANDLER
# =================================================================

async def handle_report_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages when user is in reporting mode."""
    if not update.message or not update.message.text or not update.effective_user:
        return
    
    # Check if user is in reporting mode
    if not context.user_data or not context.user_data.get('reporting_issue'):
        return
    
    # Clear the reporting state
    del context.user_data['reporting_issue']
    
    user = update.effective_user
    report_text = update.message.text
    
    # Get admin user ID (you'll need to set this)
    ADMIN_USER_ID = 6130335505  # Replace with your actual admin user ID
    
    # Format the report message for admin
    admin_message = (
        f"📞 **NEW ISSUE REPORT**\n\n"
        f"👤 **From:** {user.first_name} (@{user.username or 'No username'})\n"
        f"🆔 **User ID:** `{user.id}`\n"
        f"📅 **Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"📝 **Report:**\n{report_text}\n\n"
        f"💬 **Reply to user:** Use admin panel or send message directly"
    )
    
    try:
        # Send report to admin
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=admin_message,
            parse_mode='Markdown'
        )
        
        # Confirm to user
        await update.message.reply_text(
            f"✅ **Report Sent Successfully!**\n\n"
            f"📤 Your report has been forwarded to @{ADMIN_CONTACT_USERNAME}.\n\n"
            f"💬 **What happens next:**\n"
            f"• Admin will review your report\n"
            f"• You may receive a response if needed\n"
            f"• Thank you for helping improve Nebula AI!\n\n"
            f"🏠 Use /start to return to the main menu.",
            parse_mode='Markdown'
        )
        
        logger.info(f"Issue report forwarded from user {user.id} to admin")
        
    except Exception as e:
        logger.error(f"Failed to send report to admin: {e}")
        await update.message.reply_text(
            f"❌ **Report Failed**\n\n"
            f"Sorry, there was an error sending your report. Please try contacting @{ADMIN_CONTACT_USERNAME} directly.\n\n"
            f"🏠 Use /start to return to the main menu.",
            parse_mode='Markdown'
        )

# --- Command Handlers ---
async def smart_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Enhanced handler that checks for different interactive modes.
    """
    if not update.message:
        return
    
    user_id = update.effective_user.id if update.effective_user else 0
    message_text = update.message.text or ""
    
    # Skip if it's a command
    if message_text.startswith('/'):
        return
    
    # Check for active modes (priority order)
    if ('image_mode_users' in context.bot_data and 
        user_id in context.bot_data['image_mode_users']):
        
        # Image Mode - generate image from message
        await update.message.reply_text(
            f"🎨 **[IMAGE MODE]** Creating: _{message_text[:50]}{'...' if len(message_text) > 50 else ''}_\n\n"
            f"💡 *Tip: Type `/imagemode` to exit image mode*",
            parse_mode='Markdown'
        )
        await queue_job_handler(update, context, tools=["image_generation"])
    
    elif ('code_mode_users' in context.bot_data and 
          user_id in context.bot_data['code_mode_users']):
        
        # Code Mode - treat everything as coding task
        await update.message.reply_text(
            f"💻 **[CODE MODE]** Processing: _{message_text[:50]}{'...' if len(message_text) > 50 else ''}_\n\n"
            f"💡 *Tip: Go to 🎮 Modes to change or exit*",
            parse_mode='Markdown'
        )
        await queue_job_handler(update, context, tools=["code_interpreter"])
    
    elif ('websearch_mode_users' in context.bot_data and 
          user_id in context.bot_data['websearch_mode_users']):
        
        # Web Search Mode - search the web for everything
        await update.message.reply_text(
            f"🌐 **[WEB SEARCH MODE]** Searching: _{message_text[:50]}{'...' if len(message_text) > 50 else ''}_\n\n"
            f"💡 *Tip: Go to 🎮 Modes to change or exit*",
            parse_mode='Markdown'
        )
        await queue_job_handler(update, context, tools=["web_search"])
    
    else:
        # Normal chat mode with smart tool selection
        await queue_job_handler(
            update, context, 
            tools=["web_search", "code_interpreter"]
        )

async def image_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /image command with enhanced model compatibility check."""
    user = get_or_create_user(update.effective_user)

    # Enhanced model compatibility check with auto-fix suggestion
    if user['current_model'] not in IMAGE_SUPPORTED_MODELS:
        if update.message:
            # Create quick-fix buttons
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            
            keyboard = []
            # Add compatible models as quick-switch options
            from user_menu_handlers import AVAILABLE_MODELS
            for model_id in IMAGE_SUPPORTED_MODELS[:2]:  # Show top 2 options
                model_name = AVAILABLE_MODELS.get(model_id, model_id)
                keyboard.append([InlineKeyboardButton(
                    f"🔄 Switch to {model_name}", 
                    callback_data=f'models:set:{model_id}'
                )])
            
            keyboard.append([InlineKeyboardButton("⚙️ All AI Settings", callback_data='user:settings')])
            keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='image:cancel')])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            compatible_models = ", ".join([
                AVAILABLE_MODELS.get(m, m) 
                for m in IMAGE_SUPPORTED_MODELS
            ])
            
            await update.message.reply_text(
                f"🎨 **Image Generation Requires Compatible Model**\n\n"
                f"❌ **Current Model**: `{user['current_model']}`\n"
                f"✅ **Compatible Models**: {compatible_models}\n\n"
                f"**Quick Fix**: Choose a compatible model below, or visit AI Settings to see all options.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        return

    # If the check passes, proceed as normal
    await queue_job_handler(update, context, tools=["image_generation"])

async def websearch_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /websearch command - focused web search only"""
    await queue_job_handler(update, context, tools=["web_search"])

async def code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /code command - code interpreter only"""  
    await queue_job_handler(update, context, tools=["code_interpreter"])

async def imagemode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle image generation mode on/off"""
    if not update.message:
        return
    
    user_id = update.effective_user.id if update.effective_user else 0
    
    # Initialize user_data if needed
    if 'image_mode_users' not in context.bot_data:
        context.bot_data['image_mode_users'] = set()
    
    # Toggle image mode
    if user_id in context.bot_data['image_mode_users']:
        # Turn off image mode
        context.bot_data['image_mode_users'].remove(user_id)
        await update.message.reply_text(
            "🎨 **Image Generation Mode: OFF**\n\n"
            "✅ Back to normal chat mode!\n"
            "💬 Your messages will now be processed normally.\n\n"
            "🖼️ To generate a single image, use: `/image your prompt`\n"
            "🎨 To enter image mode again, use: `/imagemode`",
            parse_mode='Markdown'
        )
    else:
        # Turn on image mode
        context.bot_data['image_mode_users'].add(user_id)
        await update.message.reply_text(
            "🎨 **Image Generation Mode: ON**\n\n"
            "✨ **Everything you type will now generate images!**\n\n"
            "💡 **How it works:**\n"
            "• Just type what you want to see\n"
            "• Each message becomes an image\n"
            "• Be descriptive for best results\n\n"
            "🔧 **Examples:**\n"
            "• `sunset over mountains`\n"
            "• `cute cat wearing sunglasses`\n"
            "• `futuristic city at night`\n\n"
            "❌ **To exit**: Type `/imagemode` again or `/exit`",
            parse_mode='Markdown'
        )

async def exit_imagemode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exit image generation mode"""
    if not update.message:
        return
    
    user_id = update.effective_user.id if update.effective_user else 0
    
    if 'image_mode_users' in context.bot_data and user_id in context.bot_data['image_mode_users']:
        context.bot_data['image_mode_users'].remove(user_id)
        await update.message.reply_text(
            "✅ **Exited Image Generation Mode**\n\n"
            "💬 Back to normal chat!\n"
            "🎨 Use `/imagemode` to enter image mode again.",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "💡 You're not in image generation mode.\n"
            "🎨 Use `/imagemode` to start generating images!"
        )

async def document_library_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document library queries with dynamic library management"""
    if not update.message:
        return
    
    if not context.args:
        await update.message.reply_text(
            "Please provide a query after the /doc command.\n"
            "Example: `/doc explain the main concepts in the uploaded documents`"
        )
        return
    
    query = " ".join(context.args)
    user_id = update.effective_user.id if update.effective_user else 0
    
    # Check if libraries exist
    try:
        libraries = await asyncio.to_thread(list_libraries)
        if not libraries:
            if update.message:
                await update.message.reply_text(
                    "📚 No document libraries found!\n\n"
                    "Please ask an administrator to:\n"
                    "1. Create a document library\n"
                    "2. Upload some documents\n\n"
                    "Contact support for help setting up document libraries."
                )
            return
        
        # Get library IDs
        library_ids = [getattr(lib, 'id', '') for lib in libraries if hasattr(lib, 'id')]
        logger.info(f"Found {len(library_ids)} libraries: {library_ids}")
        
    except Exception as e:
        logger.error(f"Failed to list libraries: {e}")
        if update.message:
            await update.message.reply_text(
                "❌ Error accessing document libraries. Please try again later or contact support."
            )
        return
    
    # Get or create document library agent for this user
    if 'document_agents' not in context.bot_data:
        context.bot_data['document_agents'] = {}
    
    if user_id not in context.bot_data['document_agents']:
        try:
            # Create a new agent for this user with all available libraries
            if update.message:
                await update.message.reply_text("🤖 Setting up document library agent...")
            agent = await asyncio.to_thread(create_document_library_agent, library_ids)
            agent_id = getattr(agent, 'id', '') 
            context.bot_data['document_agents'][user_id] = agent_id
            logger.info(f"Created document library agent {agent_id} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to create document library agent for user {user_id}: {e}")
            if update.message:
                await update.message.reply_text(
                    "❌ Failed to create document library agent. Please try again later."
                )
            return
    
    agent_id = context.bot_data['document_agents'][user_id]
    
    # Send query to document library
    if update.message:
        await update.message.reply_text("🔍 Searching document library...")
    
    try:
        response = await asyncio.to_thread(query_document_library, agent_id, query)
        
        # Extract text from response
        if hasattr(response, 'outputs') and response.outputs:
            for output in response.outputs:
                if hasattr(output, 'type') and getattr(output, 'type', '') == "message.output":
                    output_content = getattr(output, 'content', None)
                    if output_content:
                        # Handle content as list or single item
                        content_list = output_content if isinstance(output_content, list) else [output_content]
                        for content in content_list:
                            # Handle different content types
                            content_text = None
                            if hasattr(content, 'text'):
                                content_text = getattr(content, 'text', None)
                            elif isinstance(content, str):
                                content_text = content
                            
                            if content_text and update.message:
                                # Send with proper formatting
                                await send_long_message(update.message, content_text)
                                return
        
        if update.message:
            await send_formatted_message(update.message, "📄 No relevant information found in the document library for your query.")
        
    except Exception as e:
        logger.error(f"Document library query failed: {e}")
        # Reset the agent in case it's corrupted
        if user_id in context.bot_data.get('document_agents', {}):
            del context.bot_data['document_agents'][user_id]
        if update.message:
            await update.message.reply_text(
                "❌ Sorry, I couldn't search the document library at this time. Please try again."
            )

# --- Application Startup Function ---
async def post_init(application: Application):
    """Called after the Application is built to start background worker tasks and set bot commands."""
    
    # --- NEW: Set the bot's command menu ---
    await application.bot.set_my_commands([
        BotCommand("start", "🚀 Main Menu & Welcome"),
        BotCommand("account", "👤 View My Account Status"),
        BotCommand("image", "🖼️ Create a Single Image"),
        BotCommand("imagemode", "🎨 Enter Image Generation Mode"),
        BotCommand("websearch", "🌐 Web Search Only"),
        BotCommand("code", "💻 Code Interpreter Only"),
        BotCommand("doc", "📚 Search Your Documents"),
        BotCommand("help", "❓ Get Help & Information")
        # Note: We don't list /admin or /exit here
    ])
    logger.info("Bot command menu has been set.")
    # --- END NEW ---

    logger.info("Starting worker fleet...")
    job_queue = asyncio.Queue()
    application.bot_data['job_queue'] = job_queue

    application.bot_data['worker_tasks'] = []
    for i in range(WORKER_COUNT):
        task = asyncio.create_task(worker(f"Worker-{i+1}", job_queue))
        application.bot_data['worker_tasks'].append(task)
    logger.info(f"🚀 Bot is ready with {WORKER_COUNT} parallel workers.")

# =================================================================
# CONTEXT MANAGEMENT COMMANDS
# =================================================================

async def reset_context_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset conversation context manually."""
    if not update.effective_user:
        return
    
    user_id = update.effective_user.id
    success = clear_user_context(user_id)
    
    if success:
        await send_formatted_message(
            update.message,
            "🔄 **Context Reset Complete!**\n\n"
            "Your conversation history has been cleared. I'll start fresh from your next message!"
        )
    else:
        await send_formatted_message(
            update.message,
            "ℹ️ **Nothing to Reset**\n\n"
            "You don't have any conversation history yet."
        )

async def new_conversation_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start a completely new conversation.""" 
    if not update.effective_user:
        return
    
    user_id = update.effective_user.id
    clear_user_context(user_id)
    
    await send_formatted_message(
        update.message,
        "🆕 **New Conversation Started!**\n\n"
        "✨ Clean slate! What would you like to talk about?"
    )

async def context_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show information about current conversation context."""
    if not update.effective_user:
        return
    
    user_id = update.effective_user.id
    stats = get_context_stats(user_id)
    
    info_text = (
        f"📊 **Conversation Context Info**\n\n"
        f"💬 **Messages in Memory**: {stats.get('messages', 0)}\n"
        f"🏷️ **Current Topic**: {stats.get('current_topic', 'None')}\n"
        f"⏰ **Last Reset**: {stats.get('last_reset', 'Never')}\n\n"
        f"**💡 Pro Tips:**\n"
        f"• Say 'new topic' or 'change subject' for auto-reset\n"
        f"• Use `/reset` to manually clear context\n"
        f"• Use `/newconvo` to start completely fresh"
    )
    
    await send_formatted_message(update.message, info_text)

# --- Main Application ---
def main():
    # --- NEW: Initialize the database on startup ---
    initialize_database()

    request = HTTPXRequest(connect_timeout=10.0, read_timeout=60.0, pool_timeout=10.0)
    
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(request)
        .post_init(post_init)
        .build()
    )
    
    # --- Conversation Handler for Custom Functions ---
    functions_conversation_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(functions_menu, pattern='^settings:functions$')],
        states={
            FC_SELECTING_ACTION: [
                CallbackQueryHandler(ask_for_name, pattern='^functions:add$'),
                CallbackQueryHandler(show_delete_menu, pattern='^functions:delete_menu$'),
                CallbackQueryHandler(back_to_settings, pattern='^functions:back_to_settings$')
            ],
            FC_GETTING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            FC_GETTING_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_description)],
            FC_GETTING_SCHEMA: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_schema_and_save)],
            FC_CONFIRM_DELETE: [
                CallbackQueryHandler(confirm_delete_function, pattern='^functions:confirm_delete:'),
                CallbackQueryHandler(functions_menu, pattern='^functions:main_menu$')
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_flow)],
        map_to_parent={
             ConversationHandler.END: SELECTING_SETTING
        }
    )

    # --- NEW: Conversation Handler for Parameter Tuning ---
    tuning_conversation_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_tuning_handler, pattern='^settings:tune$')],
        states={
            SELECTING_SETTING: [
                CallbackQueryHandler(ask_for_system_prompt, pattern='^settings:set_prompt$'),
                CallbackQueryHandler(ask_for_temperature, pattern='^settings:set_temp$'),
                CallbackQueryHandler(ask_for_top_p, pattern='^settings:set_top_p$'),
                CallbackQueryHandler(ask_for_max_tokens, pattern='^settings:set_max_tokens$'),
                CallbackQueryHandler(end_tuning_conversation, pattern='^settings:back_to_main$')
            ],
            GETTING_SYSTEM_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_system_prompt)],
            GETTING_TEMPERATURE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_temperature)],
            GETTING_TOP_P: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_top_p)],
            GETTING_MAX_TOKENS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_max_tokens)],
        },
        fallbacks=[CommandHandler("cancel", cancel_setting)],
        per_message=False,
        map_to_parent={
            # After the conversation ends, it will go back to the main settings menu
            ConversationHandler.END: FC_SELECTING_ACTION,
        }
    )

    application.add_handler(admin_conversation_handler)
    application.add_handler(tuning_conversation_handler)
    application.add_handler(functions_conversation_handler)

    # --- User Menu Handlers ---
    application.add_handler(CommandHandler("start", start_command_handler))
    application.add_handler(CommandHandler("account", account_command_handler))
    application.add_handler(CommandHandler("help", help_menu_handler)) # <-- NEW: Wire up /help command
    application.add_handler(CommandHandler("doc", document_library_handler))
    
    # --- Context Management Commands ---
    application.add_handler(CommandHandler("reset", reset_context_command))
    application.add_handler(CommandHandler("newconvo", new_conversation_command))
    application.add_handler(CommandHandler("context", context_info_command))
    
    # Handlers for the buttons in the user menu
    application.add_handler(CallbackQueryHandler(account_command_handler, pattern='^user:account$'))
    application.add_handler(CallbackQueryHandler(create_purchase_ticket_handler, pattern='^user:create_ticket$'))
    application.add_handler(CallbackQueryHandler(start_command_handler, pattern='^user:main_menu$'))
    
    # --- NEW & UPDATED: Interactive Help Menu Handlers ---
    application.add_handler(CallbackQueryHandler(help_menu_handler, pattern='^user:help_menu$'))
    application.add_handler(CallbackQueryHandler(help_images_handler, pattern='^user:help_images$'))
    application.add_handler(CallbackQueryHandler(help_features_handler, pattern='^user:help_features$'))
    application.add_handler(CallbackQueryHandler(help_rag_handler, pattern='^user:help_rag$'))

    # --- NEW: Interactive Modes Menu Handlers ---
    application.add_handler(CallbackQueryHandler(modes_menu_handler, pattern='^user:modes$'))
    application.add_handler(CallbackQueryHandler(toggle_mode_handler, pattern='^modes:toggle:'))
    application.add_handler(CallbackQueryHandler(turn_off_all_modes_handler, pattern='^modes:off_all$'))
    
    # --- Image Generation Helper Handlers ---
    application.add_handler(CallbackQueryHandler(image_cancel_handler, pattern='^image:cancel$'))
    
    # --- Context Management Handlers ---
    application.add_handler(CallbackQueryHandler(context_menu_handler, pattern='^user:context_menu$'))
    application.add_handler(CallbackQueryHandler(context_reset_handler, pattern='^context:reset$'))
    application.add_handler(CallbackQueryHandler(context_new_convo_handler, pattern='^context:new_convo$'))
    application.add_handler(CallbackQueryHandler(context_details_handler, pattern='^context:details$'))
    
    # --- Issue Reporting Handlers ---
    application.add_handler(CallbackQueryHandler(report_issue_handler, pattern='^user:report_issue$'))
    application.add_handler(CallbackQueryHandler(start_report_handler, pattern='^report:start$'))
    application.add_handler(CallbackQueryHandler(cancel_report_handler, pattern='^report:cancel$'))

    # --- NEW: AI Settings and Model Selector Handlers ---
    application.add_handler(CallbackQueryHandler(settings_menu_handler, pattern='^user:settings$'))
    application.add_handler(CallbackQueryHandler(show_paginated_model_options, pattern='^models:change:'))
    application.add_handler(CallbackQueryHandler(set_new_model_handler, pattern='^models:set:'))

    # --- NEW: Agent Commands for Users ---
    application.add_handler(CommandHandler("websearch", websearch_handler))
    application.add_handler(CommandHandler("code", code_handler))
    
    # --- Regular Handlers ---
    # --- NEW: Voice and Document Handlers ---
    application.add_handler(MessageHandler(filters.VOICE, voice_handler))
    application.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, document_and_image_handler))
    
    # --- New Image Mode Handlers ---
    application.add_handler(CommandHandler("imagemode", imagemode_handler))
    application.add_handler(CommandHandler("exit", exit_imagemode_handler))
    
    # --- Regular Handlers ---
    application.add_handler(CommandHandler("image", image_handler))
    
    # Issue reporting message handler (must come before smart_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_report_message))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, smart_handler))

    application.run_polling()

# --- NEW: Voice and Document Handlers ---
async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles voice messages by transcribing them and processing as text."""
    if not update.message or not update.message.voice:
        return
        
    voice_file = await update.message.voice.get_file()
    user_id = update.message.from_user.id if update.message.from_user else "unknown"
    file_path = f"temp_audio_{user_id}.ogg"
    await voice_file.download_to_drive(file_path)

    transcribed_text = transcribe_audio(file_path)
    os.remove(file_path)

    if transcribed_text:
        # Create a modified update with the transcribed text
        # We'll modify the message text to contain the transcribed content
        update.message.text = transcribed_text
        await queue_job_handler(update, context, tools=["web_search", "code_interpreter"])
    else:
        await update.message.reply_text("Sorry, I couldn't understand the audio.")

async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Automatically upload documents to the default library."""
    if not update.message or not update.message.document:
        return
    
    user_id = update.effective_user.id if update.effective_user else 0
    document = update.message.document
    
    # Check file size (max 20MB)
    if document.file_size and document.file_size > 20 * 1024 * 1024:
        await update.message.reply_text(
            "📁 File too large! Please upload files smaller than 20MB.\n\n"
            "💡 *Tip*: You can compress large documents or split them into smaller files."
        )
        return
    
    # Check file type
    allowed_extensions = ['.txt', '.pdf', '.doc', '.docx', '.md', '.rtf']
    file_name = document.file_name or "document"
    file_extension = os.path.splitext(file_name.lower())[1]
    
    if file_extension not in allowed_extensions:
        await update.message.reply_text(
            f"📁 Unsupported file type: `{file_extension}`\n\n"
            f"✅ Supported formats: {', '.join(allowed_extensions)}\n\n"
            f"💡 *Tip*: Convert your file to PDF or TXT format for best results.",
            parse_mode='Markdown'
        )
        return
    
    await update.message.reply_text(
        "📁 **Document received!** Processing...\n\n"
        "🔄 Downloading and adding to your personal library...",
        parse_mode='Markdown'
    )
    
    file_path = None
    try:
        # Download the file
        file = await document.get_file()
        file_path = f"temp_doc_{user_id}_{int(time.time())}_{file_name}"
        await file.download_to_drive(file_path)
        
        # Get or create user's personal library
        library_id = await get_or_create_user_library(user_id)
        
        if library_id:
            # Upload to library
            await asyncio.to_thread(
                upload_document_to_library, 
                library_id, 
                file_path, 
                file_name
            )
            
            # Success message
            await update.message.reply_text(
                f"✅ **Document uploaded successfully!**\n\n"
                f"📄 *File*: `{file_name}`\n"
                f"📚 *Added to*: Your Personal Library\n\n"
                f"🔍 **How to search**: Use `/doc your question here`\n"
                f"💡 *Example*: `/doc what are the main points in this document?`\n\n"
                f"📖 **What is RAG?** This document is now searchable using AI! "
                f"I can find relevant information from your uploaded documents and answer questions about them.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ Failed to create your personal library. Please try again or contact support."
            )
        
        # Clean up
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            
    except Exception as e:
        logger.error(f"Document upload failed for user {user_id}: {e}")
        await update.message.reply_text(
            "❌ **Upload failed!**\n\n"
            "This could be due to:\n"
            "• Network issues\n"
            "• File corruption\n"
            "• Server problems\n\n"
            "Please try again, or contact support if the issue persists."
        )
        
        # Clean up on error
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

async def handle_image_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle image uploads with helpful information."""
    if not update.message or not update.message.photo:
        return
    
    await update.message.reply_text(
        "🖼️ **Image received!**\n\n"
        "🤖 **What I can do**:\n"
        "• Analyze and describe images\n"
        "• Answer questions about image content\n"
        "• Extract text from images (OCR)\n\n"
        "💡 **Try asking**: *What do you see in this image?*\n\n"
        "🎨 **Want to create images?** Use `/imagemode` to enter image generation mode!"
    )

async def get_or_create_user_library(user_id: int) -> Optional[str]:
    """Get or create a personal library for the user."""
    try:
        # Check if user already has a personal library
        libraries = await asyncio.to_thread(list_libraries)
        user_library_name = f"User_{user_id}_Personal_Library"
        
        for lib in libraries:
            if hasattr(lib, 'name') and lib.name == user_library_name:
                return getattr(lib, 'id', None)
        
        # Create new personal library
        logger.info(f"Creating personal library for user {user_id}")
        library = await asyncio.to_thread(
            create_library, 
            user_library_name, 
            f"Personal document library for user {user_id}"
        )
        
        library_id = getattr(library, 'id', None)
        logger.info(f"Created library {library_id} for user {user_id}")
        return library_id
        
    except Exception as e:
        logger.error(f"Failed to get/create library for user {user_id}: {e}")
        return None

async def document_and_image_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles documents and images with automatic library upload."""
    if not update.message:
        return
        
    if update.message.document:
        await handle_document_upload(update, context)
    elif update.message.photo:
        await handle_image_upload(update, context)

if __name__ == '__main__':
    main()