# database_manager.py

import sqlite3
import logging
from datetime import datetime, timedelta

DATABASE_FILE = "mistral_bot_users.db"
logger = logging.getLogger(__name__)

# --- Plan Definitions ---
# We define our plans here so they are easy to manage.
# For now, we only have the 'free' plan.
PLANS = {
    'free': {
        'daily_images': 3,
        'daily_tokens_limit': 20000  # A generous limit for text
    },
    'premium': {
        'daily_images': 50,
        'daily_tokens_limit': 500000
    },
    'premium_plus': {
        'daily_images': -1,  # -1 means unlimited
        'daily_tokens_limit': -1
    }
}


def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row # This lets us access columns by name
    return conn

def initialize_database():
    """Creates and updates all necessary tables and columns."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            plan_name TEXT NOT NULL DEFAULT 'free',
            daily_images_used INTEGER NOT NULL DEFAULT 0,
            daily_tokens_used INTEGER NOT NULL DEFAULT 0,
            subscription_expiry_date DATETIME,
            last_seen DATETIME NOT NULL
        )
    ''')

    # --- NEW: Non-destructive column addition ---
    # This checks if the column exists before trying to add it, preventing errors on restart.
    cursor.execute("PRAGMA table_info(users)")
    columns = [column['name'] for column in cursor.fetchall()]
    if 'current_model' not in columns:
        # We set a default model for everyone.
        cursor.execute("ALTER TABLE users ADD COLUMN current_model TEXT NOT NULL DEFAULT 'mistral-medium-latest'")
        logger.info("Added 'current_model' column to the users table.")

    if 'system_prompt' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN system_prompt TEXT")
    if 'temperature' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN temperature REAL DEFAULT 0.7")
    if 'top_p' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN top_p REAL DEFAULT 1.0")
    if 'max_tokens' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN max_tokens INTEGER DEFAULT 4096")
    
    # --- NEW: Columns for Advanced User Management ---
    if 'is_banned' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER NOT NULL DEFAULT 0")
        logger.info("Added 'is_banned' column to users table.")
    if 'is_active' not in columns:
        # 1 = active, 0 = inactive (likely blocked the bot)
        cursor.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        logger.info("Added 'is_active' column to users table.")

    # --- NEW: Table for Historical Usage Tracking ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usage_stats (
            stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            stat_date DATE NOT NULL,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            images_used INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            UNIQUE(user_id, stat_date) -- Prevents duplicate entries for the same user on the same day
        )
    ''')
    
    # --- NEW: Create a table for user-defined custom functions ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_functions (
            function_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            schema_json TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")


def get_or_create_user(user_data):
    """
    Retrieves a user, creates them if new, and handles daily limit/subscription resets.
    """
    # This function now also checks for expired subscriptions and returns the user's current model.
    # The logic inside remains the same from our last step. It's already perfect.
    conn = get_db_connection()
    cursor = conn.cursor()
    
    user = cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_data.id,)).fetchone()
    
    now = datetime.now()
    today = now.date()
    
    if user is None:
        cursor.execute(
            "INSERT INTO users (user_id, first_name, username, last_seen, current_model, plan_name) VALUES (?, ?, ?, ?, ?, ?)",
            (user_data.id, user_data.first_name, user_data.username, now, 'mistral-large-latest', 'premium_plus')
        )
        logger.info(f"🚀 NEW LAUNCH USER created with PREMIUM_PLUS: {user_data.id} ({user_data.first_name})")
    else:
        last_seen_date = datetime.fromisoformat(user['last_seen']).date()
        if last_seen_date < today:
            cursor.execute("UPDATE users SET daily_images_used = 0, daily_tokens_used = 0 WHERE user_id = ?", (user_data.id,))
            logger.info(f"Daily limits reset for user {user_data.id}")

        if user['plan_name'] != 'free' and user['subscription_expiry_date']:
            expiry_date = datetime.fromisoformat(user['subscription_expiry_date'])
            if now > expiry_date:
                cursor.execute("UPDATE users SET plan_name = 'free', subscription_expiry_date = NULL, current_model = 'mistral-medium-latest' WHERE user_id = ?", (user_data.id,))
                logger.info(f"Subscription for user {user_data.id} has expired. Reverted to free plan.")

        cursor.execute("UPDATE users SET last_seen = ?, first_name = ?, username = ? WHERE user_id = ?", (now, user_data.first_name, user_data.username, user_data.id))
        
    conn.commit()
    user = cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_data.id,)).fetchone()
    conn.close()
    return user

def get_user_by_id(user_id: int):
    """A simple helper to get a user row by their ID."""
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return user

def increment_image_usage(user_id: int):
    """Increments the image usage counter for a user and logs it."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET daily_images_used = daily_images_used + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    log_usage(user_id, images=1) # <-- Log to historical table
    logger.info(f"Incremented image usage for user {user_id}.")

