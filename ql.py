#!/usr/bin/env python3
"""
QL - Quick Launcher
A simple CLI tool for saving and running frequently used commands and command chains
Enhanced version with improved UX and additional features
"""

import os
import sys
import subprocess
import json
import re
import argparse
import tempfile
import stat
import time
import glob
import shutil
from pathlib import Path
from collections import OrderedDict
from datetime import datetime

# Cross-platform terminal handling
try:
    import termios
    import tty
    TERMIOS_AVAILABLE = True
except ImportError:
    TERMIOS_AVAILABLE = False

try:
    import msvcrt
    MSVCRT_AVAILABLE = True
except ImportError:
    MSVCRT_AVAILABLE = False
    msvcrt = None

# Optional clipboard support
try:
    import pyperclip
    CLIPBOARD_AVAILABLE = True
except ImportError:
    CLIPBOARD_AVAILABLE = False

# Command templates for common patterns
COMMAND_TEMPLATES = {
    'git-setup': {
        'template': 'git clone {repo} && cd {project} && npm install',
        'description': 'Clone repo and setup Node.js project',
        'placeholders': ['repo', 'project']
    },
    'backup': {
        'template': 'tar -czf backup-$(date +%Y%m%d).tar.gz {directory}',
        'description': 'Create timestamped backup of directory',
        'placeholders': ['directory']
    },
    'deploy': {
        'template': 'git pull && {build_command} && {deploy_command}',
        'description': 'Pull, build and deploy sequence',
        'placeholders': ['build_command', 'deploy_command']
    },
    'docker-build': {
        'template': 'docker build -t {image_name} . && docker run -p {port}:{port} {image_name}',
        'description': 'Build and run Docker container',
        'placeholders': ['image_name', 'port']
    }
}

