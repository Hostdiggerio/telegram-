#!/usr/bin/env python3
"""
Dependency installation script for Mistral AI Bot with Agents & Libraries
Run this script to install all dependencies with correct versions.
"""

import subprocess
import sys
import os

def run_command(command, description):
    """Run a command and handle errors gracefully"""
    print(f"\n🔄 {description}...")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed:")
        print(f"   Error: {e.stderr}")
        return False

def main():
    print("🚀 Installing Mistral AI Bot Dependencies")
    print("=" * 50)
    
    # Check if we're in a virtual environment
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print("✅ Virtual environment detected")
    else:
        print("⚠️  Warning: Virtual environment not detected!")
        response = input("Continue anyway? (y/N): ")
        if response.lower() != 'y':
            print("Exiting. Please activate your virtual environment first.")
            return
    
    # Upgrade pip first
    if not run_command(f"{sys.executable} -m pip install --upgrade pip", "Upgrading pip"):
        return
    
    # Install specific version of mistralai client
    if not run_command(f"{sys.executable} -m pip install 'mistralai>=1.0.0'", "Installing Mistral AI client"):
        return
    
    # Install from requirements.txt
    if os.path.exists("requirements.txt"):
        if not run_command(f"{sys.executable} -m pip install -r requirements.txt", "Installing other dependencies"):
            return
    else:
        print("⚠️  requirements.txt not found, installing core dependencies manually")
        dependencies = [
            "python-telegram-bot==22.3",
            "requests>=2.31.0", 
            "python-dotenv>=1.0.0",
            "pytz>=2023.3",
            "typing-extensions>=4.0.0",
            "sqlalchemy>=2.0.0",
            "psycopg2-binary>=2.9.0"
        ]
        
        for dep in dependencies:
            if not run_command(f"{sys.executable} -m pip install '{dep}'", f"Installing {dep.split('=')[0]}"):
                return
    
    print("\n🎉 All dependencies installed successfully!")
    print("\n📝 Next steps:")
    print("1. Create a .env file with your API keys:")
    print("   MISTRAL_API_KEY=your_mistral_api_key_here")
    print("   TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here")
    print("2. Run the bot: python fast_main.py")

if __name__ == "__main__":
    main()
