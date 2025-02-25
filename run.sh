#!/bin/bash

# This script helps set up Chromium in Replit environments

echo "Setting up Chrome dependencies..."

# Check if we're in a Replit environment
if [ -d "/home/runner" ]; then
  echo "Detected Replit environment"
else
  echo "Not in a Replit environment, exiting"
  exit 1
fi

# Create a directory to store logs
mkdir -p logs

# Check if Chromium is installed via Nix
CHROME_PATH=$(find /nix/store -name chromium -type f -executable 2>/dev/null | head -n 1)

if [ -n "$CHROME_PATH" ]; then
  echo "Found existing Chrome installation at: $CHROME_PATH"
else
  echo "Chrome not found in Nix store, checking other locations..."

  for path in "/usr/bin/chromium" "/usr/bin/google-chrome" "/usr/bin/chromium-browser"; do
    if [ -f "$path" ]; then
      CHROME_PATH="$path"
      echo "Found Chrome at: $CHROME_PATH"
      break
    fi
  done
fi

if [ -z "$CHROME_PATH" ]; then
  echo "No Chrome installation found. Make sure 'chromium' is listed in your replit.nix file."
fi

# Verify that Chrome is working
echo "Testing Chrome..."
if [ -n "$CHROME_PATH" ]; then
  "$CHROME_PATH" --version > logs/chrome_version.log 2>&1
  if [ $? -eq 0 ]; then
    echo "Chrome is working correctly"
    cat logs/chrome_version.log
  else
    echo "Chrome test failed. See logs/chrome_version.log for details"
  fi
else
  echo "Skipping Chrome test as no Chrome binary was found"./
fi

# Start the application
echo "Starting application..."
python app.py./