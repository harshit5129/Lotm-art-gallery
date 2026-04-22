# Agent Instructions

## Project Overview

Discord Art Gallery Manager - CLI tool for downloading/transferring Discord images with batch processing to minimize disk usage.

## Critical Setup

```bash
# uv must be in PATH for all commands
source $HOME/.local/bin/env

# Run any command
uv run main.py <args>
```

## Environment

- Python 3.12+ (managed by uv)
- Dependencies: requests, python-dotenv, rich
- Config via `.env` file (DISCORD_AUTH_TOKEN required)

## Key Architecture

**Single-file structure** (`main.py`):
- `Config` class: All constants (API URLs, timeouts, batch sizes)
- `ChannelType` enum: Discord channel types (0=Text, 2=Voice, 4=Category, 5=News)
- `make_request()`: Centralized API handler with `DiscordAPIError` exception
- `transfer_images_batch()`: Core transfer with disk-space optimization
- Interactive menu system with numbered selections

## Important Constraints

1. **Disk Usage**: `TRANSFER_BATCH_SIZE = 5` - processes 5 images at a time, deletes before next batch
2. **No Image Counting**: Channel selection skips `count_images_in_channel()` for performance (set `count_images=False`)
3. **TTY Required**: Interactive mode checks `sys.stdin.isatty()` - use CLI args for automation
4. **No Rate Limiting**: May hit Discord API limits on large transfers

## Common Patterns

**API Request Pattern**:
```python
try:
    return make_request(url, method="GET", headers=headers, params=params)
except DiscordAPIError as e:
    console.print(f"[red]Error: {e}[/red]")
    return []
```

**Selection Pattern**:
```python
selected_guild = select_server(guilds)  # Returns Optional[Dict]
if not selected_guild:
    return  # User cancelled
```

**Transfer Pattern**:
```python
temp_dir = Path(media_base_dir) / "temp_transfer"
temp_dir.mkdir(parents=True, exist_ok=True)
stats = transfer_images_batch(source_id, target_id, auth_token, temp_dir)
# Cleanup
for file in temp_dir.glob("*.*"):
    file.unlink()
temp_dir.rmdir()
```

## Code Organization

- Lines 1-45: Imports, enums, Config class
- Lines 47-82: Environment, headers, API request handler
- Lines 84-143: API functions (guilds, channels, messages, counting)
- Lines 145-178: Download/upload functions
- Lines 180-255: Message retrieval with JSON export
- Lines 258-323: Display functions (tables, channels)
- Lines 325-358: Selection helpers
- Lines 361-475: List servers menu with transfer options
- Lines 478-558: Download menu (channel or whole server)
- Lines 561-686: Batch transfer with text support
- Lines 689-1007: Transfer menu (local, server, whole server)
- Lines 1010-1097: Interactive menu and CLI handlers
- Lines 1100-1145: Main entry point

## Gotchas

1. **Function Signature Mismatch**: Menu functions must accept `(auth_token, media_base_dir)` - easy to miss when adding new menus
2. **Image Counting Performance**: `count_images_in_channel()` iterates ALL messages - never call in loops
3. **Batch Processing**: Always use `transfer_images_batch()` for server-to-server transfers to save disk space
4. **Channel Type Filtering**: Use `Config.TEXT_CHANNEL_TYPES` set, not hardcoded values
5. **Progress Context**: Rich Progress must be created with `console=console` parameter

## Testing

No test framework configured. Manual testing:
```bash
# Syntax check
python3 -m py_compile main.py

# Interactive test
uv run main.py --interactive
```

## When Adding Features

1. Add to `Config` class if it's a constant
2. Use `make_request()` for all Discord API calls
3. Handle `DiscordAPIError` exceptions
4. Use Rich console for output: `console.print("[green]Success[/green]")`
5. For transfers, use batch processing to minimize disk usage
6. Update menu options in `interactive_menu()` dictionary
