# conversation_manager.py - Smart Context Management System

import time
import re
from collections import deque
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Enhanced conversation storage with metadata
conversation_histories = {}
user_topics = {}  # Track current topic for each user
context_reset_timestamps = {}  # Track when context was last reset

# Configuration
MAX_HISTORY_LENGTH = 12  # Increased to allow for smarter pruning
TOPIC_CHANGE_THRESHOLD = 0.7  # How different topics need to be (0-1)
AUTO_RESET_KEYWORDS = [
    'new topic', 'change subject', 'something else', 'different question',
    'by the way', 'btw', 'moving on', 'next question', 'different topic'
]

class ConversationContext:
    def __init__(self):
        self.messages = deque(maxlen=MAX_HISTORY_LENGTH)
        self.current_topic = None
        self.topic_keywords = set()
        self.last_reset = time.time()
        
    def add_message(self, role: str, content: str, topic_keywords: set = None):
        """Add a message with optional topic information."""
        message = {
            "role": role,
            "content": content,
            "timestamp": time.time(),
            "topic_keywords": topic_keywords or set()
        }
        self.messages.append(message)
        
        if topic_keywords:
            self.topic_keywords.update(topic_keywords)
    
    def get_relevant_messages(self, current_keywords: set = None) -> List[Dict]:
        """Get messages relevant to current topic."""
        if not current_keywords:
            return list(self.messages)
        
        relevant_messages = []
        for msg in self.messages:
            # Always include recent messages (last 4)
            if len(self.messages) - list(self.messages).index(msg) <= 4:
                relevant_messages.append(msg)
                continue
                
            # Include messages with topic overlap
            if msg["topic_keywords"] and current_keywords:
                overlap = len(msg["topic_keywords"] & current_keywords)
                if overlap > 0:
                    relevant_messages.append(msg)
        
        return relevant_messages
    
    def clear_context(self):
        """Clear conversation context."""
        self.messages.clear()
        self.current_topic = None
        self.topic_keywords.clear()
        self.last_reset = time.time()

def extract_topic_keywords(text: str) -> set:
    """Extract key topic words from text."""
    # Remove common words and extract meaningful terms
    stopwords = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 
        'with', 'by', 'from', 'up', 'about', 'into', 'through', 'during', 'before',
        'after', 'above', 'below', 'between', 'among', 'is', 'are', 'was', 'were',
        'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
        'would', 'could', 'should', 'may', 'might', 'must', 'can', 'this', 'that',
        'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him',
        'her', 'us', 'them', 'my', 'your', 'his', 'her', 'its', 'our', 'their'
    }
    
    # Extract words, filter stopwords, and get meaningful terms
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    keywords = {word for word in words if word not in stopwords}
    
    # Limit to most important keywords (max 10)
    return set(list(keywords)[:10])

def detect_topic_change(old_keywords: set, new_keywords: set) -> bool:
    """Detect if there's a significant topic change."""
    if not old_keywords or not new_keywords:
        return False
    
    # Calculate similarity using Jaccard coefficient
    intersection = len(old_keywords & new_keywords)
    union = len(old_keywords | new_keywords)
    
    if union == 0:
        return False
        
    similarity = intersection / union
    return similarity < (1 - TOPIC_CHANGE_THRESHOLD)

def detect_explicit_topic_change(text: str) -> bool:
    """Detect explicit topic change phrases."""
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in AUTO_RESET_KEYWORDS)

def get_conversation_history(user_id: int) -> list:
    """Gets the relevant conversation history for a user."""
    if user_id not in conversation_histories:
        conversation_histories[user_id] = ConversationContext()
    
    context = conversation_histories[user_id]
    current_keywords = user_topics.get(user_id, set())
    
    # Get relevant messages based on current topic
    relevant_messages = context.get_relevant_messages(current_keywords)
    
    # Convert to simple format expected by API
    return [{"role": msg["role"], "content": msg["content"]} for msg in relevant_messages]

def add_to_conversation_history(user_id: int, role: str, content: str) -> Optional[str]:
    """
    Adds a new message to user's history with smart topic management.
    Returns a message if context was reset, None otherwise.
    """
    if user_id not in conversation_histories:
        conversation_histories[user_id] = ConversationContext()
    
    context = conversation_histories[user_id]
    
    # Extract topic keywords from the new message
    new_keywords = extract_topic_keywords(content)
    current_keywords = user_topics.get(user_id, set())
    
    # Check for topic changes
    context_reset_message = None
    
    if role == "user":  # Only check topic changes for user messages
        # Check for explicit topic change phrases
        if detect_explicit_topic_change(content):
            context.clear_context()
            context_reset_message = "🔄 **New conversation started** - Context cleared!"
            logger.info(f"Explicit topic change detected for user {user_id}")
        
        # Check for automatic topic change detection
        elif current_keywords and detect_topic_change(current_keywords, new_keywords):
            # Only auto-reset if we have enough context to be confident
            if len(context.messages) >= 4:
                context.clear_context()
                context_reset_message = "🎯 **Topic change detected** - Starting fresh context!"
                logger.info(f"Automatic topic change detected for user {user_id}")
        
        # Update user's current topic
        user_topics[user_id] = new_keywords
    
    # Add the message to history
    context.add_message(role, content, new_keywords if role == "user" else None)
    
    return context_reset_message

def clear_user_context(user_id: int) -> bool:
    """Manually clear a user's conversation context."""
    if user_id in conversation_histories:
        conversation_histories[user_id].clear_context()
        if user_id in user_topics:
            del user_topics[user_id]
        logger.info(f"Manually cleared context for user {user_id}")
        return True
    return False

def get_context_stats(user_id: int) -> Dict:
    """Get statistics about user's conversation context."""
    if user_id not in conversation_histories:
        return {
            "messages": 0, 
            "topic_keywords": 0, 
            "current_topic": "None",
            "last_reset": "Never"
        }
    
    context = conversation_histories[user_id]
    return {
        "messages": len(context.messages),
        "topic_keywords": len(context.topic_keywords),
        "current_topic": ", ".join(list(context.topic_keywords)[:5]) if context.topic_keywords else "None",
        "last_reset": time.strftime("%H:%M:%S", time.localtime(context.last_reset))
    } 