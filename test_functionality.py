#!/usr/bin/env python3
"""
Test script for Mistral AI Bot functionality
Tests core functions without requiring Telegram bot setup
"""

import os
import sys

# Test if we can import all modules without errors
def test_imports():
    print("🔍 Testing imports...")
    try:
        import mistral_client_official
        import fast_main
        import conversation_handlers
        import database_manager
        print("✅ All imports successful!")
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False

# Test environment setup
def test_environment():
    print("\n🔍 Testing environment...")
    
    # Check for required environment variables
    required_vars = ["MISTRAL_API_KEY", "TELEGRAM_BOT_TOKEN"]
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print(f"⚠️  Missing environment variables: {', '.join(missing_vars)}")
        print("💡 Create a .env file or set these environment variables")
        return False
    else:
        print("✅ All required environment variables are set!")
        return True

# Test database initialization
def test_database():
    print("\n🔍 Testing database...")
    try:
        from database_manager import initialize_database
        initialize_database()
        print("✅ Database initialization successful!")
        return True
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        return False

# Test Mistral client functions (without API calls)
def test_mistral_functions():
    print("\n🔍 Testing Mistral client functions...")
    try:
        from mistral_client_official import (
            create_websearch_agent, create_code_agent, create_image_agent,
            list_libraries, list_agents
        )
        print("✅ Mistral client functions loaded successfully!")
        return True
    except Exception as e:
        print(f"❌ Mistral functions test failed: {e}")
        return False

# Test conversation handlers
def test_handlers():
    print("\n🔍 Testing conversation handlers...")
    try:
        from conversation_handlers import (
            show_admin_menu, library_management_handler, agent_management_handler
        )
        print("✅ Conversation handlers loaded successfully!")
        return True
    except Exception as e:
        print(f"❌ Handlers test failed: {e}")
        return False

# Main test runner
def main():
    print("🚀 Mistral AI Bot - Functionality Test")
    print("=" * 50)
    
    tests = [
        ("Import Test", test_imports),
        ("Environment Test", test_environment), 
        ("Database Test", test_database),
        ("Mistral Functions Test", test_mistral_functions),
        ("Handlers Test", test_handlers)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        result = test_func()
        if result:
            passed += 1
    
    print(f"\n📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Your bot is ready to run.")
        print("\n🚀 Next steps:")
        print("1. Run: python fast_main.py")
        print("2. Test /admin command for library/agent management")
        print("3. Test /doc command for document search")
        print("4. Test /websearch and /code commands")
    else:
        print("⚠️  Some tests failed. Please fix the issues before running the bot.")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
