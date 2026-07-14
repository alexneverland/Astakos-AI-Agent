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

## ⚙️ Step 4: Run the Web Setup Wizard

You **do not** need to manually create configuration files or `.env` secrets! Astakos comes with an automated Web Setup Wizard.

- If you are on **Windows**, double click the file **`start_astakos.bat`**.
- Alternatively, run from the terminal:
  ```bash
  python boot.py
  ```

Because it's your first time running it, Astakos will detect that your settings are missing and will automatically launch the **Web Setup Wizard**. 

1. Open your browser to `http://localhost:8000` (or the URL shown in your terminal).
2. Follow the on-screen instructions to set up your API keys, your name, and your assistant's Persona.
3. The wizard will automatically create all the necessary files (`.env`, `astakos_settings.json`, etc.) safely on your machine!

---

## 🚀 Step 5: Start Chatting!

Once the wizard completes, Astakos will start automatically with your new settings.

1. Open Telegram.
2. Find your Bot (which you configured in the wizard) and send it a "Hello!" message. 🦞

*(If you ever want to re-run the wizard in the future, you can start Astakos with `python boot.py --setup` or simply delete your `.env` file).*
