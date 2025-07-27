# ⚡ ql
### 🚀 quick launcher > should be self explanatory

ql is an interactive command launcher that lets you save and quickly execute your most-used terminal commands and command chains. It provides keyboard navigation, real-time filtering, template support, and instant command execution — without the ceremony of complex CLI tools.

## 🧠 why
ql is built on a simple idea: launching commands shouldn't be complex. It's a streamlined command bookmark system for individuals who prefer visual selection and instant execution over typing long commands repeatedly — built for those who think in shortcuts, not syntax.

## 📦 Installation

[get yanked](https://github.com/codinganovel/yanked)

## 🚀 Usage

### ql
The main command. Run this anywhere to open the interactive launcher. Use arrow keys to navigate through your saved commands, press Enter to execute, or start typing to add new commands or filter existing ones. The interface shows all your saved links, chains, and templates in a clean, navigable list.

### ql <alias>
Execute a specific command directly without opening the interactive interface. Perfect for scripting or when you know exactly which command you want to run.

### ql --help
Shows usage information and available options.

### ql --version
Shows the current version of ql.

## 📁 What it creates

When you first run ql, it creates configuration files to store your commands and templates. Here's what gets saved:

### 📂 `~/.local/bin/.qlcom`
Your saved commands in JSON format.

### 📂 `~/.local/bin/.qltemplates`
Your saved templates with dynamic placeholders.

### 📂 `~/.local/bin/.qlstats`
Usage statistics for your commands.

## 🎯 Command Types

| Type     | Purpose | Example |
|----------|---------|---------|
| **Links** 🔗 | Single commands that execute immediately | `docker ps`, `git status` |
| **Chains** ⛓️ | Multiple commands linked with `&&` that run sequentially and stop on first failure | `git pull && npm install && npm run build` |
| **Templates** 🎨 | Dynamic commands with placeholders that prompt for values | `git clone {repo} && cd {project}` |

**Example commands:**
```bash
# In the interactive interface:
add backup tar -czf backup.tar.gz ~/documents
chain setup git pull && npm install && npm run build
template deploy git clone {repo} && cd {project} && {build_command}
```

The configuration files use JSON format and store command types, descriptions, tags, and usage statistics — making it easy to backup or share your command collection.

## ✨ Features

### 🎮 Interactive Navigation
- **Arrow key browsing**: Navigate through all your commands and templates
- **Quick selection**: Press 1-9 to instantly run the first 9 items
- **Enter to execute**: Run commands immediately
- **Dual mode interface**: Switch between command mode and template mode with `Ctrl+T`

### 🔍 Smart Filtering
- **Real-time search**: Press `/` to filter commands by name, description, or tags
- **Fuzzy matching**: Find commands even with partial or out-of-order typing
- **Template filtering**: Search through templates and their placeholders

### 🎨 Template System
- **Dynamic placeholders**: Create commands with `{placeholder}` syntax
- **Interactive prompts**: Get prompted for values when running templates
- **Built-in templates**: Includes useful default templates for common tasks
- **Template management**: Full CRUD operations for templates

### 🛠️ Command Management
- **Command types**: Support for links, chains, and templates
- **Rich metadata**: Add descriptions and tags to organize your commands
- **Usage statistics**: Track how often you use each command
- **Export/Import**: Share command collections between machines

### 🎯 User Experience
- **Dry run mode**: Press `d` to preview what a command will do
- **Clipboard support**: Press `c` to copy commands (requires `pyperclip`)
- **Preview toggle**: Press `p` to show/hide command details
- **Safety features**: Warns about potentially dangerous commands
- **Cross-platform**: Works on Linux, macOS, and Windows

### 🔧 Advanced Features
- **Command validation**: Checks for common typos and missing commands
- **Automatic cleanup**: Manages temporary files and scripts
- **Error handling**: Graceful handling of long commands and edge cases
- **Keyboard shortcuts**: Extensive keyboard navigation support

## 🛠 Contributing

Pull requests welcome. Open an issue or suggest an idea.

## 📄 License

under ☕️, check out [the-coffee-license](https://github.com/codinganovel/The-Coffee-License)

I've included both licenses with the repo, do what you know is right. The licensing works by assuming you're operating under good faith.

> built by **Sam** with ☕️&❤️