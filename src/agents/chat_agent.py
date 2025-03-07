"""
🌙 Moon Dev's Chat Agent
Built with love by Moon Dev 🚀

This agent monitors Restream chat and answers questions using a knowledge base.
"""

import sys
from pathlib import Path
# Add project root to Python path for imports
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

import os
import time
from datetime import datetime
from termcolor import cprint
from dotenv import load_dotenv
import pandas as pd
from src.config import *
from src.models import model_factory
import json
import threading
import random
import selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import csv

# Load environment variables from the project root
env_path = Path(project_root) / '.env'
if not env_path.exists():
    raise ValueError(f"🚨 .env file not found at {env_path}")

load_dotenv(dotenv_path=env_path)

# Model override settings
MODEL_TYPE = "groq"  # Using Claude for chat responses
MODEL_NAME = "llama-3.3-70b-versatile"  # Fast, efficient model

# Configuration - All in one place! 🎯
RESTREAM_CHECK_INTERVAL = 0.1  # Reduce to 100ms for more responsive chat
CONFIDENCE_THRESHOLD = 0.8
MAX_RETRIES = 3
MAX_RESPONSE_TOKENS = 50  # Increase to allow longer responses
CHAT_MEMORY_SIZE = 30
MIN_CHARS_FOR_RESPONSE = 3
DEFAULT_INITIAL_CHATS = 10
NEGATIVITY_THRESHOLD = 0.3  # Lower this from 0.4 to catch more negative messages
LEADERBOARD_INTERVAL = 10  # Show leaderboard every 10 chats
IGNORED_USERS = ["Nightbot", "StreamElements"]
# Add near the top with other configuration constants
POINTS_PER_777 = 0.5  # Points earned per 777 message
MAX_777_POINTS_PER_DAY = 5.0  # Maximum points from 777s per day
MAX_777_PER_DAY = int(MAX_777_POINTS_PER_DAY / POINTS_PER_777)  # Auto-calculate max 777s per day


# Restream configuration
RESTREAM_WEBSOCKET_URL = "wss://chat.restream.io/embed/ws"
RESTREAM_EVENT_SOURCES = {
    2: "Twitch",
    13: "YouTube",
    28: "X/Twitter"
}


# Chat prompts - for responding to message
CHAT_PROMPT = """You are Moon Dev's Live Stream Chat AI Agent. 
You help users learn about coding, algo trading, and Moon Dev's content.
Keep responses short, friendly, and include emojis.

Key points about Moon Dev:
- Passionate about AI, trading, and coding
- Streams coding sessions on YouTube
- Built multiple AI trading agents
- Loves adding emojis to everything
- Runs a coding bootcamp
- Focuses on Python and algo trading

Knowledge Base:
Frequently Asked Questions
* how/where do i get started with algo trading? moondev.com has a algo trading roadmap, resources, discord and github
* when do you live stream? daily at 8am est
* how you get point for bootcamp? what are points used for? the person with the most points at the end of each's days stream gets the algo trade camp for free for 1 month

User message: {question}
"""

# Update the negativity check prompt to be simpler
NEGATIVITY_CHECK_PROMPT = """

You are the negativity moderator swearing is okay. It's an 18 and over crowd. And YouTube monitors that. So that's not negativity. The negativity you're looking for is any negativity towards the presenter or other people in the chat. So if anybody is being hateful or saying mean things towards other people in the chat, then the negativity trigger would be true. If it's not negative towards somebody else in the chat or the YouTube presenter, then the negativity would be False. Reply with just true or false. 

Message: {message}
Is this message negative? Reply with ONLY 'true' or 'false':"""

PROMPT_777 = """
give me a random one of the below:
- a motivational quote
- a bible verse
or
- a cool parable

ONLY RETURN THE QUOTE, NO OTHER TEXT.
"""

# Add new constants for emojis
USER_EMOJIS = ["👨🏽", "👨🏽", "🧑🏽‍🦱", "👨🏽‍🦱", "👨🏽‍🦳", "👱🏽‍♂️", "👨🏽‍🦰", "👩🏽‍🦱"]
AI_EMOJIS = ["🤖", "🐳", "🐐", "👽", "🧠", "🌚"]
# Add lucky emojis for 777 responses
LUCKY_EMOJIS = ["⭐️", "🧠", "😎", "♥️", "💙", "💚", "😇", "🌟", "✨", "💫", "❤️‍🔥"]

