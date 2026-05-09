# ================================================================
# Project: Astakos AI Agent 🦞
# Developer: Lazaros (Piston-7)
# Description: Modular LLM-agnostic multi-agent framework
# Copyright (c) 2026 - All Rights Reserved
# ================================================================

import os

def list_parent_directory():
    try:
        parent_dir_contents = os.listdir('..')
        print("Contents of the parent directory:")
        for item in parent_dir_contents:
            print(item)
    except FileNotFoundError:
        print("Error: Parent directory not found.")
    except PermissionError:
        print("Error: Permission denied to access the parent directory.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    list_parent_directory()