def update_token_usage(user_id: int, token_count: int):
    """Adds the token count to a user's daily usage and logs it."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET daily_tokens_used = daily_tokens_used + ? WHERE user_id = ?", (token_count, user_id))
    conn.commit()
    conn.close()
    log_usage(user_id, tokens=token_count) # <-- Log to historical table

def check_user_limits(user_row, tools: list) -> (bool, str):
    """Checks all plan limits (images and tokens)."""
    plan_name = user_row['plan_name']
    plan_details = PLANS.get(plan_name, PLANS['free'])

    # Check for image generation limit
    if 'image_generation' in tools:
        images_limit = plan_details['daily_images']
        if images_limit != -1 and user_row['daily_images_used'] >= images_limit:
            message = (
                "😔 **Daily Image Limit Reached!**\n\n"
                f"You have used your quota of {images_limit} images for today using the `/image` command. "
                "Your limit will reset tomorrow.\n\n"
                "To upgrade your plan, please contact the admin."
            )
            return False, message
    else: # --- NEW: This is a text-based request, so check token limits ---
        tokens_limit = plan_details['daily_tokens_limit']
        if tokens_limit != -1 and user_row['daily_tokens_used'] >= tokens_limit:
            message = (
                "😔 **Daily Chat Limit Reached!**\n\n"
                f"You have used your chat quota for today on the '{plan_name}' plan. "
                "Your limit will reset tomorrow.\n\n"
                "To get more credits, please contact the admin."
            )
            return False, message

    return True, "Limits are okay."

# --- NEW: Central function to log historical usage ---
def log_usage(user_id: int, tokens: int = 0, images: int = 0):
    """Logs token and image usage to the historical stats table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    today = datetime.now().date()
    # This 'UPSERT' logic is powerful: it inserts a new row or, if a row for that user/date
    # already exists, it updates the counters instead.
    cursor.execute('''
        INSERT INTO usage_stats (user_id, stat_date, tokens_used, images_used)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, stat_date) DO UPDATE SET
            tokens_used = tokens_used + excluded.tokens_used,
            images_used = images_used + excluded.images_used
    ''', (user_id, today, tokens, images))
    conn.commit()
    conn.close()

def set_user_model(user_id: int, model_name: str) -> bool:
    """Sets a user's preferred AI model."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET current_model = ? WHERE user_id = ?", (model_name, user_id))
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    if success:
        logger.info(f"User {user_id} changed their model to '{model_name}'.")
    return success

def set_user_system_prompt(user_id: int, prompt: str) -> bool:
    """Sets a user's custom system prompt."""
    conn = get_db_connection()
    cursor = conn.cursor()
    # If prompt is empty, set it to NULL in the database
    db_prompt = prompt if prompt and prompt.strip() else None
    cursor.execute("UPDATE users SET system_prompt = ? WHERE user_id = ?", (db_prompt, user_id))
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    if success:
        logger.info(f"User {user_id} updated their system prompt.")
    return success

def set_user_temperature(user_id: int, temp: float) -> bool:
    """Sets a user's preferred temperature."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET temperature = ? WHERE user_id = ?", (temp, user_id))
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    if success:
        logger.info(f"User {user_id} set temperature to {temp}.")
    return success

def set_user_top_p(user_id: int, top_p: float) -> bool:
    """Sets a user's preferred top_p."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET top_p = ? WHERE user_id = ?", (top_p, user_id))
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    if success:
        logger.info(f"User {user_id} set top_p to {top_p}.")
    return success

def set_user_max_tokens(user_id: int, max_tokens: int) -> bool:
    """Sets a user's preferred max_tokens."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET max_tokens = ? WHERE user_id = ?", (max_tokens, user_id))
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    if success:
        logger.info(f"User {user_id} set max_tokens to {max_tokens}.")
    return success

# --- NEW: Functions for managing custom tools ---

def add_custom_function(user_id: int, name: str, description: str, schema_json: str) -> bool:
    """Adds a new custom function for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO custom_functions (user_id, name, description, schema_json) VALUES (?, ?, ?, ?)",
            (user_id, name, description, schema_json)
        )
        conn.commit()
        logger.info(f"Added custom function '{name}' for user {user_id}.")
        return True
    except sqlite3.Error as e:
        logger.error(f"Database error adding function for user {user_id}: {e}")
        return False
    finally:
        conn.close()

