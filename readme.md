# ⚡ ql
### 🚀 quick launcher > should be self explanatory

ql is an interactive command launcher that lets you save and quickly execute your most-used terminal commands and command chains. It provides keyboard navigation, real-time filtering, and instant command execution — without the ceremony of complex CLI tools.

## 🧠 why
ql is built on a simple idea: launching commands shouldn't be complex. It's a streamlined command bookmark system for individuals who prefer visual selection and instant execution over typing long commands repeatedly — built for those who think in shortcuts, not syntax.

## 📦 Installation

[get yanked](https://github.com/codinganovel/yanked)

## 🚀 Usage

### ql
The main command. Run this anywhere to open the interactive launcher. Use arrow keys to navigate through your saved commands, press Enter to execute, or start typing to add new commands or filter existing ones. The interface shows all your saved links and chains in a clean, navigable list.

### ql <alias>
Execute a specific command directly without opening the interactive interface. Perfect for scripting or when you know exactly which command you want to run.

### ql --help
Shows usage information and available options.

## 📁 What it creates

When you first run ql, it creates a configuration file to store your commands. Here's what gets saved:
### how to read what gets Saved.
### 📂 `~/.local/bin/.qlcom`

| Type     | Purpose |
|----------|---------|
| **Links** 🔗 | Single commands that execute immediately (e.g., `docker ps`, `git status`) |
| **Chains** ⛓️ | Multiple commands linked with `&&` that run sequentially and stop on first failure |

**Example commands:**
```bash
# In the interactive interface:
add backup tar -czf backup.tar.gz ~/documents
chain setup git pull && npm install && npm run build
```

The configuration file uses JSON format and stores command types, making it easy to backup or share your command collection.

## 🎯 Features

- **Interactive Navigation**: Arrow keys to browse, Enter to execute
- **Real-time Filtering**: Press `/` to search through commands
- **Command Types**: Support for single commands (links) and command chains
- **Dry Run Mode**: Press `d` to preview what a command will do
- **Clipboard Support**: Press `c` to copy commands (requires `pyperclip`)
- **Safety Features**: Warns about potentially dangerous commands
- **Cross-platform**: Works on Linux, macOS, and Windows

## 🛠 Contributing

Pull requests welcome. Open an issue or suggest an idea.

## 📄 License

MIT

> built by **Sam** with ☕️&❤️