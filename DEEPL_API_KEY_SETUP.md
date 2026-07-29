# DeepL API Key Setup

This document explains how to configure your DeepL API key for use with ebook2audiobook.

## Getting a DeepL API Key

1. Visit the DeepL API website: https://www.deepl.com/pro-api
2. Sign up for an account or log in if you already have one
3. Navigate to your account settings to find your API key
4. Copy your API key for use in ebook2audiobook

## Configuring the API Key

There are two ways to configure your DeepL API key:

### Method 1: Environment Variable (Recommended)

Set the `DEEPL_API_KEY` environment variable:

**On Windows (Command Prompt):**
```cmd
set DEEPL_API_KEY=your-api-key-here
```

**On Windows (PowerShell):**
```powershell
$env:DEEPL_API_KEY="your-api-key-here"
```

**On Linux/Mac:**
```bash
export DEEPL_API_KEY=your-api-key-here
```

### Method 2: Direct Configuration

Edit the `lib/conf.py` file and set the `DEEPL_API_KEY` variable directly:

```python
# DeepL API Key Configuration
# Set your DeepL API key here or use the DEEPL_API_KEY environment variable
DEEPL_API_KEY = "your-api-key-here"  # Replace with your actual API key
```

## Using DeepL Translation

Once configured, you can use DeepL translation in the ebook2audiobook interface:

1. Select "deepl" as your translation method
2. The system will automatically use your configured API key
3. No additional setup is required

## Security Notes

- Never commit your API key to version control
- Use environment variables for better security
- Keep your API key private and secure
- Monitor your API usage to avoid unexpected charges

## Troubleshooting

If you encounter issues with DeepL translation:

1. Verify your API key is correct
2. Check that you have sufficient quota on your DeepL account
3. Ensure your internet connection is working
4. Check that the DeepL library is properly installed (`pip install deepl`)