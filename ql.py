#!/usr/bin/env python3
"""
QL - Quick Launcher
A simple CLI tool for saving and running frequently used commands and command chains
Minimal TUI version with improved UX
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
from datetime import datetime, timedelta

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
        self.flash_message = ""
        self.flash_time = 0
        self.last_exit_status = None
        self.sort_by_usage = True  # New: sort by usage by default
        
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
            self.set_flash_message(f"⚠ Error reading config: {e}", error=True)
        except Exception as e:
            self.set_flash_message(f"⚠ Unexpected error: {e}", error=True)
        
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
            self.set_flash_message(f"✗ Error saving commands: {e}", error=True)
    
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
    
    def set_flash_message(self, message, error=False, duration=2):
        """Set a flash message that will disappear after duration seconds"""
        self.flash_message = message
        self.flash_time = time.time() + duration
        if error:
            self.last_exit_status = "failed"
    
    def get_flash_message(self):
        """Get current flash message if still valid"""
        if time.time() < self.flash_time:
            return self.flash_message
        return ""
    
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
        """Validate command with inline feedback"""
        # Check for common typos
        words = command.split()
        if words:
            first_word = words[0]
            if first_word in self.common_typos:
                return command.replace(first_word, self.common_typos[first_word], 1)
        
        # Check if command exists
        words = command.split()
        if words and not words[0].startswith('./') and not '=' in words[0]:
            cmd_name = words[0]
            if not shutil.which(cmd_name) and cmd_name not in ['cd', 'export', 'source', '.']:
                # Don't interrupt flow, just note it
                pass
        
        return command
    
    def is_dangerous_command(self, command):
        """Check if command contains dangerous patterns"""
        for pattern in self.dangerous_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False
    
    def clear_screen(self):
        """Clear the terminal screen"""
        os.system('clear' if os.name == 'posix' else 'cls')
    
    def get_terminal_size(self):
        """Get terminal dimensions"""
        try:
            import shutil
            cols, rows = shutil.get_terminal_size()
            return rows, cols
        except:
            return 24, 80  # Default fallback
    
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
            all_commands = list(self.commands.items())
        else:
            all_commands = []
            for alias, cmd_data in self.commands.items():
                command = cmd_data.get('command', '')
                description = cmd_data.get('description', '')
                tags = ' '.join(cmd_data.get('tags', []))
                
                if (self.fuzzy_match(alias, self.filter_text) or 
                    self.fuzzy_match(command, self.filter_text) or
                    self.fuzzy_match(description, self.filter_text) or
                    self.fuzzy_match(tags, self.filter_text)):
                    all_commands.append((alias, cmd_data))
        
        # Sort by usage if enabled
        if self.sort_by_usage:
            return self.sort_commands_by_usage(all_commands)
        return all_commands
    
    def sort_commands_by_usage(self, commands_list):
        """Sort commands by usage frequency and recency"""
        def get_sort_key(item):
            alias, cmd_data = item
            usage_count = self.stats["usage_count"].get(alias, 0)
            last_used = self.stats["last_used"].get(alias, "")
            
            # Calculate recency score
            if last_used:
                try:
                    last_used_date = datetime.fromisoformat(last_used)
                    days_ago = (datetime.now() - last_used_date).days
                    recency_score = max(0, 30 - days_ago) / 30  # Score from 0-1
                except:
                    recency_score = 0
            else:
                recency_score = 0
            
            # Combined score: usage_count + recency bonus
            return -(usage_count + recency_score * 10)
        
        return sorted(commands_list, key=get_sort_key)
    
    def get_usage_indicator(self, alias):
        """Get usage indicator for a command"""
        count = self.stats["usage_count"].get(alias, 0)
        last_used = self.stats["last_used"].get(alias, "")
        
        if count == 0:
            return ""
        
        # Check if used recently
        if last_used:
            try:
                last_used_date = datetime.fromisoformat(last_used)
                days_ago = (datetime.now() - last_used_date).days
                if days_ago == 0:
                    indicator = "●"  # Used today
                elif days_ago <= 7:
                    indicator = "○"  # Used this week
                else:
                    indicator = " "  # Used but not recently
            except:
                indicator = " "
        else:
            indicator = " "
        
        return f"{indicator}[{count}]"
    
    def truncate_command(self, command, max_length):
        """Intelligently truncate command to fit display"""
        if len(command) <= max_length:
            return command
        
        # Try to break at logical points
        if '&&' in command:
            parts = command.split('&&')
            if len(parts[0]) < max_length - 3:
                return parts[0].strip() + '...'
        
        # Otherwise just truncate
        return command[:max_length-3] + '...'
    
    def get_help_line(self):
        """Get context-sensitive help line"""
        if self.filter_mode:
            return "[Esc] cancel • [Enter] select"
        elif self.input_mode:
            if self.input_buffer.startswith(('add ', 'chain ', 'edit ', 'remove ')):
                return "[Enter] confirm • [Esc] cancel"
            else:
                return "[Tab] complete • [Enter] run • [Esc] cancel"
        else:
            if self.commands:
                return "[1-9] quick • [/] filter • [a]dd • [s]tats • [?] help • [q]uit"
            else:
                return "[a]dd • [?] help • [q]uit"
    
    def show_main_screen(self):
        """Display the main interface - minimal version"""
        self.clear_screen()
        
        rows, cols = self.get_terminal_size()
        
        # Header with stats
        command_count = len(self.commands)
        if self.filter_mode and self.filter_text:
            filtered_count = len(self.get_filtered_commands())
            header = f"QL - Quick Launcher ({filtered_count}/{command_count} commands)"
        else:
            chains = sum(1 for cmd in self.commands.values() if cmd.get('type') == 'chain')
            if chains > 0:
                header = f"QL - Quick Launcher ({command_count} commands: {command_count - chains} links, {chains} chains)"
            else:
                header = f"QL - Quick Launcher ({command_count} commands)"
        
        # Add last command status if exists
        if self.last_exit_status:
            header += f" [last: {self.last_exit_status}]"
        
        print(header)
        print("─" * min(cols, 80))
        
        # Flash message if any
        flash_msg = self.get_flash_message()
        if flash_msg:
            print(flash_msg)
            print()
        
        # Filter mode header
        if self.filter_mode:
            print(f"/{self.filter_text}_")
            print("─" * min(cols, 80))
        
        # Get commands to display
        display_commands = self.get_filtered_commands()
        
        if not self.commands:
            print("\nNo commands saved yet. Press 'a' to add your first command.")
        elif not display_commands and self.filter_mode:
            print("\nNo commands match your filter.")
        else:
            # Calculate display parameters
            max_alias_len = max(len(alias) for alias, _ in display_commands) if display_commands else 10
            max_alias_len = min(max_alias_len, 20)  # Cap alias display length
            
            # Calculate available space for command
            # Format: "  N. alias [count] → command"
            prefix_len = 5  # "  N. "
            usage_len = 6  # " [99] "
            arrow_len = 3  # " → "
            available_for_cmd = cols - prefix_len - max_alias_len - usage_len - arrow_len - 2
            available_for_cmd = max(30, available_for_cmd)  # Minimum command display
            
            # Display commands (limited by terminal height)
            max_display = rows - 8  # Leave room for header, footer, help line
            for i, (alias, cmd_data) in enumerate(display_commands[:max_display]):
                cmd_type = cmd_data.get('type', 'link')
                command = cmd_data.get('command', '')
                
                # Format line number
                if i < 9:
                    num_str = f"{i+1}."
                else:
                    num_str = f"{i+1:2d}"
                
                # Get usage indicator
                usage = self.get_usage_indicator(alias)
                
                # Add chain marker if needed
                type_marker = " ⛓️ " if cmd_type == 'chain' else "   "
                
                # Truncate command to fit
                display_command = self.truncate_command(command, available_for_cmd)
                
                # Build the line
                if i == self.selected_index:
                    # Selected line
                    line = f" ▸{num_str} {alias:<{max_alias_len}}{type_marker}{usage:>6} → {display_command}"
                else:
                    line = f"  {num_str} {alias:<{max_alias_len}}{type_marker}{usage:>6} → {display_command}"
                
                print(line)
            
            if len(display_commands) > max_display:
                print(f"\n  ... and {len(display_commands) - max_display} more")
        
        # Bottom help line
        print()
        if self.input_mode:
            print(f"> {self.input_buffer}_")
        else:
            print()
        
        print("─" * min(cols, 80))
        print(self.get_help_line())
    
    def show_help(self):
        """Show simplified help screen"""
        self.clear_screen()
        help_text = """QL Help
