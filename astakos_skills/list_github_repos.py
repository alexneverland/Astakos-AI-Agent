# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import requests
import os

# Mastro-Security: Τραβάμε το token με ασφάλεια από το config
try:
    from config import GITHUB_TOKEN
except ImportError:
    GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")

USERNAME = 'alexneverland'

def list_github_repositories(username, pat):
    if not pat:
        print("❌ Σφάλμα: Το GITHUB_TOKEN δεν βρέθηκε στο config.py ή στο περιβάλλον.")
        return

    url = f'https://api.github.com/user/repos'
    headers = {
        'Authorization': f'token {pat}',
        'Accept': 'application/vnd.github.v3+json'
    }

    all_repos = []
    page = 1
    while True:
        params = {'page': page, 'per_page': 100}
        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            repos = response.json()
            if not repos:
                break
            all_repos.extend(repos)
            page += 1
        else:
            print(f"Error fetching repositories: {response.status_code}")
            print(response.json())
            return

    print(f"GitHub Repositories for {username}:")
    if not all_repos:
        print("- No repositories found or accessible with the provided token.")
    for repo in all_repos:
        visibility = "(Private)" if repo['private'] else "(Public)"
        print(f"- {repo['name']} {visibility}")

if __name__ == '__main__':
    list_github_repositories(USERNAME, GITHUB_TOKEN)