class QLLauncher:
    def __init__(self):
        # Force QL to always run from root directory for maximum cd compatibility
        os.chdir('/')
        
        # Ensure ~/.local/bin exists
        self.config_dir = Path.home() / '.local' / 'bin'
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / '.qlcom'
        self.stats_file = self.config_dir / '.qlstats'
        self.commands = self.load_commands()
        self.stats = self.load_stats()
        self.selected_index = 0
        self.input_buffer = ""
        self.input_mode = False
        self.filter_mode = False
        self.filter_text = ""
        self.filtered_commands = []
        self.first_run = True
        self.show_preview = True
        
        # Dangerous command patterns
        self.dangerous_patterns = [
            r'\brm\s+-rf?\s+/',
            r'\bshutdown\b',
            r'\breboot\b',
            r'\bdd\s+if=',
            r'\bmkfs\b',
            r'\bformat\b',
            r'>\s*/dev/sd[a-z]',
            r'\bsudo\b.*\brm\b',
        ]
        
        # Common command typos
        self.common_typos = {
            'cd..': 'cd ..',
            'ls-la': 'ls -la',
            'gitcommit': 'git commit',
            'gitpush': 'git push',
            'gitpull': 'git pull',
            'npminstall': 'npm install',
            'dockerrun': 'docker run'
        }
    
    def load_commands(self):
        """Load commands from config file with backward compatibility"""
        commands = OrderedDict()
        
        if not self.config_file.exists():
            return commands
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                
                if not content:
                    return commands
                
                # Try JSON format first
                if content.startswith('{'):
                    try:
                        data = json.loads(content)
                        # Convert to OrderedDict to maintain order and validate structure
                        for alias, cmd_data in data.items():
                            if isinstance(cmd_data, dict) and 'command' in cmd_data:
                                # Ensure all required fields exist
                                commands[alias] = {
                                    "type": cmd_data.get("type", "link"),
                                    "command": cmd_data.get("command", ""),
                                    "description": cmd_data.get("description", ""),
                                    "tags": cmd_data.get("tags", []),
                                    "created": cmd_data.get("created", datetime.now().isoformat())
                                }
                            elif isinstance(cmd_data, str):
                                # Handle old format where value was just a string
                                commands[alias] = {
                                    "type": "link",
                                    "command": cmd_data,
                                    "description": "",
                                    "tags": [],
                                    "created": datetime.now().isoformat()
                                }
                        return commands
                    except json.JSONDecodeError:
                        pass  # Fall through to old format parsing
                
                # Fall back to old text format
                for line in content.split('\n'):
                    line = line.strip()
                    if line and ':' in line and not line.startswith('#'):
                        try:
                            alias, command = line.split(':', 1)
                            alias = alias.strip()
                            command = command.strip()
                            if alias and command:
                                commands[alias] = {
                                    "type": "link",
                                    "command": command,
                                    "description": "",
                                    "tags": [],
                                    "created": datetime.now().isoformat()
                                }
                        except ValueError:
                            continue  # Skip malformed lines
                            
        except (IOError, OSError) as e:
            print(f"\033[93m⚠️  Warning: Error reading config file: {e}\033[0m")
            print(f"\033[37mStarting with empty command list.\033[0m")
        except Exception as e:
            print(f"\033[93m⚠️  Warning: Unexpected error reading config file: {e}\033[0m")
            print(f"\033[37mStarting with empty command list.\033[0m")
        
        return commands
    
    def load_stats(self):
        """Load usage statistics"""
        stats = {"usage_count": {}, "last_used": {}}
        
        if not self.stats_file.exists():
            return stats
        
        try:
            with open(self.stats_file, 'r', encoding='utf-8') as f:
                stats = json.load(f)
        except Exception:
            pass  # Use default stats if loading fails
        
        return stats
    
    def save_commands(self):
        """Save commands to config file in JSON format"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(dict(self.commands), f, indent=2, ensure_ascii=False)
        except (IOError, OSError) as e:
            print(f"\033[91m❌ Error saving commands: {e}\033[0m")
    
    def save_stats(self):
        """Save usage statistics"""
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.stats, f, indent=2)
        except Exception:
            pass  # Ignore stats save errors
    
    def update_usage_stats(self, alias):
        """Update usage statistics for a command"""
        self.stats["usage_count"][alias] = self.stats["usage_count"].get(alias, 0) + 1
        self.stats["last_used"][alias] = datetime.now().isoformat()
        self.save_stats()
    
    def fuzzy_match(self, text, pattern):
        """Combined substring + fuzzy matching for intuitive search"""
        if not pattern:
            return True
        text, pattern = text.lower(), pattern.lower()
        
        # First try substring search (most intuitive)
        if pattern in text:
            return True
        
        # Fall back to fuzzy matching (characters in order)
        i = 0
        for char in text:
            if i < len(pattern) and char == pattern[i]:
                i += 1
        return i == len(pattern)
    
    def validate_command(self, command):
        """Validate command and suggest corrections"""
        # Check for common typos
        words = command.split()
        if words:
            first_word = words[0]
            if first_word in self.common_typos:
                suggestion = self.common_typos[first_word]
                print(f"\033[93m💡 Did you mean: {suggestion}?\033[0m")
                response = input("\033[96mUse suggestion? (Y/n): \033[0m").lower()
                if response != 'n':
                    return command.replace(first_word, suggestion, 1)
        
        # Check if command exists
        words = command.split()
        if words and not words[0].startswith('./') and not '=' in words[0]:
            cmd_name = words[0]
            if not shutil.which(cmd_name) and cmd_name not in ['cd', 'export', 'source', '.']:
                print(f"\033[93m⚠️  Command '{cmd_name}' not found in PATH\033[0m")
                response = input("\033[96mContinue anyway? (y/N): \033[0m").lower()
                if response != 'y':
                    return None
        
        return command
    
    def is_dangerous_command(self, command):
        """Check if command contains dangerous patterns"""
        for pattern in self.dangerous_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False
    
    def confirm_dangerous_command(self, command):
        """Get user confirmation for potentially dangerous commands"""
        print(f"\033[93m⚠️  WARNING: This command appears potentially dangerous!\033[0m")
        print(f"\033[37mCommand: {command}\033[0m")
        response = input("\033[96mAre you sure you want to run this? (y/N): \033[0m").lower()
        return response == 'y'
    
    def clear_screen(self):
        """Clear the terminal screen"""
        os.system('clear' if os.name == 'posix' else 'cls')
    
    def get_key(self):
        """Get a single keypress from terminal with cross-platform support"""
        if TERMIOS_AVAILABLE:
            # Unix/Linux/macOS
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(sys.stdin.fileno())
                key = sys.stdin.read(1)
                
                # Handle arrow keys (escape sequences)
                if key == '\x1b':
                    key += sys.stdin.read(2)
                    if key == '\x1b[A':
                        return 'UP'
                    elif key == '\x1b[B':
                        return 'DOWN'
                    elif key == '\x1b[C':
                        return 'RIGHT'
                    elif key == '\x1b[D':
                        return 'LEFT'
                
                return key
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        
        elif MSVCRT_AVAILABLE and msvcrt:
            # Windows
            key = msvcrt.getch()
            if key == b'\xe0':  # Arrow key prefix
                key = msvcrt.getch()
                if key == b'H':
                    return 'UP'
                elif key == b'P':
                    return 'DOWN'
                elif key == b'M':
                    return 'RIGHT'
                elif key == b'K':
                    return 'LEFT'
            return key.decode('utf-8', errors='ignore')
        
        else:
            # Fallback - just get regular input
            return input().strip()
    
    def get_filtered_commands(self):
        """Get commands filtered by current filter text using fuzzy matching"""
        if not self.filter_text:
            return list(self.commands.items())
        
        filtered = []
        for alias, cmd_data in self.commands.items():
            command = cmd_data.get('command', '')
            description = cmd_data.get('description', '')
            tags = ' '.join(cmd_data.get('tags', []))
            
            if (self.fuzzy_match(alias, self.filter_text) or 
                self.fuzzy_match(command, self.filter_text) or
                self.fuzzy_match(description, self.filter_text) or
                self.fuzzy_match(tags, self.filter_text)):
                filtered.append((alias, cmd_data))
        return filtered
    
    def get_command_suggestions(self, partial):
        """Get command suggestions for tab completion"""
        matches = [alias for alias in self.commands if alias.startswith(partial)]
        return matches
    
    def show_command_preview(self, alias):
        """Show preview of selected command"""
        if alias in self.commands:
            cmd_data = self.commands[alias]
            command = cmd_data.get('command', '')
            description = cmd_data.get('description', '')
            tags = cmd_data.get('tags', [])
            usage_count = self.stats["usage_count"].get(alias, 0)
            
            preview_parts = []
            if description:
                preview_parts.append(f"📝 {description}")
            if tags:
                preview_parts.append(f"🏷️  {', '.join(tags)}")
            if usage_count > 0:
                preview_parts.append(f"📊 Used {usage_count} times")
            
            if preview_parts:
                print(f"\033[90m   └─ {' • '.join(preview_parts)}\033[0m")
            
            # Show command preview
            display_command = command if len(command) <= 80 else command[:77] + "..."
            print(f"\033[90m   └─ Command: {display_command}\033[0m")
    
    def show_stats(self):
        """Show command usage statistics"""
        if not self.commands:
            return ""
        
        chains = sum(1 for cmd in self.commands.values() if cmd.get('type') == 'chain')
        links = len(self.commands) - chains
        total_usage = sum(self.stats["usage_count"].values())
        
        stats_text = f"📊 {len(self.commands)} commands ({links} links, {chains} chains)"
        if total_usage > 0:
            stats_text += f" • {total_usage} total uses"
        
        return stats_text
    
    def show_main_screen(self):
        """Display the main interface"""
        if not self.first_run:
            self.clear_screen()
        self.first_run = False
        
        # Header with blue theme
        print("\033[96m" + "=" * 60)
        print("🚀 QL - Quick Launcher")
        print("=" * 60 + "\033[0m")
        print()
        
        # Get commands to display (filtered or all)
        display_commands = self.get_filtered_commands()
        
        if not self.commands:
            print("\033[94m📝 No commands saved yet!\033[0m")
            print("\033[37mGet started by adding your first command:\033[0m")
            print("\033[36m   add <alias> <command>\033[0m")
            print("\033[36m   chain <alias> <cmd1> && <cmd2> && <cmd3>\033[0m")
            print("\033[36m   template <template_name> <alias>\033[0m")
            print()
            print("\033[37mExample:\033[0m")
            print("\033[36m   add backup tar -czf backup.tar.gz ~/documents\033[0m")
            print("\033[36m   chain setup git pull && npm install && npm run build\033[0m")
            print("\033[36m   template git-setup myproject\033[0m")
            print()
            print("\033[94m🎯 Available templates:\033[0m")
            for name, template in COMMAND_TEMPLATES.items():
                print(f"\033[36m   {name:<12}\033[0m \033[37m- {template['description']}\033[0m")
        else:
            # Show filter status and stats
            stats_text = self.show_stats()
            if self.filter_mode:
                print(f"\033[94m🔍 Filter: \"{self.filter_text}\" ({len(display_commands)}/{len(self.commands)} commands)\033[0m")
            else:
                print(f"\033[94m{stats_text}\033[0m")
            print()
            
            if not display_commands:
                print("\033[93m📭 No commands match your filter.\033[0m")
            else:
                # Calculate max alias length for alignment
                max_alias_len = max(len(alias) for alias, _ in display_commands) if display_commands else 10
                
                for i, (alias, cmd_data) in enumerate(display_commands):
                    cmd_type = cmd_data.get('type', 'link')
                    command = cmd_data.get('command', '')
                    description = cmd_data.get('description', '')
                    usage_count = self.stats["usage_count"].get(alias, 0)
                    
                    # Choose emoji based on type
                    emoji = "⛓️" if cmd_type == 'chain' else "🔗"
                    
                    # Truncate long commands for display
                    display_command = command if len(command) <= 40 else command[:37] + "..."
                    
                    # Show number for quick selection (1-9), or position for 10+
                    if i < 9:
                        num_display = f"{i+1}"
                    else:
                        num_display = f"{i+1:2d}" if i < 99 else "##"
                    
                    # Add usage indicator
                    usage_indicator = f" ({usage_count})" if usage_count > 0 else ""
                    
                    # Highlight selected command
                    if i == self.selected_index:
                        print(f"\033[1;97;44m {num_display}. {emoji} {alias:<{max_alias_len}}{usage_indicator} → {display_command}\033[0m")
                        if self.show_preview:
                            self.show_command_preview(alias)
                    else:
                        # Show clickable numbers (1-9) in bright color, others in dim
                        num_color = "\033[96m" if i < 9 else "\033[90m"
                        alias_color = "\033[1;36m" if usage_count > 0 else "\033[36m"
                        print(f"{num_color} {num_display}.\033[0m {emoji} {alias_color}{alias:<{max_alias_len}}\033[90m{usage_indicator}\033[0m \033[37m→\033[0m {display_command}")
        
        print()
        print("\033[94m⚡ Commands:\033[0m")
        print("\033[36m   add <alias> <command>\033[0m      \033[37m- Add new command link\033[0m")
        print("\033[36m   chain <alias> <cmd1> && <cmd2>\033[0m \033[37m- Add command chain\033[0m")
        print("\033[36m   edit <alias>\033[0m               \033[37m- Edit existing command\033[0m")
        print("\033[36m   remove <alias>\033[0m             \033[37m- Remove command\033[0m")
        print("\033[36m   template <name> <alias>\033[0m    \033[37m- Create from template\033[0m")
        print("\033[36m   export <file>\033[0m              \033[37m- Export commands to file\033[0m")
        print("\033[36m   import <file>\033[0m              \033[37m- Import commands from file\033[0m")
        print("\033[36m   help\033[0m                       \033[37m- Show detailed help\033[0m")
        print("\033[36m   quit\033[0m or \033[36mq\033[0m                  \033[37m- Exit ql\033[0m")
        print()
        
        if self.commands:
            print("\033[94m🎯 Navigation:\033[0m")
            print("\033[36m   1-9\033[0m                       \033[37m- Quick select (first 9 commands)\033[0m")
            print("\033[36m   ↑/↓ arrows\033[0m                \033[37m- Navigate all commands\033[0m")
            print("\033[36m   Enter\033[0m                     \033[37m- Run selected command\033[0m")
            print("\033[36m   Ctrl+D\033[0m                    \033[37m- Dry run (preview command)\033[0m")
            if CLIPBOARD_AVAILABLE:
                print("\033[36m   Ctrl+Y\033[0m                    \033[37m- Copy command to clipboard\033[0m")
            print("\033[36m   /\033[0m                         \033[37m- Filter commands (fuzzy)\033[0m")
            print("\033[36m   Tab\033[0m                       \033[37m- Auto-complete alias\033[0m")
            print("\033[36m   p\033[0m                         \033[37m- Toggle preview on/off\033[0m")
            print()
        
        print(f"\033[90m📁 Commands stored in: {self.config_file}\033[0m")
        
        # Input prompt
        if self.filter_mode:
            print(f"\033[95m🔍 Filter: {self.filter_text}\033[7m \033[0m")
        elif self.input_mode:
            print(f"\033[96m> {self.input_buffer}\033[7m \033[0m")
        else:
            print("\033[96m> \033[0m", end="", flush=True)
    
    def move_command_to_front(self, alias):
        """Move recently used command to front of the list"""
        if alias in self.commands:
            cmd_data = self.commands.pop(alias)
            new_commands = OrderedDict()
            new_commands[alias] = cmd_data
            new_commands.update(self.commands)
            self.commands = new_commands
    
    def show_help(self):
        """Show detailed help"""
        self.clear_screen()
        print("\033[96m" + "=" * 60)
        print("🚀 QL - Quick Launcher Help")
        print("=" * 60 + "\033[0m")
        print()
        
        print("\033[94m📝 Adding Commands:\033[0m")
        print("\033[36m   add backup tar -czf backup.tar.gz ~/docs\033[0m")
        print("\033[37m   └─ Creates a simple command link\033[0m")
        print()
        print("\033[36m   chain deploy git pull && npm install && npm run build\033[0m")
        print("\033[37m   └─ Creates a command chain (stops on first failure)\033[0m")
        print()
        print("\033[36m   template git-setup myproject\033[0m")
        print("\033[37m   └─ Creates command from template with guided setup\033[0m")
        print()
        
        print("\033[94m🎯 Navigation Tips:\033[0m")
        print("\033[37m   • Use / to search/filter commands by name, description, or tags\033[0m")
        print("\033[37m   • Arrow keys to navigate, Enter to run\033[0m")
        print("\033[37m   • Numbers 1-9 for quick selection of first 9 commands\033[0m")
        print("\033[37m   • Ctrl+D for dry run preview (see what would execute)\033[0m")
        print("\033[37m   • p key to toggle command preview on/off\033[0m")
        print()
        
        print("\033[94m🔧 Command Management:\033[0m")
        print("\033[37m   • edit <alias> - Modify existing commands\033[0m")
        print("\033[37m   • Commands can have descriptions and tags for better organization\033[0m")
        print("\033[37m   • Usage statistics track how often you use each command\033[0m")
        print("\033[37m   • export/import for sharing command sets between machines\033[0m")
        print()
        
        print("\033[94m🎨 Available Templates:\033[0m")
        for name, template in COMMAND_TEMPLATES.items():
            print(f"\033[36m   {name:<15}\033[0m \033[37m{template['description']}\033[0m")
        print()
        
        print("\033[94m⚠️  Safety Features:\033[0m")
        print("\033[37m   • Potentially dangerous commands require confirmation\033[0m")
        print("\033[37m   • Common command typos are detected and corrected\033[0m")
        print("\033[37m   • Commands are validated before saving\033[0m")
        print()
        
        input("\033[90mPress Enter to continue...\033[0m")
    
    def show_templates(self):
        """Show available templates"""
        self.clear_screen()
        print("\033[96m📋 Available Command Templates\033[0m")
        print()
        
        for name, template in COMMAND_TEMPLATES.items():
            print(f"\033[1;36m{name}\033[0m")
            print(f"  \033[37m{template['description']}\033[0m")
            print(f"  \033[90m{template['template']}\033[0m")
            if template['placeholders']:
                print(f"  \033[90mPlaceholders: {', '.join(template['placeholders'])}\033[0m")
            print()
        
        print(f"\033[94mUsage: template <name> <alias>\033[0m")
        input("\033[90mPress Enter to continue...\033[0m")
    
    def parse_input(self, user_input):
        """Parse and execute user input"""
        if not user_input.strip():
            return True
        
        parts = user_input.strip().split()
        command = parts[0].lower()
        
        if command in ['quit', 'q', 'exit']:
            return False
        elif command == 'help':
            self.show_help()
        elif command == 'templates':
            self.show_templates()
        elif command == 'add':
            if len(parts) < 3:
                print("\033[91m❌ Usage: add <alias> <command>\033[0m")
                input("\033[90mPress Enter to continue...\033[0m")
            else:
                alias = parts[1]
                cmd = ' '.join(parts[2:])
                self.add_command(alias, cmd, 'link')
                input("\033[90mPress Enter to continue...\033[0m")
        elif command == 'chain':
            if len(parts) < 3:
                print("\033[91m❌ Usage: chain <alias> <cmd1> && <cmd2> && <cmd3>\033[0m")
                input("\033[90mPress Enter to continue...\033[0m")
            else:
                alias = parts[1]
                cmd = ' '.join(parts[2:])
                self.add_command(alias, cmd, 'chain')
                input("\033[90mPress Enter to continue...\033[0m")
        elif command == 'edit':
            if len(parts) < 2:
                print("\033[91m❌ Usage: edit <alias>\033[0m")
                input("\033[90mPress Enter to continue...\033[0m")
            else:
                self.edit_command(parts[1])
                input("\033[90mPress Enter to continue...\033[0m")
        elif command == 'remove':
            if len(parts) < 2:
                print("\033[91m❌ Usage: remove <alias>\033[0m")
                input("\033[90mPress Enter to continue...\033[0m")
            else:
                self.remove_command(parts[1])
                input("\033[90mPress Enter to continue...\033[0m")
        elif command == 'template':
            if len(parts) < 3:
                print("\033[91m❌ Usage: template <template_name> <alias>\033[0m")
                print("\033[37mAvailable templates: " + ", ".join(COMMAND_TEMPLATES.keys()) + "\033[0m")
                input("\033[90mPress Enter to continue...\033[0m")
            else:
                self.create_from_template(parts[1], parts[2])
                input("\033[90mPress Enter to continue...\033[0m")
        elif command == 'export':
            if len(parts) < 2:
                print("\033[91m❌ Usage: export <filename>\033[0m")
                input("\033[90mPress Enter to continue...\033[0m")
            else:
                self.export_commands(parts[1])
                input("\033[90mPress Enter to continue...\033[0m")
        elif command == 'import':
            if len(parts) < 2:
                print("\033[91m❌ Usage: import <filename>\033[0m")
                input("\033[90mPress Enter to continue...\033[0m")
            else:
                self.import_commands(parts[1])
                input("\033[90mPress Enter to continue...\033[0m")
        else:
            # Try to run as a command alias
            if command in self.commands:
                return self.run_command_and_exit(command)
            else:
                print(f"\033[91m❌ Unknown command: {command}\033[0m")
                print("\033[37mType 'help' for available commands or 'quit' to exit.\033[0m")
                input("\033[90mPress Enter to continue...\033[0m")
        
        return True
    
    def cleanup_old_scripts(self):
        """Clean up any leftover QL temp scripts"""
        # Clean from both system temp and our local temp directory
        temp_dirs = ['/tmp', str(self.config_dir / 'tmp')]
        
        for temp_dir in temp_dirs:
            if not os.path.exists(temp_dir):
                continue
                
            try:
                pattern = os.path.join(temp_dir, 'tmp*_ql.sh')
                for script_path in glob.glob(pattern):
                    try:
                        # Check if it's a QL script and if it's old
                        if os.path.exists(script_path):
                            age = time.time() - os.path.getmtime(script_path)
                            if age > 3600:  # 1 hour
                                with open(script_path, 'r', encoding='utf-8', errors='ignore') as f:
                                    content = f.read()
                                    if '# QL Command Executor' in content:
                                        os.unlink(script_path)
                    except (OSError, IOError):
                        pass  # Ignore individual file errors
            except (OSError, IOError):
                pass  # Ignore directory errors
    
    def _check_sudo_cd_issues(self, command):
        """Check for and warn about sudo cd issues"""
        if not command.strip().startswith('sudo cd '):
            return False
        
        self.clear_screen()
        print(f"\033[93m⚠️  WARNING: 'sudo cd' command detected!\033[0m")
        print(f"\033[37mCommand: {command}\033[0m")
        print("\n\033[96m💡 'sudo cd' doesn't work as expected in command chains.\033[0m")
        
        # Show suggestions
        self._show_sudo_cd_alternatives(command)
        
        response = input("\033[96mWould you like to run the command anyway? (y/N): \033[0m").lower()
        if response != 'y':
            print("\033[37mCommand cancelled.\033[0m")
            input("\033[90mPress Enter to continue...\033[0m")
            return True
        return False
    
    def _show_sudo_cd_alternatives(self, command):
        """Show alternative suggestions for sudo cd commands"""
        print("\033[94mSuggested alternatives:\033[0m")
        
        # Extract the directory and remaining commands
        parts = command.split('&&', 1)
        if len(parts) == 2:
            cd_part = parts[0].strip()
            rest_part = parts[1].strip()
            directory = cd_part.replace('sudo cd', 'cd').strip()
            
            print(f"\033[36m1. {directory} && {rest_part}\033[0m")
            print(f"\033[90m   (Change directory first, then run command normally)\033[0m")
            print()
            print(f"\033[36m2. {directory} && sudo {rest_part}\033[0m") 
            print(f"\033[90m   (Change directory first, then run command with sudo)\033[0m")
            print()
            print(f"\033[36m3. sudo bash -c \"{cd_part.replace('sudo ', '')} && {rest_part}\"\033[0m")
            print(f"\033[90m   (Run entire chain in sudo subshell)\033[0m")
        print()
    
    def _create_execution_script(self, alias, command, cmd_type):
        """Create the execution script and return its path"""
        try:
            script_dir = self.config_dir / 'tmp'
            script_dir.mkdir(exist_ok=True)
            
            temp_script = tempfile.NamedTemporaryFile(
                mode='w', suffix='_ql.sh', delete=False,
                dir=script_dir, encoding='utf-8'
            )
            
            shell = os.environ.get('SHELL', '/bin/bash')
            if not os.path.exists(shell):
                shell = '/bin/bash'
            
            # Write script content
            script_content = self._generate_script_content(alias, command, cmd_type, shell)
            temp_script.write(script_content)
            temp_script.close()
            
            # Make executable
            os.chmod(temp_script.name, stat.S_IRWXU)
            return temp_script.name
            
        except (OSError, IOError) as e:
            print(f"\033[91m❌ Error creating script: {e}\033[0m")
            input("\033[90mPress Enter to continue...\033[0m")
            return None
    
    def _generate_script_content(self, alias, command, cmd_type, shell):
        """Generate the script content"""
        if cmd_type == 'chain':
            return f"""#!/bin/bash