def get_user_functions(user_id: int) -> list:
    """Retrieves all custom functions for a specific user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT function_id, name, description, schema_json FROM custom_functions WHERE user_id = ?", (user_id,))
    functions = cursor.fetchall()
    conn.close()
    return functions

def delete_custom_function(function_id: int, user_id: int) -> bool:
    """Deletes a specific custom function owned by a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    # Ensure the user owns the function they are trying to delete
    cursor.execute("DELETE FROM custom_functions WHERE function_id = ? AND user_id = ?", (function_id, user_id))
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    if success:
        logger.info(f"User {user_id} deleted function {function_id}.")
    return success

# --- NEW: Functions for Banning and Activity Status ---
def set_user_ban_status(user_id: int, is_banned: bool):
    """Sets the is_banned flag for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (1 if is_banned else 0, user_id))
    conn.commit()
    logger.info(f"Set ban status for user {user_id} to {is_banned}.")
    conn.close()

def set_user_active_status(user_id: int, is_active: bool):
    """Sets the is_active flag for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_active = ? WHERE user_id = ?", (1 if is_active else 0, user_id))
    conn.commit()
    conn.close()

def set_user_plan(user_id: int, plan_name: str, duration_days: int = None) -> bool:
    """
    Sets a user's subscription plan, optionally with an expiry date.
    """
    if plan_name not in PLANS:
        return False
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    expiry_date = None
    if duration_days is not None:
        expiry_date = datetime.now() + timedelta(days=duration_days)

    # --- NEW: Set model based on plan ---
    new_model = 'mistral-medium-latest' if plan_name == 'free' else 'mistral-large-latest'

    cursor.execute(
        "UPDATE users SET plan_name = ?, subscription_expiry_date = ?, current_model = ? WHERE user_id = ?",
        (plan_name, expiry_date, new_model, user_id)
    )
    
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    
    if success:
        logger.info(f"Updated plan for user {user_id} to '{plan_name}'" + (f" for {duration_days} days." if duration_days else "."))
    else:
        logger.warning(f"Attempted to update plan for non-existent user {user_id}.")
    return success

def get_all_user_ids() -> list[int]:
    """Retrieves a list of all user IDs from the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    # The result is a list of tuples, like [(123,), (456,)], so we extract the first item of each tuple.
    user_ids = [item['user_id'] for item in cursor.fetchall()]
    conn.close()
    return user_ids

# --- NEW: Master Statistics Function ---
def get_bot_statistics() -> dict:
    """Gathers a comprehensive dictionary of bot statistics."""
    conn = get_db_connection()
    stats = {}

    # User counts
    stats['total_users'] = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    stats['active_users'] = conn.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()[0]
    stats['inactive_users'] = stats['total_users'] - stats['active_users'] # Inactive = blocked the bot
    stats['banned_users'] = conn.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1").fetchone()[0]
    
    # Users per plan
    plan_counts = conn.execute("SELECT plan_name, COUNT(*) FROM users WHERE is_banned = 0 GROUP BY plan_name").fetchall()
    stats['users_per_plan'] = {row['plan_name']: row['COUNT(*)'] for row in plan_counts}

    # Usage stats (from the new historical table)
    seven_days_ago = (datetime.now() - timedelta(days=7)).date()
    stats['tokens_past_7_days'] = conn.execute(
        "SELECT SUM(tokens_used) FROM usage_stats WHERE stat_date >= ?", (seven_days_ago,)
    ).fetchone()[0] or 0
    stats['images_past_7_days'] = conn.execute(
        "SELECT SUM(images_used) FROM usage_stats WHERE stat_date >= ?", (seven_days_ago,)
    ).fetchone()[0] or 0
    
    stats['tokens_today'] = conn.execute(
        "SELECT SUM(tokens_used) FROM usage_stats WHERE stat_date = ?", (datetime.now().date(),)
    ).fetchone()[0] or 0
    stats['images_today'] = conn.execute(
        "SELECT SUM(images_used) FROM usage_stats WHERE stat_date = ?", (datetime.now().date(),)
    ).fetchone()[0] or 0

    # Most used model
    most_used = conn.execute("""
        SELECT current_model, COUNT(*) as count
        FROM users
        WHERE is_banned = 0
        GROUP BY current_model
        ORDER BY count DESC
        LIMIT 1
    """).fetchone()
    stats['most_used_model'] = f"{most_used['current_model']} ({most_used['count']} users)" if most_used else "N/A"

    conn.close()
    return stats

def get_full_user_data_for_export():
    """Retrieves all user data for CSV export."""
    conn = get_db_connection()
    users = conn.execute("SELECT user_id, first_name, username, plan_name, is_banned, is_active, last_seen FROM users ORDER BY user_id").fetchall()
    conn.close()
    return users