# Configuration
MESSAGE_COOLDOWN = 3  # Reduce from 10 to 3 seconds

# Update config defaults
DEFAULT_CONFIG = {
    "response_prefix": "🤖 Moon Dev AI: ",
    "ignored_users": ["Nightbot", "StreamElements"],
    "command_prefix": "!",
    "initial_chats": DEFAULT_INITIAL_CHATS,
    "leaderboard_interval": 300,
    "use_restream": True,  # Force this to True
    "restream_show_id": None
}

# Add to configuration section
DEBUG_MODE = True  # Add this near other constants

# Update constants at the top
LOVE_EMOJIS = ["❤️", "💖", "💝", "💗", "💓", "💞", "💕", "💘", "💟", "💌", "🫶", "💝", "💖", "💗", "🩵", "🩶", "🩷", "💛", "💚", "💙", "💜", "🤍", "🤎", "🖤", "❤️‍🔥", "🩵", "🩶", "🩷", "💛", "💚", "💙", "💜", "🤍", "🤎", "🖤", "❤️‍🔥"]
LOVE_SPAM = " ".join(random.sample(LOVE_EMOJIS, 14))  # Random selection of love emojis


class RestreamChatHandler:
    """Handler for Restream chat integration"""
    def __init__(self, client_id, client_secret):
        self.embed_token = os.getenv('RESTREAM_EMBED_TOKEN')
        self.messages = []
        self.driver = None
        self.connected = False
        self.message_class = None
        self.chat_agent = None
        self.message_queue = []  # List of (timestamp, username, text) tuples
        self.message_timeout = 2  # Reduce timeout to 2 seconds
        self.last_message = None  # Track the last message we processed
        
        # Initialize Selenium options
        self.chrome_options = Options()
        self.chrome_options.add_argument("--headless=new")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--window-size=1920,1080")
        self.chrome_options.add_argument("--disable-notifications")
        self.chrome_options.add_argument("--disable-popup-blocking")
        self.chrome_options.add_argument("--disable-software-rasterizer")
        self.chrome_options.add_argument("--disable-extensions")
        
        # Simplify message tracking to just the last message content
        self.last_message_content = None
        
    def set_chat_agent(self, agent):
        """Set reference to ChatAgent for processing questions"""
        self.chat_agent = agent
        
    def process_question(self, username, text):
        """Forward question processing to ChatAgent"""
        if self.chat_agent:
            return self.chat_agent.process_question(username, text)
        return None
        
    def connect(self):
        if not self.embed_token:
            cprint("❌ RESTREAM_EMBED_TOKEN not found in .env!", "red")
            return
            
        try:
            cprint("🔌 Connecting to Restream chat...", "cyan")
            
            service = webdriver.ChromeService()
            self.driver = webdriver.Chrome(service=service, options=self.chrome_options)
            self.driver.set_page_load_timeout(30)
            
            embed_url = f"https://chat.restream.io/embed?token={self.embed_token}"
            cprint(f"🌐 Loading chat URL", "cyan")
            self.driver.get(embed_url)
            
            # Wait for page to load
            time.sleep(5)
            
            # Debug page source
            cprint("🔍 Looking for chat elements...", "cyan")
            page_source = self.driver.page_source
            
            # Try different class names that might be present
            possible_classes = [
                "chat-message", 
                "message", 
                "chat-item",
                "message-item",
                "chat-line",
                "rs-chat-message",
                "chat-messages",  # Added more possible classes
                "message-wrapper",
                "chat-message-wrapper"
            ]
            
            found_class = None
            for class_name in possible_classes:
                elements = self.driver.find_elements(By.CLASS_NAME, class_name)
                if elements:
                    found_class = class_name
                    cprint(f"✅ Found chat elements using class: {class_name}", "green")
                    break
            
            if found_class:
                self.message_class = found_class
                self.connected = True
                cprint("✅ Connected to Restream chat!", "green")
            else:
                # If no class found, use a default one
                self.message_class = "chat-message"
                cprint("⚠️ Using default message class: chat-message", "yellow")
                self.connected = True
            
            threading.Thread(target=self._poll_messages, daemon=True).start()
            
        except Exception as e:
            cprint(f"❌ Error connecting to Restream: {str(e)}", "red")
            if self.driver:
                self.driver.quit()
                self.driver = None

    def _poll_messages(self):
        while self.connected:
            try:
                if not self.message_class:
                    time.sleep(0.1)
                    continue

                # Look for all possible message containers
                message_containers = []
                for class_name in ["message-info-container", "chat-message", "message-wrapper"]:
                    containers = self.driver.find_elements(By.CLASS_NAME, class_name)
                    if containers:
                        message_containers.extend(containers)

                if not message_containers:
                    time.sleep(0.1)
                    continue
                    
                # Get the last message
                latest_msg = message_containers[-1]
                
                try:
                    # Try different class names for username
                    username = None
                    for class_name in ["message-sender", "chat-author", "username"]:
                        try:
                            username_elem = latest_msg.find_element(By.CLASS_NAME, class_name)
                            if username_elem:
                                username = username_elem.text.strip()
                                break
                        except:
                            continue
                    
                    if not username:
                        continue
                        
                    # Try different class names for message text
                    text = None
                    for class_name in ["chat-text-normal", "message-text", "chat-message-text"]:
                        try:
                            text_elem = latest_msg.find_element(By.CLASS_NAME, class_name)
                            if text_elem:
                                text = text_elem.text.strip()
                                break
                        except:
                            continue
                    
                    if not text:
                        continue
                    
                    # Create unique message content identifier
                    current_content = f"{username}:{text}"
                    
                    # Only process if this is a new message and has valid username
                    if current_content != self.last_message_content and username:
                        # Skip system messages
                        if username == "Restream.io" or not text:
                            continue
                            
                        # Process message
                        if self.chat_agent:
                            ai_response = self.chat_agent.process_question(username, text)
                            if ai_response:
                                self._display_chat(username, text, ai_response)
                                
                        # Update last message content after successful processing
                        self.last_message_content = current_content
                    
                except Exception as e:
                    cprint(f"⚠️ Error processing message: {str(e)}", "yellow")
                    continue

                time.sleep(0.1)
                
            except Exception as e:
                cprint(f"❌ Error polling messages: {str(e)}", "red")
                time.sleep(0.1)

    def __del__(self):
        """Clean up resources"""
        if self.driver:
            self.driver.quit()

    def _display_chat(self, username, text, ai_response):
        """Display chat with colored formatting
        ai_response can be:
        - string starting with 777: 777 response
        - string with 💖: negativity response (don't show original message)
        - True: normal message to display
        - string: AI response to question
        - None: skip displaying
        """
        if not ai_response:
            return
            
        # Check if this is a negativity response (contains both username and LOVE_SPAM)
        if isinstance(ai_response, str) and "💖" in ai_response and LOVE_SPAM in ai_response:
            # For negative messages, ONLY show the hearts and username, not the original message
            print(f"{random.choice(USER_EMOJIS)} ", end="")
            username_part = ai_response.split('\n')[0]
            cprint(username_part, "white", "on_magenta")
            print(LOVE_SPAM)
            print('❤️ ❤️ ❤️ I LOVE YOU!!!!!! KEEP GOING 777 ❤️ ❤️ ❤️')
            print(LOVE_SPAM)
            print()  # Add spacing
            return
            
        # For 777 responses
        if isinstance(ai_response, str) and ai_response.startswith("777"):
            print(f"{random.choice(USER_EMOJIS)} ", end="")
            cprint(username.strip(), "white", "on_blue", end="")
            print(f": {text}")
            print(f"{random.choice(AI_EMOJIS)} ", end="")
            cprint("Moon Dev AI", "white", "on_green", end="")
            print(": ", end="")
            cprint(ai_response, "white", "on_cyan")
            print()  # Add spacing
            return
            
        # For normal messages (ai_response is True)
        if ai_response is True:
            print(f"{random.choice(USER_EMOJIS)} ", end="")
            cprint(username.strip(), "white", "on_blue", end="")
            print(f": {text}")
            print()  # Add spacing
            return
            
        # For AI responses to questions
        if isinstance(ai_response, str):
            print(f"{random.choice(USER_EMOJIS)} ", end="")
            cprint(username.strip(), "white", "on_blue", end="")
            print(f": {text}")
            print(f"{random.choice(AI_EMOJIS)} ", end="")
            cprint("Moon Dev AI", "white", "on_green", end="")
            print(f": {ai_response}")
            print()  # Add spacing

