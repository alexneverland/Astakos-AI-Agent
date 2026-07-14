# 🦞 Astakos AI - Beginner's Setup Guide

Welcome to the Astakos AI setup guide! Even if you have never written code before, by following the steps below one by one, you will be able to run your personal AI assistant.

Currently, this guide focuses on using **Google Cloud Vertex AI** (which is the most professional and robust connection method).

---

## 🛠️ Step 1: Prerequisites

Before we start, make sure you have installed the following on your computer:
1. **Python (version 3.11 or newer):** During installation (especially on Windows), make sure to check the box **"Add Python to PATH"**.
2. **Google Cloud CLI:** Download and install the Google tool from [here](https://cloud.google.com/sdk/docs/install).

---

## 📦 Step 2: Download and Install Libraries

1. Open the terminal (Command Prompt or PowerShell on Windows, Terminal on Mac/Linux) and navigate to the folder where you downloaded the code.
2. Run the following command to install all the necessary "tools" that Astakos needs:
   ```bash
   pip install -r requirements.txt
   ```

---

## 🔑 Step 3: Connect to Google Cloud (Vertex AI)

In order for Astakos to think (via Gemini models), we must grant it access to your Google Cloud account:
1. Open the terminal again (Command Prompt/PowerShell).
2. Run the command:
   ```bash
   gcloud auth application-default login
   ```
3. A browser window will open. Log in with your Google account and grant the necessary permissions. That's it! Now your computer has the access key.

---

## ⚙️ Step 4: Configuration Files (Renaming)

Inside the Astakos folder you will see some files ending in `.example`. You need to remove this extension and adapt them to your preferences:

1. **`astakos_settings.json.example` ➡️ `astakos_settings.json`**
   - Open it with a simple Notepad.
   - Change the names (e.g., `USER_NAME`, `KID1_NAME`) so Astakos knows how to call you.
2. **`astakos_custom_intents.json.example` ➡️ `astakos_custom_intents.json`**
   - Simply rename it. It contains rules on how Astakos understands messages.
3. **`persona.md.example` ➡️ `persona.md`**
   - The personality of Astakos is described here. You can read it or add your own behavioral instructions.

---

## 🔐 Step 5: The .env File (Secret Keys)

Create a new, entirely empty file named **`.env`** (pay attention to the dot in front) inside the main Astakos folder.
Open it with Notepad and paste the following, replacing the placeholders with your own details:

```env
# --- Core Settings (Google Cloud & Telegram) ---
PROJECT_ID=your-gcp-project-id
LOCATION=us-central1
TELEGRAM_TOKEN=your-telegram-bot-token
TELEGRAM_CHAT_ID=your-chat-id

# --- Optional Settings (For extra features) ---
# If you DO NOT use gcloud auth (Step 3), put your API key here:
GEMINI_API_KEY=your-gemini-api-key

# GitHub (For the Tech Agent)
GITHUB_TOKEN=your-github-token

# Email (For the Mail Agent)
EMAIL_ADDRESS=your-email@example.com
EMAIL_PASSWORD=your-app-password

# Smart Home (Vacuum)
VACUUM_IP=192.168.1.100
VACUUM_TOKEN=your-vacuum-token

# LinkedIn (For posting)
LINKEDIN_TOKEN=your-linkedin-token
```
*(The only **absolutely necessary** variables to start Astakos are `PROJECT_ID`, `LOCATION`, and the two Telegram variables. If you don't know how to create a Bot on Telegram, search for `@BotFather`, send `/newbot` and get your `TELEGRAM_TOKEN`).*

---

## 🚀 Step 6: Start Astakos!

You are ready! To start your personal assistant:
- If you are on **Windows**, double click the file **`start_astakos.bat`**.
- Alternatively, run from the terminal:
  ```bash
  python run_telegram.py
  ```

Once you see in the terminal that Astakos has started, open Telegram, find your Bot and send it a "Hello!" message. 🦞
