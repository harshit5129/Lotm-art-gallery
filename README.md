# Discord Art Gallery Manager

A powerful CLI/TUI tool for managing Discord images with support for downloading, transferring between servers, and uploading to Telegram. Features batch processing to minimize disk usage and supports both user and bot authentication.

## Features

- **Download Images**: Download images from specific channels, multiple channels, or entire servers
- **Transfer Between Discord Servers**: Move images between channels/servers with optional text preservation
- **Telegram Integration**: Upload images directly to Telegram channels/groups (single or album mode)
- **Multi-Channel Selection**: Select multiple channels at once using comma-separated indices or "all" keyword
- **Dual Authentication**: Supports both Discord user tokens and bot tokens
- **Batch Processing**: Processes images in configurable batches to minimize disk usage
- **Progress Tracking**: Rich console UI with progress bars and color-coded output
- **Rate Limit Handling**: Exponential backoff with jitter for Discord and Telegram API rate limits

## Setup

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your credentials
```

## Environment Variables

Create a `.env` file with the following variables:

```bash
# Discord Authentication (choose one)
DISCORD_AUTH_TOKEN=your_user_auth_token_here       # For user authentication
DISCORD_BOT_TOKEN=your_bot_token_here              # For bot authentication

# Telegram (optional - for Telegram upload features)
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=-1001234567890

# General Settings
MEDIA_DIRECTORY=extracted_media                      # Base directory for downloads
```

### Getting Tokens

**Discord User Token:**
1. Open Discord in browser
2. Open Developer Tools (F12) → Network tab
3. Send any message and look for `messages` request
4. Copy the `authorization` header value

**Discord Bot Token:**
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application → Bot → Add Bot
3. Copy the bot token
4. Enable "Message Content Intent" in Bot settings

**Telegram Bot Token:**
1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Create a new bot with `/newbot`
3. Copy the bot token

**Telegram Chat ID:**
1. Add your bot to the target channel/group
2. Send a test message
3. Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
4. Look for `"chat":{"id":-1001234567890}`

## Usage

### Interactive Mode

```bash
# Start interactive mode (will prompt for auth method)
uv run main.py --interactive
```

**Menu Options:**
1. **List Servers** - View all accessible Discord servers
2. **Download Images** - Download from specific/multiple/all channels
3. **Transfer Images** - Transfer between Discord servers or to Telegram

### Command-Line Mode

```bash
# Specify authentication method
uv run main.py --auth-method user list-servers    # User token
uv run main.py --auth-method bot list-servers     # Bot token

# List channels in a server
uv run main.py list-channels --guild-id <server_id>

# Download from a channel
uv run main.py download --channel-id <channel_id> --output-dir <directory>

# Transfer images to a Discord channel
uv run main.py transfer --source-dir <directory> --target-channel-id <channel_id>

# Upload local directory to Telegram
uv run main.py telegram upload \
  --source-dir ./images \
  --bot-token <telegram_token> \
  --chat-id <chat_id> \
  --albums

# Transfer Discord channel to Telegram
uv run main.py telegram transfer \
  --channel-id <discord_channel_id> \
  --telegram-bot-token <token> \
  --chat-id <chat_id> \
  --include-text \
  --albums
```

## Key Features Explained

### Multi-Channel Selection

When downloading from multiple channels:
- Enter comma-separated numbers: `1,3,5,7`
- Type `all` to select all channels
- Type `0` to cancel

### Telegram Albums

- **Single Photo Mode**: Uploads images one by one with individual captions
- **Album Mode** (`--albums`): Groups up to 10 photos per message (only first image can have caption)
- Files over 10MB are automatically skipped with a warning

### Batch Processing

All transfers use configurable batch sizes (default: 5 images) to minimize disk usage:
- Downloads images in batches
- Processes and uploads
- Cleans up before next batch
- Maximum disk usage: ~5 images at a time

### Authentication Methods

**User Token (`DISCORD_AUTH_TOKEN`):**
- Acts as your personal Discord account
- Can access all servers you're a member of
- Full permissions based on your account

**Bot Token (`DISCORD_BOT_TOKEN`):**
- Acts as a bot application
- Requires bot to be added to servers with appropriate permissions
- More suitable for automated workflows

## Architecture

### Core Components

- **Config** (`@dataclass`): Centralized configuration with Discord/Telegram limits
- **ChannelType** (`IntEnum`): Discord channel type constants
- **make_request()**: Centralized API handler with rate limit support
- **transfer_images_batch()**: Core transfer logic with disk optimization
- **Telegram Functions**: Full Telegram Bot API integration

### Data Classes

```python
Config:
  - API_BASE_URL: str = "https://discord.com/api/v9"
  - REQUEST_TIMEOUT: int = 30
  - MESSAGE_LIMIT: int = 100
  - IMAGE_EXTENSIONS: frozenset
  - TRANSFER_BATCH_SIZE: int = 5
  - TELEGRAM_MAX_ALBUM_SIZE: int = 10
  - TELEGRAM_PHOTO_SIZE_LIMIT: int = 10MB
```

## Important Notes

- **Disk Usage**: Batch processing limits disk usage to ~5 images at a time
- **Rate Limits**: Automatic retry with exponential backoff and jitter
- **Image Counting**: Disabled by default in channel selection for performance
- **Temporary Files**: Automatically cleaned up after transfers
- **TTY Required**: Interactive mode requires a terminal; use CLI args for scripts
- **Telegram Limits**: Photo files >10MB are skipped; captions truncated to 1024 chars

## CLI Reference

### Global Options

| Option | Description |
|--------|-------------|
| `--interactive` | Run in interactive TUI mode |
| `--auth-method {user,bot}` | Authentication method (overrides auto-detection) |

### Commands

| Command | Description |
|---------|-------------|
| `list-servers` | List all accessible Discord servers |
| `list-channels --guild-id ID` | List channels in a server |
| `download --channel-id ID` | Download images from a channel |
| `transfer --source-dir DIR --target-channel-id ID` | Upload images to a channel |
| `telegram upload --source-dir DIR` | Upload to Telegram |
| `telegram transfer --channel-id ID` | Transfer Discord to Telegram |

### Telegram Options

| Option | Description |
|--------|-------------|
| `--bot-token TOKEN` | Telegram bot token |
| `--chat-id ID` | Target Telegram chat/channel ID |
| `--telegram-bot-token TOKEN` | Telegram token for transfer command |
| `--include-text` | Include Discord message text as photo captions |
| `--albums` | Send as albums (groups of up to 10 photos) |

## Development

```bash
# Check syntax
python3 -m py_compile main.py

# Run with uv
source $HOME/.local/bin/env
uv run main.py --help

# Install dev dependencies (if any)
uv pip install -e ".[dev]"
```

## Troubleshooting

**"No guilds found" error:**
- Check that your token is valid
- For bot tokens, ensure the bot is added to the server
- For user tokens, ensure you're a member of the server

**"Failed to verify Telegram chat" error:**
- Verify bot token is correct
- Ensure bot is added to the target channel/group
- Check that chat ID includes the `-100` prefix for channels

**Rate limiting:**
- The tool automatically handles rate limits with exponential backoff
- For large transfers, expect delays when hitting API limits

**Image files not being detected:**
- Supported formats: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`, `.tiff`
- Files are case-insensitive

## License

MIT License - See LICENSE file for details