class ChatAgent:
    def __init__(self):
        """Initialize the Chat Agent"""
        cprint("\n🤖 Initializing Moon Dev's Chat Agent...", "cyan")
        
        # Remove knowledge base initialization
        self.data_dir = Path(project_root) / "src" / "data" / "chat_agent"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.chat_log_path = self.data_dir / "chat_history.csv"
        self.quotes_file_path = self.data_dir / "quotes_and_verses.txt"
        
        # Load quotes and verses into memory
        self.quotes_and_verses = self._load_quotes_and_verses()
        
        # Initialize chat memory
        self.chat_memory = []
        
        # Create chat log if it doesn't exist
        if not self.chat_log_path.exists():
            self._create_chat_log()
            
        # Debug environment variables
        for key in ["OPENAI_KEY", "ANTHROPIC_KEY", "GEMINI_KEY", "GROQ_API_KEY", "DEEPSEEK_KEY", "YOUTUBE_API_KEY"]:
            if os.getenv(key):
                cprint(f"✅ Found {key}", "green")
            else:
                cprint(f"❌ Missing {key}", "red")
        
        # Initialize model using factory
        self.model_factory = model_factory
        self.model = self.model_factory.get_model(MODEL_TYPE, MODEL_NAME)
        
        if not self.model:
            raise ValueError(f"🚨 Could not initialize {MODEL_TYPE} {MODEL_NAME} model! Check API key and model availability.")
        
        self._announce_model()
        
        # Add leaderboard tracking
        self.chat_count_since_last_leaderboard = 0
        self.leaderboard_chat_interval = LEADERBOARD_INTERVAL  # Use the constant we defined (10)
        
        # Initialize Restream handler
        cprint("\n🔄 Initializing Restream...", "cyan")
        restream_id = os.getenv("RESTREAM_CLIENT_ID")
        restream_secret = os.getenv("RESTREAM_CLIENT_SECRET")
        
        if not restream_id or not restream_secret:
            cprint("❌ Missing Restream credentials in .env!", "red")
            raise ValueError("Missing Restream credentials!")
            
        self.restream_handler = RestreamChatHandler(restream_id, restream_secret)
        self.restream_handler.set_chat_agent(self)
        self.restream_handler.connect()
        cprint("🎮 Restream chat integration enabled!", "green")
        
        cprint("🎯 Moon Dev's Chat Agent initialized!", "green")
        
        # Add tracking for 777 counts
        self.daily_777_counts = {}  # Format: {username: {'count': int, 'last_reset': datetime}}
        
    def _create_chat_log(self):
        """Create empty chat history CSV with all required columns"""
        try:
            # Create with all required columns
            df = pd.DataFrame(columns=['timestamp', 'user', 'message', 'score'])
            # Ensure directory exists
            self.chat_log_path.parent.mkdir(parents=True, exist_ok=True)
            # Save with index=False to avoid extra column
            df.to_csv(self.chat_log_path, index=False)
            cprint("📝 Created fresh chat history log!", "green")
        except Exception as e:
            cprint(f"❌ Error creating chat log: {str(e)}", "red")
        
    def _announce_model(self):
        """Announce current model with eye-catching formatting"""
        model_msg = f"🤖 USING MODEL: {MODEL_TYPE.upper()} - {MODEL_NAME} 🤖"
        border = "=" * (len(model_msg) + 4)
        cprint(border, 'white', 'on_blue', attrs=['bold'])
        cprint(f"  {model_msg}  ", 'white', 'on_blue', attrs=['bold'])
        cprint(border, 'white', 'on_blue', attrs=['bold'])
        
    def _log_chat(self, user, question, confidence, response):
        """Log chat interaction to CSV silently"""
        try:
            new_data = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'user': user,
                'question': question,
                'confidence': confidence,
                'response': response
            }
            
            df = pd.read_csv(self.chat_log_path)
            df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
            df.to_csv(self.chat_log_path, index=False)
            
        except Exception as e:
            cprint(f"❌ Error logging chat: {str(e)}", "red")
            
    def _update_chat_memory(self, message):
        """Update the chat memory with new message"""
        self.chat_memory.append(message)
        if len(self.chat_memory) > CHAT_MEMORY_SIZE:
            self.chat_memory.pop(0)  # Remove oldest message

    def _get_random_lucky_emojis(self, count=3):
        """Get random lucky emojis for 777 responses"""
        return ' '.join(random.sample(LUCKY_EMOJIS, count))

    def _should_skip_response(self, message):
        """Check if message should be skipped for response"""
        # Never skip 777 messages
        if message.strip() == "777":
            return False
        
        # Skip if empty
        if not message.strip():
            return True
        
        # Skip if too short
        if len(message.strip()) < MIN_CHARS_FOR_RESPONSE:
            return True
        
        return False

    def _display_chat(self, username, text, ai_response):
        """Display chat with colored formatting
        ai_response can be:
        - string starting with 777: 777 response
        - string with 💖: negativity response (don't show original message)
        - True: normal message to display
        - string: AI response to question
        - None: skip displaying
        """
        if not ai_response:
            return
            
        # Check if this is a negativity response (contains both username and LOVE_SPAM)
        if isinstance(ai_response, str) and "💖" in ai_response and LOVE_SPAM in ai_response:
            # For negative messages, ONLY show the hearts and username, not the original message
            print(f"{random.choice(USER_EMOJIS)} ", end="")
            username_part = ai_response.split('\n')[0]
            cprint(username_part, "white", "on_magenta")
            print(LOVE_SPAM)
            print()  # Add spacing
            return
            
        # For 777 responses
        if isinstance(ai_response, str) and ai_response.startswith("777"):
            print(f"{random.choice(USER_EMOJIS)} ", end="")
            cprint(username.strip(), "white", "on_blue", end="")
            print(f": {text}")
            print(f"{random.choice(AI_EMOJIS)} ", end="")
            cprint("Moon Dev AI", "white", "on_green", end="")
            print(": ", end="")
            cprint(ai_response, "white", "on_cyan")
            print()  # Add spacing
            return
            
        # For normal messages (ai_response is True)
        if ai_response is True:
            print(f"{random.choice(USER_EMOJIS)} ", end="")
            cprint(username.strip(), "white", "on_blue", end="")
            print(f": {text}")
            print()  # Add spacing
            return
            
        # For AI responses to questions
        if isinstance(ai_response, str):
            print(f"{random.choice(USER_EMOJIS)} ", end="")
            cprint(username.strip(), "white", "on_blue", end="")
            print(f": {text}")
            print(f"{random.choice(AI_EMOJIS)} ", end="")
            cprint("Moon Dev AI", "white", "on_green", end="")
            print(f": {ai_response}")
            print()  # Add spacing

    def _get_daily_777_count(self, username):
        """Get and update the user's daily 777 count"""
        today = datetime.now().date()
        
        if username not in self.daily_777_counts:
            self.daily_777_counts[username] = {'count': 0, 'last_reset': today}
            
        # Check if we need to reset the count for a new day
        user_data = self.daily_777_counts[username]
        if user_data['last_reset'] != today:
            user_data['count'] = 0
            user_data['last_reset'] = today
            
        return user_data['count']
        
    def _load_quotes_and_verses(self):
        """Load quotes, verses and parables from file"""
        try:
            if not self.quotes_file_path.exists():
                cprint("❌ quotes_and_verses.txt not found!", "red")
                return []
                
            with open(self.quotes_file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            # Filter out empty lines, comments and section headers
            valid_lines = [line.strip() for line in lines 
                         if line.strip() and not line.startswith('#')]
            
            if not valid_lines:
                cprint("⚠️ No quotes/verses found in file!", "yellow")
                return []
                
            cprint(f"✨ Loaded {len(valid_lines)} quotes/verses/parables!", "green")
            return valid_lines
            
        except Exception as e:
            cprint(f"❌ Error loading quotes: {str(e)}", "red")
            return []

    def _get_random_quote_or_verse(self):
        """Get a random quote, verse or parable"""
        if not self.quotes_and_verses:
            return "🌟 Stay positive and keep pushing forward! - Moon Dev"
            
        return random.choice(self.quotes_and_verses)

    def process_question(self, user, question):
        """Process incoming chat messages with the following flow:
        1. Check if it's 777
        2. If not 777, check for negativity
        3. If not negative and contains ?, send to AI
        4. If not negative and no ?, just display the message
        """
        # Add API key warning
        if any(key_word in question.lower() for key_word in ['api', 'key', 'token', 'secret']):
            return "⚠️ For security reasons, I cannot process messages containing API keys or tokens. Please never share API keys in chat! 🔒"
            
        retries = 0
        max_retries = 3
        
        while retries < max_retries:
            try:
                # 1. Check for 777 FIRST
                if question.strip() == "777":
                    # Check daily limit and add points
                    daily_count = self._get_daily_777_count(user)
                    if daily_count < MAX_777_PER_DAY:
                        self.daily_777_counts[user]['count'] += 1
                        self.save_chat_history(user, question, POINTS_PER_777)
                    
                    # Get random quote/verse/parable from our file
                    response = self._get_random_quote_or_verse()
                    emojis = self._get_random_lucky_emojis()
                    return f"777 {emojis}\n{response}"

                # 2. Check negativity for ALL non-777 messages
                negativity_prompt = NEGATIVITY_CHECK_PROMPT.format(message=question)
                try:
                    negativity_response = self.model.generate_response(
                        system_prompt=negativity_prompt,
                        user_content=question,
                        temperature=0.3,
                        max_tokens=5
                    ).content.strip().lower()
                    
                    if negativity_response == 'true':
                        self.save_chat_history(user, question, -1)
                        return f"💖 {user} 💖\n{LOVE_SPAM}"
                except Exception as e:
                    if "503" in str(e):
                        retries += 1
                        time.sleep(2)
                        continue
                    cprint(f"❌ Error checking negativity: {str(e)}", "red")
                
                # 3. For non-negative messages, check for questions
                if "?" in question:
                    try:
                        response = self.model.generate_response(
                            system_prompt=CHAT_PROMPT.format(question=question),
                            user_content=question,
                            temperature=0.7,
                            max_tokens=MAX_RESPONSE_TOKENS
                        )
                        return response.content.strip()
                    except Exception as e:
                        if "503" in str(e):
                            retries += 1
                            time.sleep(2)
                            continue
                        cprint(f"❌ Error processing question: {str(e)}", "red")
                
                # 4. For non-negative, non-question messages, return True to display the message
                return True
                
            except Exception as e:
                cprint(f"❌ Error in process_question: {str(e)}", "red")
                retries += 1
                time.sleep(1)
                
        return None

    def _get_leaderboard(self):
        """
        🌙 MOON DEV SAYS: Let's see who's leading the chat! 🏆
        """
        try:
            # Read chat history
            df = pd.read_csv(self.chat_log_path)
            
            # Check if score column exists
            if not df.empty and 'score' in df.columns:
                scores = df.groupby('user')['score'].sum().sort_values(ascending=False)
                return scores.head(3)  # Get top 3
            return pd.Series()
        except Exception as e:
            cprint(f"❌ Error getting leaderboard: {str(e)}", "red")
            return pd.Series()
            
    def _format_leaderboard_message(self, scores):
        """
        🌙 MOON DEV SAYS: Format that leaderboard with style! 🎨
        """
        if len(scores) == 0:
            return None
            
        message = "⭐️ 🌟 💫 CHAT CHAMPS 💫 🌟 ⭐️ "
        
        # Simple rank emojis
        rank_decorations = [
            "👑", # First place
            "🥈", # Second place
            "🥉"  # Third place
        ]
        
        # Add some randomized bonus emojis
        bonus_emojis = ["🎯", "🎲", "🎮", "🕹️"]
        
        message += "\n"  # Add spacing after header
        
        for i, (user, score) in enumerate(scores.items()):
            random_bonus = random.choice(bonus_emojis)
            message += f"\n{rank_decorations[i]} {user}: {score} points {random_bonus}"
        
        message += "\n\n ⭐️ Winner Gets Free Bootcamp ⭐️ "
        return message.strip()
        
    def _show_leaderboard(self):
        """
        🌙 MOON DEV SAYS: Time to show off those chat skills! 🚀
        """
        scores = self._get_leaderboard()
        if len(scores) == 0:
            return
            
        message = self._format_leaderboard_message(scores)
        print(f"\n{message}\n")  # Display in console
        # You can add code here to post to chat if needed
        
    def run(self):
        """Main loop for monitoring chat"""
        cprint("\n🎯 Moon Dev's Chat Agent starting...", "cyan", attrs=['bold'])
        print()
        
        cprint(f"📝 Will process last {DEFAULT_INITIAL_CHATS} messages on startup", "cyan")
        cprint(f"⏰ Leaderboard will show every {LEADERBOARD_INTERVAL} chats", "cyan")
        
        # Show initial leaderboard
        cprint("\n🏆 Initial Leaderboard:", "cyan")
        self._show_leaderboard()
        self.chat_count_since_last_leaderboard = 0
        
        # Start Restream handler and keep main thread alive
        try:
            while True:
                time.sleep(RESTREAM_CHECK_INTERVAL)
                
                # Show leaderboard every LEADERBOARD_INTERVAL chats
                if self.chat_count_since_last_leaderboard >= LEADERBOARD_INTERVAL:
                    #cprint("\n🏆 Time for the leaderboard!", "cyan")
                    self._show_leaderboard()
                    self.chat_count_since_last_leaderboard = 0
                    print()  # Add spacing after leaderboard
                
        except KeyboardInterrupt:
            raise
        except Exception as e:
            cprint(f"❌ Error: {str(e)}", "red")
            time.sleep(RESTREAM_CHECK_INTERVAL)

    def _get_user_chat_history(self, username):
        """
        🌙 MOON DEV SAYS: Let's get that chat history! 📚
        """
        try:
            df = pd.read_csv(self.chat_log_path)
            if not df.empty and 'message' in df.columns:
                return df[df['user'] == username]['message'].tolist()
            return []
        except Exception as e:
            cprint(f"❌ Error getting user chat history: {str(e)}", "red")
            return []

    def save_chat_history(self, username, message, score):
        """
        🌙 MOON DEV SAYS: Saving chat history with scores! 📊
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Check if file exists and has headers
        file_exists = os.path.exists(self.chat_log_path)
        
        with open(self.chat_log_path, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                # Write headers if file doesn't exist
                writer.writerow(['timestamp', 'user', 'message', 'score'])
            writer.writerow([timestamp, username, message, score])

def is_meaningful_chat(new_message, chat_history, threshold=0.3):
    """
    🌙 MOON DEV SAYS: Let's keep chats meaningful and fun!
    """
    # Ensure new_message is a string
    new_message = str(new_message)
    
    if len(new_message.split()) < 3:  # Very short messages
        return False
        
    if not chat_history:
        return True
        
    # Convert all chat history items to strings
    chat_history = [str(msg) for msg in chat_history]
    
    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(chat_history + [new_message])
    similarities = cosine_similarity(tfidf_matrix[-1], tfidf_matrix[:-1])
    
    if np.max(similarities) > threshold:
        return False
        
    return True

def update_chat_score(username, message, chat_history):
    """
    🌙 MOON DEV SAYS: Let's track those chat points! 
    """
    # Skip if message isn't meaningful
    if not is_meaningful_chat(message, chat_history):
        return 0
        
    # Give 1 point for meaningful messages
    # Note: Negative points are handled by AI negativity check
    # 777 points are handled separately
    return 1

if __name__ == "__main__":
    try:
        agent = ChatAgent()
        agent.run()
    except KeyboardInterrupt:
        cprint("\n👋 Chat Agent shutting down gracefully...", "yellow")
    except Exception as e:
        cprint(f"\n❌ Fatal error: {str(e)}", "red")
