import os
from dotenv import load_dotenv

load_dotenv()

def main():
    try:
        # Import inside the try so import-time errors are also caught
        from telegram.ext import Application

        print("Building Application with token from .env (may be empty)...")
        app = Application.builder().token(os.getenv("TELEGRAM_TOKEN")).build()
        print("Application built successfully:\n", app)
    except Exception as e:
        import traceback
        print("Error building Application:", e)
        traceback.print_exc()

if __name__ == '__main__':
    main()
