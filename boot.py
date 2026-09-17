import os
import sys
import subprocess
import time
from dotenv import load_dotenv

from core.version_check import check_for_updates


def is_configured(run_mode="cli"):
    """Check if the necessary configuration exists to start Astakos."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return False

    # Load env temporarily to check keys
    load_dotenv(env_path)

    from core.diagnostics import is_chat_provider_configured

    provider = os.getenv("LLM_PROVIDER", "vertex").lower()
    return is_chat_provider_configured(provider)


def start_external_transport() -> subprocess.Popen | None:
    """Start only the selected external messaging transport."""
    from core.messaging_channel import resolve_external_channel

    active_channel = resolve_external_channel()
    if active_channel == "matrix":
        print("\033[92m[Boot]: Active external channel is Matrix.\033[0m")
        return subprocess.Popen([sys.executable, "clients/matrix_bot.py"])

    if os.getenv("TELEGRAM_TOKEN"):
        return subprocess.Popen([sys.executable, "clients/telegram_bot.py"])

    print("\033[93m[Boot]: TELEGRAM_TOKEN not set - starting Web/API only.\033[0m")
    return None


def _terminate_child(process: subprocess.Popen | None) -> None:
    """Stop one still-running child without masking the original exit reason."""
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def supervise_server_processes(
    api_process: subprocess.Popen,
    external_process: subprocess.Popen | None,
    *,
    sleep=time.sleep,
) -> int:
    """Watch both server children and fail when the selected transport exits."""
    while True:
        api_exit = api_process.poll()
        if api_exit is not None:
            _terminate_child(external_process)
            return int(api_exit)

        if external_process is not None:
            external_exit = external_process.poll()
            if external_exit is not None:
                print(
                    "\033[91m[Boot]: Selected external transport stopped "
                    f"(exit={external_exit}). Stopping API.\033[0m"
                )
                _terminate_child(api_process)
                return int(external_exit) if external_exit else 1
        sleep(0.25)



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
            # Start API always and exactly one selected external transport.
            api_proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "api.server:server", "--host", "0.0.0.0", "--port", "8000"]
            )

            bot_proc = start_external_transport()

            try:
                exit_code = supervise_server_processes(api_proc, bot_proc)
            except KeyboardInterrupt:
                print("\n[Boot]: Graceful shutdown initiated. Waiting up to 10s for child processes...")
                _terminate_child(api_proc)
                _terminate_child(bot_proc)
            else:
                if exit_code:
                    sys.exit(exit_code)
        else:
            # Start main.py CLI
            subprocess.run([sys.executable, "main.py"])
    else:
        print("\033[91m[Boot]: Setup aborted or incomplete. Exiting.\033[0m")
        sys.exit(1)