─────────────────────────────────────────────

ADDING COMMANDS
  add <alias> <cmd>     Add a command
  chain <alias> <cmds>  Add command chain (&&)
  
NAVIGATION  
  1-9     Quick select      /        Filter
  j,k     Up/down          Enter    Run
  g,G     Top/bottom       d        Dry run
  
MANAGEMENT
  e       Edit selected    r        Remove
  E       Export all       I        Import

Press any key to return"""
        
        print(help_text)
        self.get_key()
    
    def show_stats(self):
        """Show minimal statistics view"""
        self.clear_screen()
        
        print("Usage Statistics")
        print("─" * 50)
        print()
        
        if not self.commands:
            print("No commands to show statistics for.")
            print("\nPress any key to return")
            self.get_key()
            return
        
        # Get usage data
        usage_data = []
        for alias, cmd_data in self.commands.items():
            count = self.stats["usage_count"].get(alias, 0)
            if count > 0:
                usage_data.append((alias, count))
        
        if not usage_data:
            print("No usage data yet. Start using commands!")
        else:
            # Sort by usage
            usage_data.sort(key=lambda x: x[1], reverse=True)
            
            # Show top 10
            print("Most used:")
            max_count = max(count for _, count in usage_data)
            for alias, count in usage_data[:10]:
                bar_length = int((count / max_count) * 20)
                bar = "█" * bar_length + "░" * (20 - bar_length)
                print(f"  {alias:<15} {bar} {count}")
        
        print()
        total_runs = sum(self.stats["usage_count"].values())
        chains = sum(1 for cmd in self.commands.values() if cmd.get('type') == 'chain')
        print(f"Total runs: {total_runs}")
        print(f"Commands: {len(self.commands)} ({len(self.commands) - chains} links, {chains} chains)")
        
        print("\nPress any key to return")
        self.get_key()
    
    def dry_run_command(self, alias):
        """Show improved dry run display"""
        if alias not in self.commands:
            return
        
        cmd_data = self.commands[alias]
        command = cmd_data.get('command', '')
        cmd_type = cmd_data.get('type', 'link')
        
        self.clear_screen()
        print(f"Dry run: {alias}")
        print("─" * 50)
        print("Would execute:")
        print(f"  {command}")
        
        # Try to expand any obvious variables
        if '$' in command or '`' in command:
            print("\nWith expansions:")
            # Simple date expansion for demonstration
            import re
            expanded = command
            date_pattern = r'\$\(date \+%Y%m%d\)'
            if re.search(date_pattern, expanded):
                expanded = re.sub(date_pattern, datetime.now().strftime('%Y%m%d'), expanded)
                print(f"  {expanded}")
        
        if cmd_type == 'chain':
            print("\n(Executes as command chain - stops on first failure)")
        
        if self.is_dangerous_command(command):
            print("\n⚠ Warning: This command appears potentially dangerous!")
        
        print("\nPress any key to return")
        self.get_key()
    
    def parse_input(self, user_input):
        """Parse and execute user input"""
        if not user_input.strip():
            return True
        
        parts = user_input.strip().split()
        command = parts[0].lower()
        
        if command in ['quit', 'q', 'exit']:
            return False
        elif command == 'help' or command == '?':
            self.show_help()
        elif command == 'stats' or command == 's':
            self.show_stats()
        elif command == 'add' or command == 'a':
            if len(parts) < 3:
                self.set_flash_message("✗ Usage: add <alias> <command>", error=True)
            else:
                alias = parts[1]
                cmd = ' '.join(parts[2:])
                self.add_command(alias, cmd, 'link')
        elif command == 'chain':
            if len(parts) < 3:
                self.set_flash_message("✗ Usage: chain <alias> <cmd1> && <cmd2>", error=True)
            else:
                alias = parts[1]
                cmd = ' '.join(parts[2:])
                self.add_command(alias, cmd, 'chain')
        elif command == 'edit' or command == 'e':
            if len(parts) < 2:
                # Edit selected command
                display_commands = self.get_filtered_commands()
                if display_commands and 0 <= self.selected_index < len(display_commands):
                    self.edit_command(display_commands[self.selected_index][0])
                else:
                    self.set_flash_message("✗ No command selected", error=True)
            else:
                self.edit_command(parts[1])
        elif command == 'remove' or command == 'r':
            if len(parts) < 2:
                # Remove selected command
                display_commands = self.get_filtered_commands()
                if display_commands and 0 <= self.selected_index < len(display_commands):
                    self.remove_command(display_commands[self.selected_index][0])
                else:
                    self.set_flash_message("✗ No command selected", error=True)
            else:
                self.remove_command(parts[1])
        elif command == 'export' or command == 'E':
            if len(parts) < 2:
                self.set_flash_message("✗ Usage: export <filename>", error=True)
            else:
                self.export_commands(parts[1])
        elif command == 'import' or command == 'I':
            if len(parts) < 2:
                self.set_flash_message("✗ Usage: import <filename>", error=True)
            else:
                self.import_commands(parts[1])
        else:
            # Try to run as a command alias
            if command in self.commands:
                return self.run_command_and_exit(command)
            else:
                self.set_flash_message(f"✗ Unknown command: {command}", error=True)
        
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
    
    def run_command_and_exit(self, alias):
        """Run command by feeding it directly to the terminal"""
        if alias not in self.commands:
            return True
        
        # Clean up any old scripts first
        self.cleanup_old_scripts()
        
        # Update usage statistics
        self.update_usage_stats(alias)
        
        # Move to front for recent usage
        if self.sort_by_usage:
            self.save_stats()  # Save immediately so sorting reflects new usage
        
        cmd_data = self.commands[alias]
        command = cmd_data.get('command', '')
        cmd_type = cmd_data.get('type', 'link')
        
        # Safety check for dangerous commands
        if self.is_dangerous_command(command):
            print("\n⚠ Dangerous command detected!")
            response = input("Run anyway? y/N: ").lower()
            if response != 'y':
                self.set_flash_message("Command cancelled")
                return True
        
        # Create execution script
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
            if cmd_type == 'chain':
                script_content = f"""#!/bin/bash