# QL Command Executor - Chain Command
trap 'rm -f "$0"' EXIT

cd /

echo "🚀 Running chain: {alias}"
echo "📁 Working directory: $(pwd)"
echo "──────────────────────────────────────────────────"

set -e
set -o pipefail

echo "⛓️  Executing chain command"
{command}

echo "──────────────────────────────────────────────────"
echo "✅ Chain '{alias}' completed successfully"

exec {shell}
"""
        else:
            return f"""#!/bin/bash
# QL Command Executor
trap 'rm -f "$0"' EXIT

cd /

echo "🚀 Running: {command}"
echo "📁 Working directory: $(pwd)"
echo "──────────────────────────────────────────────────"

{command}

exit_code=$?

echo "──────────────────────────────────────────────────"
if [ $exit_code -eq 0 ]; then
    echo "✅ Command completed successfully"
else
    echo "❌ Command failed with exit code $exit_code"
fi

exec {shell}
"""
    
    def run_command_and_exit(self, alias):
        """Run command by feeding it directly to the terminal - simplified version"""
        if alias not in self.commands:
            return True
        
        # Clean up any old scripts first
        self.cleanup_old_scripts()
        
        # Update usage statistics
        self.update_usage_stats(alias)
        
        # Move to front for recent usage
        self.move_command_to_front(alias)
        self.save_commands()
        
        cmd_data = self.commands[alias]
        command = cmd_data.get('command', '')
        cmd_type = cmd_data.get('type', 'link')
        
        # Safety checks
        if self.is_dangerous_command(command):
            self.clear_screen()
            if not self.confirm_dangerous_command(command):
                print("\033[37mCommand cancelled.\033[0m")
                input("\033[90mPress Enter to continue...\033[0m")
                return True
        
        # Check for sudo cd issues
        if self._check_sudo_cd_issues(command):
            return True
        
        # Create and execute script
        script_path = self._create_execution_script(alias, command, cmd_type)
        if not script_path:
            return True
        
        # Clear screen and launch
        self.clear_screen()
        emoji = "⛓️" if cmd_type == 'chain' else "🔗"
        print(f"\033[96m🚀 Launching {emoji} {alias} in terminal...\033[0m")
        
        # Replace current process with the script
        try:
            os.execv('/bin/bash', ['/bin/bash', script_path])
        except (OSError, IOError) as e:
            print(f"\033[91m❌ Error executing script: {e}\033[0m")
            try:
                os.unlink(script_path)
            except:
                pass
            input("\033[90mPress Enter to continue...\033[0m")
            return True
        
        return False
    
    def dry_run_command(self, alias):
        """Show what command would run without executing it"""
        if alias not in self.commands:
            return
        
        cmd_data = self.commands[alias]
        command = cmd_data.get('command', '')
        cmd_type = cmd_data.get('type', 'link')
        description = cmd_data.get('description', '')
        tags = cmd_data.get('tags', [])
        emoji = "⛓️" if cmd_type == 'chain' else "🔗"
        
        self.clear_screen()
        print(f"\033[95m🔍 Dry run for {emoji} {alias}:\033[0m")
        if description:
            print(f"\033[90m📝 {description}\033[0m")
        if tags:
            print(f"\033[90m🏷️  Tags: {', '.join(tags)}\033[0m")
        print()
        print(f"\033[37m{command}\033[0m")
        print()
        
        if cmd_type == 'chain':
            print("\033[90mThis would run as a command chain (stops on first failure)\033[0m")
        
        if self.is_dangerous_command(command):
            print("\033[93m⚠️  WARNING: This command appears potentially dangerous!\033[0m")
        
        input("\033[90mPress Enter to continue...\033[0m")
    
    def copy_to_clipboard(self, alias):
        """Copy command to clipboard"""
        if not CLIPBOARD_AVAILABLE:
            print("\033[91m❌ Clipboard support not available (install pyperclip)\033[0m")
            input("\033[90mPress Enter to continue...\033[0m")
            return
        
        if alias not in self.commands:
            return
        
        cmd_data = self.commands[alias]
        command = cmd_data.get('command', '')
        
        self.clear_screen()
        try:
            pyperclip.copy(command)
            print(f"\033[92m📋 Copied '{alias}' to clipboard!\033[0m")
            print(f"\033[90mCommand: {command}\033[0m")
        except Exception as e:
            print(f"\033[91m❌ Error copying to clipboard: {e}\033[0m")
        
        input("\033[90mPress Enter to continue...\033[0m")
    
    def interactive_mode(self):
        """Main interactive loop"""
        while True:
            self.show_main_screen()
            
            try:
                key = self.get_key()
                display_commands = self.get_filtered_commands()
                
                if key == '\r' or key == '\n':  # Enter key
                    if self.filter_mode:
                        # Exit filter mode
                        self.filter_mode = False
                        self.selected_index = 0
                    elif self.input_mode and self.input_buffer.strip():
                        if not self.parse_input(self.input_buffer):
                            break
                        self.input_buffer = ""
                        self.input_mode = False
                    elif display_commands and not self.input_mode:
                        # Run selected command
                        if 0 <= self.selected_index < len(display_commands):
                            selected_alias = display_commands[self.selected_index][0]
                            if not self.run_command_and_exit(selected_alias):
                                break
                
                elif key == '\t' and self.input_mode:  # Tab completion
                    suggestions = self.get_command_suggestions(self.input_buffer)
                    if len(suggestions) == 1:
                        self.input_buffer = suggestions[0] + ' '
                    elif len(suggestions) > 1:
                        # Show suggestions
                        print(f"\n\033[90mSuggestions: {', '.join(suggestions[:5])}\033[0m")
                        if len(suggestions) > 5:
                            print(f"\033[90m... and {len(suggestions) - 5} more\033[0m")
                        input("\033[90mPress Enter to continue...\033[0m")
                
                elif key.isdigit() and not self.input_mode and not self.filter_mode:
                    # Quick select with number keys (1-9)
                    num = int(key) - 1
                    if 0 <= num < len(display_commands) and num < 9:
                        selected_alias = display_commands[num][0]
                        if not self.run_command_and_exit(selected_alias):
                            break
                
                elif key == 'p' and not self.input_mode and not self.filter_mode:
                    # Toggle preview
                    self.show_preview = not self.show_preview
                
                elif key == 'UP' and display_commands and not self.input_mode and not self.filter_mode:
                    self.selected_index = max(0, self.selected_index - 1)
                
                elif key == 'DOWN' and display_commands and not self.input_mode and not self.filter_mode:
                    self.selected_index = min(len(display_commands) - 1, self.selected_index + 1)
                
                elif key == '\x04' and display_commands and not self.input_mode and not self.filter_mode:
                    # Ctrl+D - Dry run selected command
                    if 0 <= self.selected_index < len(display_commands):
                        selected_alias = display_commands[self.selected_index][0]
                        self.dry_run_command(selected_alias)
                
                elif key == '\x19' and display_commands and not self.input_mode and not self.filter_mode:
                    # Ctrl+Y - Copy selected command
                    if 0 <= self.selected_index < len(display_commands):
                        selected_alias = display_commands[self.selected_index][0]
                        self.copy_to_clipboard(selected_alias)
                
                elif key == '/' and not self.input_mode:
                    # Enter filter mode
                    self.filter_mode = True
                    self.filter_text = ""
                    self.selected_index = 0
                
                elif key == '\x7f' or key == '\x08':  # Backspace
                    if self.filter_mode:
                        if self.filter_text:
                            self.filter_text = self.filter_text[:-1]
                            self.selected_index = 0
                        else:
                            self.filter_mode = False
                    elif self.input_mode and self.input_buffer:
                        self.input_buffer = self.input_buffer[:-1]
                        if not self.input_buffer:
                            self.input_mode = False
                
                elif key == '\x1b':  # Escape key
                    if self.filter_mode:
                        self.filter_mode = False
                        self.filter_text = ""
                        self.selected_index = 0
                    elif self.input_mode:
                        self.input_mode = False
                        self.input_buffer = ""
                
                elif key == '\x03':  # Ctrl+C
                    break
                
                elif key.isprintable():
                    if self.filter_mode:
                        self.filter_text += key
                        self.selected_index = 0
                    else:
                        if not self.input_mode:
                            self.input_mode = True
                            self.input_buffer = ""
                        self.input_buffer += key
                    
            except KeyboardInterrupt:
                break
            except Exception:
                continue
    
    def add_command(self, alias, command, cmd_type='link', description="", tags=None):
        """Add a new command with enhanced features"""
        # Basic validation
        if not alias or not alias.strip():
            print("\033[91m❌ Alias cannot be empty\033[0m")
            return
            
        if not command or not command.strip():
            print("\033[91m❌ Command cannot be empty\033[0m")
            return
            
        # Clean up alias and command
        alias = alias.strip()
        command = command.strip()
        
        # Check for problematic characters in alias - FIXED REGEX
        if not re.match(r'^[a-zA-Z0-9_-]+$', alias):
            print("\033[91m❌ Alias can only contain letters, numbers, hyphens and underscores\033[0m")
            return
        
        # Validate command
        validated_command = self.validate_command(command)
        if validated_command is None:
            return
        command = validated_command
        
        if alias in self.commands:
            cmd_data = self.commands[alias]
            existing_type = cmd_data.get('type', 'link')
            existing_emoji = "⛓️" if existing_type == 'chain' else "🔗"
            print(f"\033[93m⚠️  Command '{alias}' already exists! {existing_emoji}\033[0m")
            print(f"\033[37mCurrent: {cmd_data.get('command', '')}\033[0m")
            response = input("\033[96mOverwrite? (y/N): \033[0m").lower()
            if response != 'y':
                print("\033[37mCommand not added.\033[0m")
                return
        
        # Get additional details if not provided
        if not description and not tags:
            print("\033[94m📝 Optional: Add description and tags for better organization\033[0m")
            description = input("\033[96mDescription (optional): \033[0m").strip()
            tags_input = input("\033[96mTags (comma-separated, optional): \033[0m").strip()
            tags = [tag.strip() for tag in tags_input.split(',') if tag.strip()] if tags_input else []
        
        self.commands[alias] = {
            "type": cmd_type,
            "command": command,
            "description": description,
            "tags": tags or [],
            "created": datetime.now().isoformat()
        }
        self.save_commands()
        
        emoji = "⛓️" if cmd_type == 'chain' else "🔗"
        print(f"\033[92m✅ Added {cmd_type} '{alias}' {emoji}\033[0m")
        if description:
            print(f"\033[90m📝 {description}\033[0m")
        if tags:
            print(f"\033[90m🏷️  Tags: {', '.join(tags)}\033[0m")
        print(f"\033[90m📁 Saved to: {self.config_file}\033[0m")
        
        # Reset selection to new command
        display_commands = self.get_filtered_commands()
        for i, (cmd_alias, _) in enumerate(display_commands):
            if cmd_alias == alias:
                self.selected_index = i
                break
    
    def edit_command(self, alias):
        """Edit an existing command interactively"""
        if alias not in self.commands:
            print(f"\033[91m❌ Command '{alias}' not found!\033[0m")
            return
        
        cmd_data = self.commands[alias]
        current_command = cmd_data.get('command', '')
        current_description = cmd_data.get('description', '')
        current_tags = cmd_data.get('tags', [])
        cmd_type = cmd_data.get('type', 'link')
        
        print(f"\033[94mEditing: {alias} ({cmd_type})\033[0m")
        print(f"\033[90mCurrent command: {current_command}\033[0m")
        if current_description:
            print(f"\033[90mCurrent description: {current_description}\033[0m")
        if current_tags:
            print(f"\033[90mCurrent tags: {', '.join(current_tags)}\033[0m")
        print()
        
        # Edit command
        new_command = input(f"\033[96mNew command (Enter to keep current): \033[0m").strip()
        if new_command:
            validated_command = self.validate_command(new_command)
            if validated_command is None:
                print("\033[37mCommand not updated.\033[0m")
                return
            current_command = validated_command
        
        # Edit description
        new_description = input(f"\033[96mDescription (Enter to keep current): \033[0m").strip()
        if new_description:
            current_description = new_description
        
        # Edit tags
        print(f"\033[90mCurrent tags: {', '.join(current_tags) if current_tags else 'none'}\033[0m")
        new_tags_input = input(f"\033[96mTags (comma-separated, Enter to keep current): \033[0m").strip()
        if new_tags_input:
            current_tags = [tag.strip() for tag in new_tags_input.split(',') if tag.strip()]
        
        # Update command
        self.commands[alias].update({
            'command': current_command,
            'description': current_description,
            'tags': current_tags
        })
        self.save_commands()
        
        emoji = "⛓️" if cmd_type == 'chain' else "🔗"
        print(f"\033[92m✅ Updated '{alias}' {emoji}\033[0m")
    
    def remove_command(self, alias):
        """Remove a command"""
        if alias not in self.commands:
            print(f"\033[91m❌ Command '{alias}' not found!\033[0m")
            return
        
        cmd_data = self.commands[alias]
        cmd_type = cmd_data.get('type', 'link')
        command = cmd_data.get('command', '')
        emoji = "⛓️" if cmd_type == 'chain' else "🔗"
        
        print(f"\033[93m⚠️  Remove {cmd_type} '{alias}' {emoji}?\033[0m")
        print(f"\033[37mCommand: {command}\033[0m")
        response = input("\033[96mConfirm removal? (y/N): \033[0m").lower()
        
        if response == 'y':
            del self.commands[alias]
            # Also remove from stats
            if alias in self.stats["usage_count"]:
                del self.stats["usage_count"][alias]
            if alias in self.stats["last_used"]:
                del self.stats["last_used"][alias]
            
            self.save_commands()
            self.save_stats()
            print(f"\033[92m✅ Removed {cmd_type} '{alias}'\033[0m")
            
            # Adjust selection if needed
            display_commands = self.get_filtered_commands()
            if self.selected_index >= len(display_commands):
                self.selected_index = max(0, len(display_commands) - 1)
        else:
            print("\033[37mCommand not removed.\033[0m")
    
    def create_from_template(self, template_name, alias):
        """Create a command from a template"""
        if template_name not in COMMAND_TEMPLATES:
            print(f"\033[91m❌ Template '{template_name}' not found!\033[0m")
            print(f"\033[37mAvailable templates: {', '.join(COMMAND_TEMPLATES.keys())}\033[0m")
            return
        
        template = COMMAND_TEMPLATES[template_name]
        command_template = template['template']
        placeholders = template['placeholders']
        
        print(f"\033[94m🎨 Creating command from template: {template_name}\033[0m")
        print(f"\033[90m{template['description']}\033[0m")
        print(f"\033[90mTemplate: {command_template}\033[0m")
        print()
        
        # Get values for placeholders
        placeholder_values = {}
        for placeholder in placeholders:
            value = input(f"\033[96m{placeholder}: \033[0m").strip()
            if not value:
                print("\033[37mTemplate creation cancelled.\033[0m")
                return
            placeholder_values[placeholder] = value
        
        # Replace placeholders
        final_command = command_template
        for placeholder, value in placeholder_values.items():
            final_command = final_command.replace(f"{{{placeholder}}}", value)
        
        print(f"\033[90mFinal command: {final_command}\033[0m")
        response = input("\033[96mCreate this command? (Y/n): \033[0m").lower()
        
        if response != 'n':
            self.add_command(alias, final_command, 'chain' if '&&' in final_command else 'link', 
                           template['description'], [template_name])
    
    def export_commands(self, filename):
        """Export commands to a file"""
        try:
            export_data = {
                'commands': dict(self.commands),
                'exported_at': datetime.now().isoformat(),
                'version': '1.0.0'
            }
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            print(f"\033[92m✅ Exported {len(self.commands)} commands to {filename}\033[0m")
        except Exception as e:
            print(f"\033[91m❌ Export failed: {e}\033[0m")
    
    def import_commands(self, filename):
        """Import commands from a file"""
        if not os.path.exists(filename):
            print(f"\033[91m❌ File '{filename}' not found!\033[0m")
            return
        
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Handle both new export format and old format
            if 'commands' in data:
                imported_commands = data['commands']
            else:
                imported_commands = data
            
            print(f"\033[94mImporting {len(imported_commands)} commands from {filename}\033[0m")
            
            conflicts = []
            for alias in imported_commands:
                if alias in self.commands:
                    conflicts.append(alias)
            
            if conflicts:
                print(f"\033[93m⚠️  {len(conflicts)} commands already exist: {', '.join(conflicts[:5])}")
                if len(conflicts) > 5:
                    print(f"    ... and {len(conflicts) - 5} more")
                response = input("\033[96mOverwrite existing commands? (y/N): \033[0m").lower()
                if response != 'y':
                    print("\033[37mImport cancelled.\033[0m")
                    return
            
            # Import commands
            imported_count = 0
            for alias, cmd_data in imported_commands.items():
                # Ensure proper structure
                if isinstance(cmd_data, str):
                    cmd_data = {
                        "type": "link",
                        "command": cmd_data,
                        "description": "",
                        "tags": [],
                        "created": datetime.now().isoformat()
                    }
                elif isinstance(cmd_data, dict):
                    # Fill in missing fields
                    cmd_data.setdefault("description", "")
                    cmd_data.setdefault("tags", [])
                    cmd_data.setdefault("created", datetime.now().isoformat())
                
                self.commands[alias] = cmd_data
                imported_count += 1
            
            self.save_commands()
            print(f"\033[92m✅ Imported {imported_count} commands successfully\033[0m")
            
        except Exception as e:
            print(f"\033[91m❌ Import failed: {e}\033[0m")

def main():
    parser = argparse.ArgumentParser(
        description='QL - Quick Launcher',
        epilog='Run without arguments for interactive mode'
    )
    parser.add_argument('command', nargs='?', help='Command alias to run')
    parser.add_argument('--version', action='version', version='ql 2.0.0')
    
    args = parser.parse_args()
    launcher = QLLauncher()
    
    if args.command:
        # Non-interactive mode - run specific command
        if args.command in launcher.commands:
            launcher.run_command_and_exit(args.command)
        else:
            print(f"\033[91m❌ Command '{args.command}' not found!\033[0m")
            available = list(launcher.commands.keys())
            if available:
                print(f"\033[37mAvailable commands: {', '.join(available)}\033[0m")
            else:
                print("\033[37mNo commands saved. Run 'ql' to add some.\033[0m")
            sys.exit(1)
    else:
        # Interactive mode
        try:
            launcher.interactive_mode()
        except KeyboardInterrupt:
            print("\n\033[96m👋 Goodbye!\033[0m")

if __name__ == "__main__":
    main()