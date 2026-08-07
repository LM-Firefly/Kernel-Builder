#!/usr/bin/env bash

# Load a deliberately small dotenv subset without evaluating its content as shell code.
set -euo pipefail

env_file=${1:-.env}
test -f "$env_file" || {
  echo "Missing environment file: $env_file" >&2
  exit 1
}

while IFS= read -r raw_line || [ -n "$raw_line" ]; do
  line=${raw_line%$'\r'}
  case "$line" in
    '' | \#*) continue ;;
    export\ *) line=${line#export } ;;
  esac

  case "$line" in
    *=*) ;;
    *)
      echo "Invalid dotenv entry in $env_file: $raw_line" >&2
      exit 1
      ;;
  esac

  key=${line%%=*}
  value=${line#*=}
  case "$key" in
    [A-Za-z_][A-Za-z0-9_]*) ;;
    *)
      echo "Invalid dotenv key in $env_file: $key" >&2
      exit 1
      ;;
  esac

  case "$value" in
    \"*\") value=${value#\"}; value=${value%\"} ;;
    \'*\') value=${value#\'}; value=${value%\'} ;;
  esac
  export "$key=$value"
done < "$env_file"