# QL Command Executor - Chain Command
trap 'rm -f "$0"' EXIT

cd /

echo "Running chain: {alias}"
echo "──────────────────────────────────────────────────"

set -e
set -o pipefail

{command}

echo "──────────────────────────────────────────────────"
echo "✓ Chain completed"

exec {shell}
"""
            else:
                script_content = f"""#!/bin/bash
# QL Command Executor
trap 'rm -f "$0"' EXIT

cd /

echo "Running: {alias}"
echo "──────────────────────────────────────────────────"

{command}

exit_code=$?

echo "──────────────────────────────────────────────────"
if [ $exit_code -eq 0 ]; then
    echo "✓ Command completed"
else
    echo "✗ Command failed (exit code $exit_code)"
fi

exec {shell}
"""
            
            temp_script.write(script_content)
            temp_script.close()
            
            # Make executable
            os.chmod(temp_script.name, stat.S_IRWXU)
            
            # Clear screen and launch
            self.clear_screen()
            
            # Replace current process with the script
            os.execv('/bin/bash', ['/bin/bash', temp_script.name])
            
        except Exception as e:
            self.set_flash_message(f"✗ Error: {e}", error=True)
            return True
        
        return False
    
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
                
                elif key.isdigit() and not self.input_mode and not self.filter_mode:
                    # Quick select with number keys (1-9)
                    num = int(key) - 1
                    if 0 <= num < len(display_commands) and num < 9:
                        selected_alias = display_commands[num][0]
                        if not self.run_command_and_exit(selected_alias):
                            break
                
                elif key == 'UP' or key == 'k':
                    if not self.input_mode and not self.filter_mode and display_commands:
                        self.selected_index = max(0, self.selected_index - 1)
                
                elif key == 'DOWN' or key == 'j':
                    if not self.input_mode and not self.filter_mode and display_commands:
                        self.selected_index = min(len(display_commands) - 1, self.selected_index + 1)
                
                elif key == 'g' and not self.input_mode and not self.filter_mode:
                    # Go to top
                    self.selected_index = 0
                
                elif key == 'G' and not self.input_mode and not self.filter_mode:
                    # Go to bottom
                    if display_commands:
                        self.selected_index = len(display_commands) - 1
                
                elif key == 'd' and display_commands and not self.input_mode and not self.filter_mode:
                    # Dry run
                    if 0 <= self.selected_index < len(display_commands):
                        selected_alias = display_commands[self.selected_index][0]
                        self.dry_run_command(selected_alias)
                
                elif key == '/' and not self.input_mode:
                    # Enter filter mode
                    self.filter_mode = True
                    self.filter_text = ""
                    self.selected_index = 0
                
                elif key == '?' and not self.input_mode and not self.filter_mode:
                    self.show_help()
                
                elif key == 's' and not self.input_mode and not self.filter_mode:
                    self.show_stats()
                
                elif key == 'a' and not self.input_mode and not self.filter_mode:
                    self.input_mode = True
                    self.input_buffer = "add "
                
                elif key == 'e' and not self.input_mode and not self.filter_mode:
                    if display_commands and 0 <= self.selected_index < len(display_commands):
                        self.edit_command(display_commands[self.selected_index][0])
                
                elif key == 'r' and not self.input_mode and not self.filter_mode:
                    if display_commands and 0 <= self.selected_index < len(display_commands):
                        self.remove_command(display_commands[self.selected_index][0])
                
                elif key == 'q' and not self.input_mode and not self.filter_mode:
                    break
                
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
                    elif self.input_mode:
                        self.input_buffer += key
                    else:
                        # Start input mode for any other key
                        self.input_mode = True
                        self.input_buffer = key
                    
            except KeyboardInterrupt:
                break
            except Exception:
                continue
    
    def add_command(self, alias, command, cmd_type='link'):
        """Add a new command with validation"""
        # Basic validation
        if not alias or not alias.strip():
            self.set_flash_message("✗ Alias cannot be empty", error=True)
            return
            
        if not command or not command.strip():
            self.set_flash_message("✗ Command cannot be empty", error=True)
            return
            
        # Clean up alias and command
        alias = alias.strip()
        command = command.strip()
        
        # Check for problematic characters in alias
        if not re.match(r'^[a-zA-Z0-9_-]+$', alias):
            self.set_flash_message("✗ Alias: only letters, numbers, - and _", error=True)
            return
        
        # Validate command
        command = self.validate_command(command)
        
        # Check if exists
        if alias in self.commands:
            # Quick confirmation
            print(f"\n'{alias}' already exists. Overwrite? y/N: ", end='', flush=True)
            response = self.get_key().lower()
            if response != 'y':
                self.set_flash_message("Command not added")
                return
        
        self.commands[alias] = {
            "type": cmd_type,
            "command": command,
            "description": "",
            "tags": [],
            "created": datetime.now().isoformat()
        }
        self.save_commands()
        
        self.set_flash_message(f"✓ Added '{alias}'")
        
        # Reset selection to new command
        display_commands = self.get_filtered_commands()
        for i, (cmd_alias, _) in enumerate(display_commands):
            if cmd_alias == alias:
                self.selected_index = i
                break
    
    def edit_command(self, alias):
        """Edit an existing command"""
        if alias not in self.commands:
            self.set_flash_message(f"✗ Command '{alias}' not found", error=True)
            return
        
        cmd_data = self.commands[alias]
        current_command = cmd_data.get('command', '')
        
        # Simple inline edit
        print(f"\nEdit '{alias}':")
        print(f"Current: {current_command}")
        print("New command (Enter to cancel): ", end='', flush=True)
        
        # Get new command
        new_command = input().strip()
        if new_command:
            self.commands[alias]['command'] = self.validate_command(new_command)
            self.save_commands()
            self.set_flash_message(f"✓ Updated '{alias}'")
        else:
            self.set_flash_message("Edit cancelled")
    
    def remove_command(self, alias):
        """Remove a command with minimal confirmation"""
        if alias not in self.commands:
            self.set_flash_message(f"✗ Command '{alias}' not found", error=True)
            return
        
        # Quick confirmation
        print(f"\nRemove '{alias}'? y/N: ", end='', flush=True)
        response = self.get_key().lower()
        
        if response == 'y':
            del self.commands[alias]
            # Also remove from stats
            if alias in self.stats["usage_count"]:
                del self.stats["usage_count"][alias]
            if alias in self.stats["last_used"]:
                del self.stats["last_used"][alias]
            
            self.save_commands()
            self.save_stats()
            self.set_flash_message(f"✓ Removed '{alias}'")
            
            # Adjust selection if needed
            display_commands = self.get_filtered_commands()
            if self.selected_index >= len(display_commands):
                self.selected_index = max(0, len(display_commands) - 1)
        else:
            self.set_flash_message("Remove cancelled")
    
    def export_commands(self, filename):
        """Export commands to a file"""
        try:
            export_data = {
                'commands': dict(self.commands),
                'exported_at': datetime.now().isoformat(),
                'version': '2.0.0'
            }
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            self.set_flash_message(f"✓ Exported {len(self.commands)} commands")
        except Exception as e:
            self.set_flash_message(f"✗ Export failed: {e}", error=True)
    
    def import_commands(self, filename):
        """Import commands from a file"""
        if not os.path.exists(filename):
            self.set_flash_message(f"✗ File '{filename}' not found", error=True)
            return
        
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Handle both new export format and old format
            if 'commands' in data:
                imported_commands = data['commands']
            else:
                imported_commands = data
            
            # Quick conflict check
            conflicts = [alias for alias in imported_commands if alias in self.commands]
            
            if conflicts:
                print(f"\n{len(conflicts)} conflicts found. Overwrite? y/N: ", end='', flush=True)
                response = self.get_key().lower()
                if response != 'y':
                    self.set_flash_message("Import cancelled")
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
            self.set_flash_message(f"✓ Imported {imported_count} commands")
            
        except Exception as e:
            self.set_flash_message(f"✗ Import failed: {e}", error=True)

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
            print(f"✗ Command '{args.command}' not found")
            available = list(launcher.commands.keys())
            if available:
                print(f"Available: {', '.join(available[:5])}")
                if len(available) > 5:
                    print(f"... and {len(available) - 5} more")
            else:
                print("No commands saved. Run 'ql' to add some.")
            sys.exit(1)
    else:
        # Interactive mode
        try:
            launcher.interactive_mode()
        except KeyboardInterrupt:
            print("\n")

if __name__ == "__main__":
    main()