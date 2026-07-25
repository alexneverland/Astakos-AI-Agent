import os
import sys
import subprocess
from dotenv import load_dotenv

from core.version_check import check_for_updates


def is_configured(run_mode="cli"):
    """Check if the necessary configuration exists to start Astakos."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return False

    # Load env temporarily to check keys
    load_dotenv(env_path)

    # We need an API Key for the chosen provider
    provider = os.getenv("LLM_PROVIDER", "vertex").lower()
    if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        return False
    if provider == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
        return False
    if provider == "gemini" and not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        return False
    if provider == "vertex" and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        return False

    return True


if __name__ == "__main__":
    # Read-only and non-blocking: failures never prevent Astakos from starting.
    check_for_updates()

    force_setup = "--setup" in sys.argv
    run_mode = "server" if "--server" in sys.argv else "cli"
    if force_setup or not is_configured(run_mode=run_mode):
        print("\n\033[93m" + "=" * 60)
        print("🦞 Astakos AI Agent is unconfigured or missing critical keys.")
        print("Starting Setup Wizard...")
        print("Please open: http://localhost:8000 in your browser.")
        print("=" * 60 + "\033[0m\n")

        # Run setup_wizard as a subprocess so when it exits, boot.py continues
        subprocess.run([sys.executable, "-m", "api.setup_wizard"])

        print("\n\033[92mConfiguration completed. Checking again...\033[0m\n")

    # Double check if configured now
    if is_configured(run_mode=run_mode):
        print("\033[92m[Boot]: Starting Astakos Systems...\033[0m")
        if "--server" in sys.argv:
            # Start API always; start Telegram only when configured.
            api_proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "api.server:server", "--host", "0.0.0.0", "--port", "8000"]
            )

            bot_proc = None
            if os.getenv("TELEGRAM_TOKEN"):
                bot_proc = subprocess.Popen([sys.executable, "clients/telegram_bot.py"])
            else:
                print("\033[93m[Boot]: TELEGRAM_TOKEN not set - starting Web/API only.\033[0m")

            try:
                api_proc.wait()
                if bot_proc is not None:
                    bot_proc.wait()
            except KeyboardInterrupt:
                print("\n[Boot]: Graceful shutdown initiated. Waiting up to 10s for child processes...")
                try:
                    api_proc.wait(timeout=10)
                    if bot_proc is not None:
                        bot_proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    print("\033[93m[Boot]: Timeout waiting for graceful exit. Terminating processes.\033[0m")
                    api_proc.terminate()
                    if bot_proc is not None:
                        bot_proc.terminate()
        else:
            # Start main.py CLI
            subprocess.run([sys.executable, "main.py"])
    else:
        print("\033[91m[Boot]: Setup aborted or incomplete. Exiting.\033[0m")
        sys.exit(1)
