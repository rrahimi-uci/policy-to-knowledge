# Setup Guide

## Security Setup

This project uses environment variables to securely store API keys. Follow these steps to set up your environment:

### 1. Create Configuration File

Copy the example configuration file:

```bash
cp config.example.json config.json
```

### 2. Set Up Environment Variables

Create a `.env` file from the example:

```bash
cp .env.example .env
```

Then edit `.env` and add your actual API keys:

```bash
# OpenAI API Key (required)
OPENAI_API_KEY=sk-proj-your-actual-openai-key-here

# Anthropic API Key (optional, only if using Claude models)
ANTHROPIC_API_KEY=sk-ant-your-actual-anthropic-key-here
```

### 3. Get Your API Keys

#### OpenAI
1. Go to [OpenAI Platform](https://platform.openai.com/api-keys)
2. Sign in or create an account
3. Create a new API key
4. Copy the key and paste it into your `.env` file

#### Anthropic (Optional)
1. Go to [Anthropic Console](https://console.anthropic.com/settings/keys)
2. Sign in or create an account
3. Create a new API key
4. Copy the key and paste it into your `.env` file

### 4. Verify Setup

Test that your configuration is working:

```bash
python3 -c "
import sys
sys.path.insert(0, 'utils')
from config import get_config
config = get_config()
print('✓ Configuration loaded successfully')
print('✓ OpenAI API key configured')
"
```

## Security Notes

⚠️ **IMPORTANT**: Never commit the following files to version control:
- `.env` - Contains your actual API keys
- `config.json` - May contain sensitive configuration

✅ **Safe to commit**:
- `.env.example` - Template without real keys
- `config.example.json` - Template configuration
- `.gitignore` - Already configured to ignore sensitive files

## Troubleshooting

### Missing API Key Error

If you see an error about missing API keys:

1. Ensure `.env` file exists in the project root
2. Check that your API keys are correctly formatted (no extra spaces)
3. Verify the config.json uses `${OPENAI_API_KEY}` and `${ANTHROPIC_API_KEY}` placeholders

### Configuration Not Loading

If the configuration isn't loading properly:

1. Make sure you copied `config.example.json` to `config.json`
2. Verify the JSON syntax is valid
3. Check that environment variables are set correctly in `.env`
