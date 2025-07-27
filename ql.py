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

class UIManager:
    """Handles all UI rendering and keyboard input"""
    
    def __init__(self):
        self.selected_index = 0
        self.input_buffer = ""
        self.input_mode = False
        self.filter_mode = False
        self.filter_text = ""
        self.show_preview = True
        self.first_run = True
    
    def safe_truncate(self, text, max_length, suffix="..."):
        """Safely truncate text to avoid string length errors"""
        if not text:
            return ""
        
        try:
            text_str = str(text)
            if len(text_str) <= max_length:
                return text_str
            else:
                return text_str[:max_length - len(suffix)] + suffix
        except (ValueError, OverflowError, MemoryError):
            return "[text too long to display]"
        
    def clear_screen(self):
        """Clear the terminal screen completely"""
        # More thorough screen clearing
        if os.name == 'posix':
            # Clear screen and move cursor to top-left
            print('\033[2J\033[H', end='', flush=True)
            # Also clear scrollback buffer on some terminals
            print('\033[3J', end='', flush=True)
        else:
            os.system('cls')
        
        # Reset any terminal formatting
        print('\033[0m', end='', flush=True)
    
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
    
    def fuzzy_match(self, text, pattern):
        """Combined substring + fuzzy matching for intuitive search"""
        if not pattern:
            return True
        
        try:
            text_str = str(text).lower()
            pattern_str = str(pattern).lower()
            
            # First try substring search (most intuitive)
            if pattern_str in text_str:
                return True
            
            # Fall back to fuzzy matching (characters in order)
            i = 0
            for char in text_str:
                if i < len(pattern_str) and char == pattern_str[i]:
                    i += 1
            return i == len(pattern_str)
        except (ValueError, OverflowError, MemoryError):
            return False
    
    def show_message_and_pause(self, title, lines, wait_text="Press Enter to continue..."):
        """Display a message with clean formatting and wait for user input"""
        self.ui.clear_screen()
        print()  # Top padding
        
        if title:
            print(title)
            print()
        
        for line in lines:
            print(line)
        
        print()
        input(f"\033[90m{wait_text}\033[0m")
    
    def get_filtered_templates(self, templates, filter_text=""):
        """Get templates filtered by current filter text using fuzzy matching"""
        if not filter_text:
            return list(templates.items())
        
        filtered = []
        for name, template_data in templates.items():
            template_command = template_data.get('template', '')
            description = template_data.get('description', '')
            placeholders = ' '.join(template_data.get('placeholders', []))
            
            if (self.fuzzy_match(name, filter_text) or 
                self.fuzzy_match(template_command, filter_text) or
                self.fuzzy_match(description, filter_text) or
                self.fuzzy_match(placeholders, filter_text)):
                filtered.append((name, template_data))
        return filtered


class CommandManager:
    """Manages command CRUD operations and execution"""
    
    def __init__(self, config_dir):
        self.config_dir = config_dir
        self.config_file = self.config_dir / '.qlcom'
        self.stats_file = self.config_dir / '.qlstats'
        
        self.commands = self.load_commands()
        self.stats = self.load_stats()
        
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
        
        return True  # Success
    
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
            return True
        else:
            print("\033[37mCommand not removed.\033[0m")
            return False


class TemplateManager:
    """Manages template CRUD operations and execution"""
    
    def __init__(self, config_dir):
        self.config_dir = config_dir
        self.templates_file = self.config_dir / '.qltemplates'
        self.templates = self.load_templates()
    
    def load_templates(self):
        """Load templates from config file, creating defaults if needed"""
        # Default templates to create if file doesn't exist
        default_templates = {
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
        
        if not self.templates_file.exists():
            # Create template file with defaults
            try:
                with open(self.templates_file, 'w', encoding='utf-8') as f:
                    json.dump(default_templates, f, indent=2, ensure_ascii=False)
            except (IOError, OSError) as e:
                print(f"\033[93m⚠️  Warning: Error creating template file: {e}\033[0m")
                print(f"\033[37mUsing built-in templates.\033[0m")
                return default_templates
            return default_templates
        
        try:
            with open(self.templates_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                
                if not content:
                    # Empty file, recreate with defaults
                    with open(self.templates_file, 'w', encoding='utf-8') as f:
                        json.dump(default_templates, f, indent=2, ensure_ascii=False)
                    return default_templates
                
                # Try to load JSON
                templates = json.loads(content)
                
                # Validate structure
                validated_templates = {}
                for name, template_data in templates.items():
                    if isinstance(template_data, dict) and all(key in template_data for key in ['template', 'description', 'placeholders']):
                        validated_templates[name] = template_data
                
                if not validated_templates:
                    # No valid templates, recreate with defaults
                    with open(self.templates_file, 'w', encoding='utf-8') as f:
                        json.dump(default_templates, f, indent=2, ensure_ascii=False)
                    return default_templates
                
                return validated_templates
                
        except (IOError, OSError, json.JSONDecodeError) as e:
            print(f"\033[93m⚠️  Warning: Error reading template file: {e}\033[0m")
            print(f"\033[37mRecreating with default templates.\033[0m")
            try:
                with open(self.templates_file, 'w', encoding='utf-8') as f:
                    json.dump(default_templates, f, indent=2, ensure_ascii=False)
            except:
                pass
            return default_templates
    
    def save_templates(self):
        """Save templates to config file"""
        try:
            with open(self.templates_file, 'w', encoding='utf-8') as f:
                json.dump(self.templates, f, indent=2, ensure_ascii=False)
        except (IOError, OSError) as e:
            print(f"\033[91m❌ Error saving templates: {e}\033[0m")
    
    def extract_placeholders(self, command):
        """Extract {placeholder} patterns from command"""
        matches = re.findall(r'\{([^}]+)\}', command)
        return list(dict.fromkeys(matches))  # Remove duplicates, preserve order
    
    def save_template(self, name, command):
        """Save a new template to file"""
        # Check for problematic characters in template name
        if not re.match(r'^[a-zA-Z0-9_-]+$', name):
            print("\033[91m❌ Template name can only contain letters, numbers, hyphens and underscores\033[0m")
            return
        
        placeholders = self.extract_placeholders(command)
        
        if name in self.templates:
            print(f"\033[93m⚠️  Template '{name}' already exists!\033[0m")
            print(f"\033[37mCurrent: {self.templates[name]['template']}\033[0m")
            response = input("\033[96mOverwrite? (y/N): \033[0m").lower()
            if response != 'y':
                print("\033[37mTemplate not saved.\033[0m")
                return
        
        print(f"\033[94m📝 Optional: Add description for template\033[0m")
        description = input("\033[96mDescription (optional): \033[0m").strip()
        
        self.templates[name] = {
            'template': command,
            'description': description or f"Template: {name}",
            'placeholders': placeholders
        }
        self.save_templates()
        
        placeholder_text = ""
        if placeholders:
            placeholder_text = f" with placeholders: {', '.join(placeholders)}"
        print(f"\033[92m✅ Saved template '{name}'{placeholder_text}\033[0m")
        if description:
            print(f"\033[90m📝 {description}\033[0m")
        print(f"\033[90m📁 Saved to: {self.templates_file}\033[0m")
    
    def edit_template(self, name):
        """Edit an existing template"""
        if name not in self.templates:
            print(f"\033[91m❌ Template '{name}' not found!\033[0m")
            if self.templates:
                print(f"\033[37mAvailable templates: {', '.join(self.templates.keys())}\033[0m")
            return
        
        template = self.templates[name]
        current_command = template['template']
        current_description = template['description']
        current_placeholders = template.get('placeholders', [])
        
        print(f"\033[94mEditing template: {name}\033[0m")
        print(f"\033[90mCurrent command: {current_command}\033[0m")
        print(f"\033[90mCurrent description: {current_description}\033[0m")
        if current_placeholders:
            print(f"\033[90mCurrent placeholders: {', '.join(current_placeholders)}\033[0m")
        print()
        
        # Edit command
        new_command = input(f"\033[96mNew command (Enter to keep current): \033[0m").strip()
        if new_command:
            current_command = new_command
        
        # Edit description
        new_description = input(f"\033[96mDescription (Enter to keep current): \033[0m").strip()
        if new_description:
            current_description = new_description
        
        # Update placeholders based on new command
        new_placeholders = self.extract_placeholders(current_command)
        
        # Update template
        self.templates[name] = {
            'template': current_command,
            'description': current_description,
            'placeholders': new_placeholders
        }
        self.save_templates()
        
        placeholder_text = ""
        if new_placeholders:
            placeholder_text = f" with placeholders: {', '.join(new_placeholders)}"
        print(f"\033[92m✅ Updated template '{name}'{placeholder_text}\033[0m")
    
    def remove_template(self, name):
        """Remove a template"""
        if name not in self.templates:
            print(f"\033[91m❌ Template '{name}' not found!\033[0m")
            if self.templates:
                print(f"\033[37mAvailable templates: {', '.join(self.templates.keys())}\033[0m")
            return
        
        template = self.templates[name]
        print(f"\033[93m⚠️  Remove template '{name}'?\033[0m")
        print(f"\033[37mTemplate: {template['template']}\033[0m")
        response = input("\033[96mConfirm removal? (y/N): \033[0m").lower()
        
        if response == 'y':
            del self.templates[name]
            self.save_templates()
            print(f"\033[92m✅ Removed template '{name}'\033[0m")
            return True
        else:
            print("\033[37mTemplate not removed.\033[0m")
            return False


class QLLauncher:
    def __init__(self):
        # Force QL to always run from root directory for maximum cd compatibility
        os.chdir('/')
        
        # Ensure ~/.local/bin exists
        self.config_dir = Path.home() / '.local' / 'bin'
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Clean up any leftover scripts from previous sessions
        self.cleanup_old_scripts()
        
        self.command_manager = CommandManager(self.config_dir)
        self.template_manager = TemplateManager(self.config_dir)
        self.ui = UIManager()
        
        # Application state
        self.current_mode = 'command'  # 'command' or 'template'
    
    def reset_ui_state(self):
        """Reset UI state when switching modes"""
        self.ui.selected_index = 0
        self.ui.filter_mode = False
        self.ui.filter_text = ""
        self.ui.input_mode = False
        self.ui.input_buffer = ""
    
    def cleanup_old_scripts(self):
        """Clean up any leftover QL temp scripts"""
        # Clean from our local temp directory
        script_dir = self.config_dir / 'tmp'
        
        if not script_dir.exists():
            return
            
        try:
            pattern = str(script_dir / '*_ql.sh')
            for script_path in glob.glob(pattern):
                try:
                    if os.path.exists(script_path):
                        # Clean up scripts older than 5 minutes (more aggressive)
                        age = time.time() - os.path.getmtime(script_path)
                        if age > 300:  # 5 minutes
                            with open(script_path, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()
                                if '# QL Command Executor' in content:
                                    os.unlink(script_path)
                                    print(f"\033[90m🧹 Cleaned up old script: {os.path.basename(script_path)}\033[0m")
                except (OSError, IOError):
                    pass  # Ignore individual file errors
        except (OSError, IOError):
            pass  # Ignore directory errors
    
    def show_template_list(self):
        """Interactive template management interface"""
        self.template_interactive_mode()
    
    def template_interactive_mode_loop(self):
        """Interactive template management with navigation - returns True to continue, False to exit"""
        while True:
            if not self.template_interactive_mode():
                return False
            # If we reach here, we're switching back to command mode
            self.current_mode = 'command'
            self.reset_ui_state()
            return True
    
    def template_interactive_mode(self):
        """Interactive template management with navigation"""
        # Reset UI state for template mode
        self.ui.selected_index = 0
        self.ui.filter_mode = False
        self.ui.filter_text = ""
        self.ui.input_mode = False
        self.ui.input_buffer = ""
        
        while True:
            self.show_template_screen()
            
            try:
                key = self.ui.get_key()
                display_templates = self.ui.get_filtered_templates(
                    self.template_manager.templates, 
                    self.ui.filter_text
                )
                
                if key == '\r' or key == '\n':  # Enter key
                    if self.ui.filter_mode:
                        # Exit filter mode
                        self.ui.filter_mode = False
                        self.ui.selected_index = 0
                    elif self.ui.input_mode and self.ui.input_buffer.strip():
                        # Process template command
                        if not self.parse_template_input(self.ui.input_buffer):
                            break
                        self.ui.input_buffer = ""
                        self.ui.input_mode = False
                    elif display_templates and not self.ui.input_mode:
                        # Run selected template
                        if 0 <= self.ui.selected_index < len(display_templates):
                            selected_name = display_templates[self.ui.selected_index][0]
                            self.run_template(selected_name)
                            break
                
                elif key.isdigit() and not self.ui.input_mode and not self.ui.filter_mode:
                    # Quick select with number keys (1-9)
                    num = int(key) - 1
                    if 0 <= num < len(display_templates) and num < 9:
                        selected_name = display_templates[num][0]
                        self.run_template(selected_name)
                        break
                
                elif key == 'e' and display_templates and not self.ui.input_mode and not self.ui.filter_mode:
                    # Edit selected template
                    if 0 <= self.ui.selected_index < len(display_templates):
                        selected_name = display_templates[self.ui.selected_index][0]
                        self.template_manager.edit_template(selected_name)
                        input("\033[90mPress Enter to continue...\033[0m")
                
                elif key == 'd' and display_templates and not self.ui.input_mode and not self.ui.filter_mode:
                    # Dry run preview of selected template
                    if 0 <= self.ui.selected_index < len(display_templates):
                        selected_name = display_templates[self.ui.selected_index][0]
                        self.show_template_preview(selected_name)
                
                elif key == 'r' and display_templates and not self.ui.input_mode and not self.ui.filter_mode:
                    # Remove selected template
                    if 0 <= self.ui.selected_index < len(display_templates):
                        selected_name = display_templates[self.ui.selected_index][0]
                        success = self.template_manager.remove_template(selected_name)
                        if success:
                            # Adjust selection if needed
                            display_templates = self.ui.get_filtered_templates(
                                self.template_manager.templates, 
                                self.ui.filter_text
                            )
                            if self.ui.selected_index >= len(display_templates):
                                self.ui.selected_index = max(0, len(display_templates) - 1)
                        input("\033[90mPress Enter to continue...\033[0m")
                
                elif key == 'n' and not self.ui.input_mode and not self.ui.filter_mode:
                    # Create new template
                    self.ui.input_mode = True
                    self.ui.input_buffer = "new "
                
                elif key == 'c' and display_templates and not self.ui.input_mode and not self.ui.filter_mode:
                    # Copy template command to clipboard
                    if 0 <= self.ui.selected_index < len(display_templates):
                        selected_name = display_templates[self.ui.selected_index][0]
                        self.copy_template_to_clipboard(selected_name)
                
                elif key == 'p' and not self.ui.input_mode and not self.ui.filter_mode:
                    # Toggle preview
                    self.ui.show_preview = not self.ui.show_preview
                
                elif key == 'UP' and display_templates and not self.ui.input_mode and not self.ui.filter_mode:
                    self.ui.selected_index = max(0, self.ui.selected_index - 1)
                
                elif key == 'DOWN' and display_templates and not self.ui.input_mode and not self.ui.filter_mode:
                    self.ui.selected_index = min(len(display_templates) - 1, self.ui.selected_index + 1)
                
                elif key == '/' and not self.ui.input_mode:
                    # Enter filter mode
                    self.ui.filter_mode = True
                    self.ui.filter_text = ""
                    self.ui.selected_index = 0
                
                elif key == '\x7f' or key == '\x08':  # Backspace
                    if self.ui.filter_mode:
                        if self.ui.filter_text:
                            self.ui.filter_text = self.ui.filter_text[:-1]
                            self.ui.selected_index = 0
                        else:
                            self.ui.filter_mode = False
                    elif self.ui.input_mode and self.ui.input_buffer:
                        self.ui.input_buffer = self.ui.input_buffer[:-1]
                        if not self.ui.input_buffer:
                            self.ui.input_mode = False
                
                elif key == '\x1b':  # Escape key
                    if self.ui.filter_mode:
                        self.ui.filter_mode = False
                        self.ui.filter_text = ""
                        self.ui.selected_index = 0
                    elif self.ui.input_mode:
                        self.ui.input_mode = False
                        self.ui.input_buffer = ""
                    else:
                        return False  # Exit template mode
                
                elif key == '\x03':  # Ctrl+C
                    return False
                
                elif key == '\x14':  # Ctrl+T - Switch to command mode
                    return True
                
                elif key == 'q':  # Quit
                    return False
                
                elif key.isprintable():
                    if self.ui.filter_mode:
                        self.ui.filter_text += key
                        self.ui.selected_index = 0
                    else:
                        if not self.ui.input_mode:
                            self.ui.input_mode = True
                            self.ui.input_buffer = ""
                        self.ui.input_buffer += key
                    
            except KeyboardInterrupt:
                return False
            except Exception:
                continue
    
    def show_template_screen(self):
        """Display the interactive template management screen"""
        self.ui.clear_screen()
        
        # Header
        print("\033[96m" + "=" * 60)
        print("🎨 Template Management")
        print("=" * 60 + "\033[0m")
        print()
        
        # Get templates to display (filtered or all)
        display_templates = self.ui.get_filtered_templates(
            self.template_manager.templates, 
            self.ui.filter_text
        )
        
        if not self.template_manager.templates:
            print("\033[94m📝 No templates saved yet!\033[0m")
            print("\033[37mGet started by creating your first template:\033[0m")
            print("\033[36m   n\033[0m                           \033[37m- Create new template\033[0m")
            print("\033[36m   new <name> <command>\033[0m         \033[37m- Create template with command\033[0m")
            print()
        else:
            # Show filter status and stats
            template_count = len(self.template_manager.templates)
            if self.ui.filter_mode:
                print(f"\033[94m🔍 Filter: \"{self.ui.filter_text}\" ({len(display_templates)}/{template_count} templates)\033[0m")
            else:
                print(f"\033[94m📊 {template_count} templates available\033[0m")
            print()
            
            if not display_templates:
                print("\033[93m📭 No templates match your filter.\033[0m")
            else:
                # Calculate max name length for alignment
                max_name_len = max(len(name) for name, _ in display_templates) if display_templates else 10
                
                for i, (name, template_data) in enumerate(display_templates):
                    template_command = template_data.get('template', '')
                    description = template_data.get('description', '')
                    placeholders = template_data.get('placeholders', [])
                    
                    # Truncate long templates for display with safe handling
                    display_template = self.ui.safe_truncate(template_command, 40)
                    
                    # Show number for quick selection (1-9)
                    if i < 9:
                        num_display = f"{i+1}"
                    else:
                        num_display = f"{i+1:2d}" if i < 99 else "##"
                    
                    # Placeholder indicator
                    placeholder_indicator = f" [{len(placeholders)}]" if placeholders else ""
                    
                    # Highlight selected template
                    if i == self.ui.selected_index:
                        print(f"\033[1;97;44m {num_display}. 🎨 {name:<{max_name_len}}{placeholder_indicator} → {display_template}\033[0m")
                        if self.ui.show_preview:
                            self.show_template_preview_inline(name, template_data)
                    else:
                        # Show clickable numbers (1-9) in bright color, others in dim
                        num_color = "\033[96m" if i < 9 else "\033[90m"
                        print(f"{num_color} {num_display}.\033[0m 🎨 \033[36m{name:<{max_name_len}}\033[90m{placeholder_indicator}\033[0m \033[37m→\033[0m {display_template}")
        
        print()
        print("\033[94m🎨 Template Actions:\033[0m")
        print("\033[36m   Enter\033[0m                     \033[37m- Run selected template\033[0m")
        print("\033[36m   1-9\033[0m                       \033[37m- Quick run (first 9 templates)\033[0m")
        print("\033[36m   e\033[0m                         \033[37m- Edit selected template\033[0m")
        print("\033[36m   d\033[0m                         \033[37m- Preview selected template\033[0m")
        print("\033[36m   r\033[0m                         \033[37m- Remove selected template\033[0m")
        print("\033[36m   n\033[0m                         \033[37m- Create new template\033[0m")
        if CLIPBOARD_AVAILABLE:
            print("\033[36m   c\033[0m                         \033[37m- Copy template to clipboard\033[0m")
        print("\033[36m   /\033[0m                         \033[37m- Filter templates\033[0m")
        print("\033[36m   p\033[0m                         \033[37m- Toggle preview on/off\033[0m")
        print("\033[36m   ↑/↓ arrows\033[0m                \033[37m- Navigate templates\033[0m")
        print("\033[36m   Ctrl+T\033[0m                    \033[37m- Switch to command mode\033[0m")
        print("\033[36m   Escape or q\033[0m               \033[37m- Exit template mode\033[0m")
        print()
        
        print(f"\033[90m📁 Templates stored in: {self.template_manager.templates_file}\033[0m")
        
        # Input prompt
        if self.ui.filter_mode:
            print(f"\033[95m🔍 Filter: {self.ui.filter_text}\033[7m \033[0m")
        elif self.ui.input_mode:
            print(f"\033[96m> {self.ui.input_buffer}\033[7m \033[0m")
        else:
            print("\033[96m> \033[0m", end="", flush=True)
    
    def show_template_preview_inline(self, name, template_data):
        """Show inline preview of selected template"""
        description = template_data.get('description', '')
        placeholders = template_data.get('placeholders', [])
        
        preview_parts = []
        if description:
            preview_parts.append(f"📝 {description}")
        if placeholders:
            preview_parts.append(f"🔧 Placeholders: {', '.join(placeholders)}")
        
        if preview_parts:
            print(f"\033[90m   └─ {' • '.join(preview_parts)}\033[0m")
        
        # Show template command preview with safe handling
        template_command = template_data.get('template', '')
        display_template = self.ui.safe_truncate(template_command, 80)
        print(f"\033[90m   └─ Template: {display_template}\033[0m")
    
    def show_template_preview(self, name):
        """Show full preview of selected template"""
        if name not in self.template_manager.templates:
            return
        
        template_data = self.template_manager.templates[name]
        template_command = template_data.get('template', '')
        description = template_data.get('description', '')
        placeholders = template_data.get('placeholders', [])
        
        self.ui.clear_screen()
        print()  # Top padding
        
        print(f"\033[95m🔍 Template preview: 🎨 {name}\033[0m")
        if description:
            print(f"\033[90m📝 {description}\033[0m")
        if placeholders:
            print(f"\033[90m🔧 Placeholders: {', '.join(placeholders)}\033[0m")
        print()
        print(f"\033[37m{template_command}\033[0m")
        print()
        
        if placeholders:
            print(f"\033[90mThis template requires {len(placeholders)} placeholder(s) when run\033[0m")
        
        print()
        input("\033[90mPress Enter to continue...\033[0m")
    
    def copy_template_to_clipboard(self, name):
        """Copy template to clipboard"""
        if not CLIPBOARD_AVAILABLE:
            self.ui.clear_screen()
            print()
            print("\033[91m❌ Clipboard support not available (install pyperclip)\033[0m")
            print()
            input("\033[90mPress Enter to continue...\033[0m")
            return
        
        if name not in self.template_manager.templates:
            return
        
        template_data = self.template_manager.templates[name]
        template_command = template_data.get('template', '')
        
        self.ui.clear_screen()
        print()  # Top padding
        
        try:
            pyperclip.copy(template_command)
            print(f"\033[92m📋 Copied template '{name}' to clipboard!\033[0m")
            print(f"\033[90mTemplate: {template_command}\033[0m")
        except Exception as e:
            print(f"\033[91m❌ Error copying to clipboard: {e}\033[0m")
        
        print()
        input("\033[90mPress Enter to continue...\033[0m")
    
    def parse_template_input(self, user_input):
        """Parse and execute template input commands"""
        if not user_input.strip():
            return True
        
        parts = user_input.strip().split()
        command = parts[0].lower()
        
        if command == 'new':
            if len(parts) < 3:
                print("\033[91m❌ Usage: new <name> <template_command>\033[0m")
                input("\033[90mPress Enter to continue...\033[0m")
            else:
                name = parts[1]
                template_command = ' '.join(parts[2:])
                self.template_manager.save_template(name, template_command)
                input("\033[90mPress Enter to continue...\033[0m")
        else:
            print(f"\033[91m❌ Unknown template command: {command}\033[0m")
            print("\033[37mAvailable commands: new\033[0m")
            input("\033[90mPress Enter to continue...\033[0m")
        
        return True
    
    def run_template(self, name):
        """Run a saved template with placeholder prompts"""
        if name not in self.template_manager.templates:
            print(f"\033[91m❌ Template '{name}' not found!\033[0m")
            if self.template_manager.templates:
                print(f"\033[37mAvailable templates: {', '.join(self.template_manager.templates.keys())}\033[0m")
            return
        
        template = self.template_manager.templates[name]
        template_command = template['template']
        placeholders = self.template_manager.extract_placeholders(template_command)
        
        print(f"\033[94m🎨 Running template: {name}\033[0m")
        print(f"\033[90m{template['description']}\033[0m")
        print(f"\033[90mTemplate: {template_command}\033[0m")
        print()
        
        if not placeholders:
            print("\033[90mNo placeholders found. Running directly...\033[0m")
            self.run_direct_command(template_command)
            return
        
        # Collect placeholder values
        values = {}
        for placeholder in placeholders:
            value = input(f"\033[96m{placeholder}: \033[0m").strip()
            if not value:
                print("\033[37mTemplate cancelled.\033[0m")
                return
            values[placeholder] = value
        
        # Replace placeholders and execute
        final_command = template_command
        for placeholder, value in values.items():
            final_command = final_command.replace(f"{{{placeholder}}}", value)
        
        print()
        print(f"\033[90mExecuting: {final_command}\033[0m")
        self.run_direct_command(final_command)
    
    def run_direct_command(self, command):
        """Execute a command directly without saving"""
        # Create and execute script similar to run_command_and_exit but don't save
        script_path = self._create_execution_script("direct", command, 'link')
        if not script_path:
            return
        
        # Clear screen and launch
        self.ui.clear_screen()
        print(f"\033[96m🚀 Executing command...\033[0m")
        
        # Replace current process with the script
        try:
            os.execv('/bin/bash', ['/bin/bash', script_path])
        except (OSError, IOError) as e:
            print(f"\033[91m❌ Error executing command: {e}\033[0m")
            try:
                os.unlink(script_path)
            except:
                pass
            input("\033[90mPress Enter to continue...\033[0m")
    
    def confirm_dangerous_command(self, command):
        """Get user confirmation for potentially dangerous commands"""
        print(f"\033[93m⚠️  WARNING: This command appears potentially dangerous!\033[0m")
        print(f"\033[37mCommand: {command}\033[0m")
        response = input("\033[96mAre you sure you want to run this? (y/N): \033[0m").lower()
        return response == 'y'
    
    def get_filtered_commands(self):
        """Get commands filtered by current filter text using fuzzy matching"""
        if not self.ui.filter_text:
            return list(self.command_manager.commands.items())
        
        filtered = []
        for alias, cmd_data in self.command_manager.commands.items():
            command = cmd_data.get('command', '')
            description = cmd_data.get('description', '')
            tags = ' '.join(cmd_data.get('tags', []))
            
            if (self.ui.fuzzy_match(alias, self.ui.filter_text) or 
                self.ui.fuzzy_match(command, self.ui.filter_text) or
                self.ui.fuzzy_match(description, self.ui.filter_text) or
                self.ui.fuzzy_match(tags, self.ui.filter_text)):
                filtered.append((alias, cmd_data))
        return filtered
    
    def get_command_suggestions(self, partial):
        """Get command suggestions for tab completion"""
        matches = [alias for alias in self.command_manager.commands if alias.startswith(partial)]
        return matches
    
    def show_command_preview(self, alias):
        """Show preview of selected command"""
        if alias in self.command_manager.commands:
            cmd_data = self.command_manager.commands[alias]
            command = cmd_data.get('command', '')
            description = cmd_data.get('description', '')
            tags = cmd_data.get('tags', [])
            usage_count = self.command_manager.stats["usage_count"].get(alias, 0)
            
            preview_parts = []
            if description:
                preview_parts.append(f"📝 {description}")
            if tags:
                preview_parts.append(f"🏷️  {', '.join(tags)}")
            if usage_count > 0:
                preview_parts.append(f"📊 Used {usage_count} times")
            
            if preview_parts:
                print(f"\033[90m   └─ {' • '.join(preview_parts)}\033[0m")
            
            # Show command preview with safe truncation
            display_command = self.ui.safe_truncate(command, 80)
            print(f"\033[90m   └─ Command: {display_command}\033[0m")
    
    def show_stats(self):
        """Show command usage statistics"""
        if not self.command_manager.commands:
            return ""
        
        chains = sum(1 for cmd in self.command_manager.commands.values() if cmd.get('type') == 'chain')
        links = len(self.command_manager.commands) - chains
        total_usage = sum(self.command_manager.stats["usage_count"].values())
        
        stats_text = f"📊 {len(self.command_manager.commands)} commands ({links} links, {chains} chains)"
        if total_usage > 0:
            stats_text += f" • {total_usage} total uses"
        
        return stats_text
    
    def show_main_screen(self):
        """Display the main interface"""
        if not self.ui.first_run:
            self.ui.clear_screen()
        self.ui.first_run = False
        
        # Header with blue theme
        print("\033[96m" + "=" * 60)
        print("🚀 QL - Quick Launcher")
        print("=" * 60 + "\033[0m")
        print()
        
        # Get commands to display (filtered or all)
        display_commands = self.get_filtered_commands()
        
        if not self.command_manager.commands:
            print("\033[94m📝 No commands saved yet!\033[0m")
            print("\033[37mGet started by adding your first command:\033[0m")
            print("\033[36m   add <alias> <command>\033[0m")
            print("\033[36m   chain <alias> <cmd1> && <cmd2> && <cmd3>\033[0m")
            print()
            print("\033[37mExample:\033[0m")
            print("\033[36m   add backup tar -czf backup.tar.gz ~/documents\033[0m")
            print("\033[36m   chain setup git pull && npm install && npm run build\033[0m")
            print()
            if self.template_manager.templates:
                print("\033[94m🎯 Available templates:\033[0m")
                for name, template in self.template_manager.templates.items():
                    print(f"\033[36m   {name:<12}\033[0m \033[37m- {template['description']}\033[0m")
        else:
            # Show filter status and stats
            stats_text = self.show_stats()
            if self.ui.filter_mode:
                print(f"\033[94m🔍 Filter: \"{self.ui.filter_text}\" ({len(display_commands)}/{len(self.command_manager.commands)} commands)\033[0m")
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
                    usage_count = self.command_manager.stats["usage_count"].get(alias, 0)
                    
                    # Choose emoji based on type
                    emoji = "⛓️" if cmd_type == 'chain' else "🔗"
                    
                    # Truncate long commands for display with safe handling
                    display_command = self.ui.safe_truncate(command, 40)
                    
                    # Show number for quick selection (1-9), or position for 10+
                    if i < 9:
                        num_display = f"{i+1}"
                    else:
                        num_display = f"{i+1:2d}" if i < 99 else "##"
                    
                    # Add usage indicator
                    usage_indicator = f" ({usage_count})" if usage_count > 0 else ""
                    
                    # Highlight selected command
                    if i == self.ui.selected_index:
                        print(f"\033[1;97;44m {num_display}. {emoji} {alias:<{max_alias_len}}{usage_indicator} → {display_command}\033[0m")
                        if self.ui.show_preview:
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
        print("\033[36m   template <name> [<command>]\033[0m    \033[37m- Manage templates\033[0m")
        print("\033[36m   export <file-path>\033[0m              \033[37m- Export commands to file\033[0m")
        print("\033[36m   import <file-path>\033[0m              \033[37m- Import commands from file\033[0m")
        print("\033[36m   help\033[0m                       \033[37m- Show detailed help\033[0m")
        print("\033[36m   quit\033[0m or \033[36mq\033[0m                  \033[37m- Exit ql\033[0m")
        print()
        
        if self.command_manager.commands:
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
            print("\033[36m   Ctrl+T\033[0m                    \033[37m- Switch to template mode\033[0m")
            print()
        
        print(f"\033[90m📁 Commands stored in: {self.command_manager.config_file}\033[0m")
        
        # Input prompt
        if self.ui.filter_mode:
            print(f"\033[95m🔍 Filter: {self.ui.filter_text}\033[7m \033[0m")
        elif self.ui.input_mode:
            print(f"\033[96m> {self.ui.input_buffer}\033[7m \033[0m")
        else:
            print("\033[96m> \033[0m", end="", flush=True)
    
    def move_command_to_front(self, alias):
        """Move recently used command to front of the list"""
        if alias in self.command_manager.commands:
            cmd_data = self.command_manager.commands.pop(alias)
            new_commands = OrderedDict()
            new_commands[alias] = cmd_data
            new_commands.update(self.command_manager.commands)
            self.command_manager.commands = new_commands
    
    def show_help(self):
        """Show detailed help"""
        self.ui.clear_screen()
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
        print("\033[36m   template backup tar -czf backup-{date}.tar.gz {directory}\033[0m")
        print("\033[37m   └─ Creates a template with placeholders for dynamic values\033[0m")
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
        
        print("\033[94m🎨 Template Management:\033[0m")
        print("\033[37m   • template <name> - Run saved template with dynamic placeholders\033[0m")
        print("\033[37m   • template <name> <command> - Save new template with {placeholder} syntax\033[0m")
        print("\033[37m   • template edit <name> - Modify existing templates\033[0m")
        print("\033[37m   • Templates prompt for {placeholder} values each time they run\033[0m")
        print()
        
        print("\033[94m🎨 Available Templates:\033[0m")
        if self.template_manager.templates:
            for name, template in self.template_manager.templates.items():
                placeholders = template.get('placeholders', [])
                placeholder_text = ""
                if placeholders:
                    placeholder_text = f" ({', '.join(placeholders)})"
                print(f"\033[36m   {name:<15}\033[0m \033[37m{template['description']}\033[90m{placeholder_text}\033[0m")
        else:
            print("\033[90m   No templates saved yet\033[0m")
        print()
        
        print("\033[94m⚠️  Safety Features:\033[0m")
        print("\033[37m   • Potentially dangerous commands require confirmation\033[0m")
        print("\033[37m   • Common command typos are detected and corrected\033[0m")
        print("\033[37m   • Commands are validated before saving\033[0m")
        print()
        
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
            self.show_template_list()
            input("\033[90mPress Enter to continue...\033[0m")
        elif command == 'add':
            if len(parts) < 3:
                print("\033[91m❌ Usage: add <alias> <command>\033[0m")
                input("\033[90mPress Enter to continue...\033[0m")
            else:
                alias = parts[1]
                cmd = ' '.join(parts[2:])
                success = self.command_manager.add_command(alias, cmd, 'link')
                if success:
                    # Reset selection to new command
                    display_commands = self.get_filtered_commands()
                    for i, (cmd_alias, _) in enumerate(display_commands):
                        if cmd_alias == alias:
                            self.ui.selected_index = i
                            break
                input("\033[90mPress Enter to continue...\033[0m")
        elif command == 'chain':
            if len(parts) < 3:
                print("\033[91m❌ Usage: chain <alias> <cmd1> && <cmd2> && <cmd3>\033[0m")
                input("\033[90mPress Enter to continue...\033[0m")
            else:
                alias = parts[1]
                cmd = ' '.join(parts[2:])
                success = self.command_manager.add_command(alias, cmd, 'chain')
                if success:
                    # Reset selection to new command
                    display_commands = self.get_filtered_commands()
                    for i, (cmd_alias, _) in enumerate(display_commands):
                        if cmd_alias == alias:
                            self.ui.selected_index = i
                            break
                input("\033[90mPress Enter to continue...\033[0m")
        elif command == 'edit':
            if len(parts) < 2:
                print("\033[91m❌ Usage: edit <alias>\033[0m")
                input("\033[90mPress Enter to continue...\033[0m")
            else:
                self.command_manager.edit_command(parts[1])
                input("\033[90mPress Enter to continue...\033[0m")
        elif command == 'remove':
            if len(parts) < 2:
                print("\033[91m❌ Usage: remove <alias>\033[0m")
                input("\033[90mPress Enter to continue...\033[0m")
            else:
                success = self.command_manager.remove_command(parts[1])
                if success:
                    # Adjust selection if needed
                    display_commands = self.get_filtered_commands()
                    if self.ui.selected_index >= len(display_commands):
                        self.ui.selected_index = max(0, len(display_commands) - 1)
                input("\033[90mPress Enter to continue...\033[0m")
        elif command == 'template':
            if len(parts) == 1:
                # template - show available templates
                self.show_template_list()
                input("\033[90mPress Enter to continue...\033[0m")
            elif len(parts) == 2:
                # template backup - run existing template
                self.run_template(parts[1])
                input("\033[90mPress Enter to continue...\033[0m")
            elif len(parts) >= 3:
                if parts[1] == 'edit':
                    # template edit backup
                    if len(parts) == 3:
                        self.template_manager.edit_template(parts[2])
                    else:
                        print("\033[91m❌ Usage: template edit <name>\033[0m")
                    input("\033[90mPress Enter to continue...\033[0m")
                elif parts[1] == 'remove':
                    # template remove backup
                    if len(parts) == 3:
                        self.template_manager.remove_template(parts[2])
                    else:
                        print("\033[91m❌ Usage: template remove <name>\033[0m")
                    input("\033[90mPress Enter to continue...\033[0m")
                else:
                    # template backup tar -czf backup-{date}.tar.gz
                    template_name = parts[1]
                    template_command = ' '.join(parts[2:])
                    self.template_manager.save_template(template_name, template_command)
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
        elif command == 'cleanup':
            cleaned = self.force_cleanup_all_scripts()
            if cleaned > 0:
                print(f"\033[92m✅ Cleaned up {cleaned} temporary script(s)\033[0m")
            else:
                print("\033[90m✨ No temporary scripts to clean\033[0m")
            input("\033[90mPress Enter to continue...\033[0m")
        else:
            # Try to run as a command alias
            if command in self.command_manager.commands:
                return self.run_command_and_exit(command)
            else:
                print(f"\033[91m❌ Unknown command: {command}\033[0m")
                print("\033[37mType 'help' for available commands or 'quit' to exit.\033[0m")
                input("\033[90mPress Enter to continue...\033[0m")
        
        return True
    
    def force_cleanup_all_scripts(self):
        """Force cleanup of all QL temp scripts (for troubleshooting)"""
        script_dir = self.config_dir / 'tmp'
        
        if not script_dir.exists():
            return 0
            
        cleaned = 0
        try:
            pattern = str(script_dir / '*_ql.sh')
            for script_path in glob.glob(pattern):
                try:
                    if os.path.exists(script_path):
                        with open(script_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            if '# QL Command Executor' in content:
                                os.unlink(script_path)
                                cleaned += 1
                except (OSError, IOError):
                    pass
        except (OSError, IOError):
            pass
        
        return cleaned
    
    def _check_sudo_cd_issues(self, command):
        """Check for and warn about sudo cd issues"""
        if not command.strip().startswith('sudo cd '):
            return False
        
        title = f"\033[93m⚠️  WARNING: 'sudo cd' command detected!\033[0m"
        lines = [
            f"\033[37mCommand: {command}\033[0m",
            "",
            "\033[96m💡 'sudo cd' doesn't work as expected in command chains.\033[0m",
            "\033[37mThe directory change won't persist for subsequent commands.\033[0m"
        ]
        
        # Show suggestions
        suggestion_lines = self._get_sudo_cd_alternatives(command)
        lines.extend([""] + suggestion_lines)
        
        self.ui.show_message_and_pause(title, lines, "")
        
        response = input("\033[96mWould you like to run the command anyway? (y/N): \033[0m").lower()
        if response != 'y':
            self.ui.show_message_and_pause(
                None, 
                ["\033[37mCommand cancelled. Consider updating your command with one of the suggestions above.\033[0m"],
                "Press Enter to continue..."
            )
            return True
        return False
    
    def _get_sudo_cd_alternatives(self, command):
        """Get alternative suggestions for sudo cd commands"""
        lines = ["\033[94mSuggested alternatives:\033[0m"]
        
        # Extract the directory and remaining commands
        parts = command.split('&&', 1)
        if len(parts) == 2:
            cd_part = parts[0].strip()
            rest_part = parts[1].strip()
            directory = cd_part.replace('sudo cd', 'cd').strip()
            
            lines.extend([
                f"\033[36m1. {directory} && {rest_part}\033[0m",
                f"\033[90m   (Change directory first, then run command normally)\033[0m",
                "",
                f"\033[36m2. {directory} && sudo {rest_part}\033[0m",
                f"\033[90m   (Change directory first, then run command with sudo)\033[0m",
                "",
                f"\033[36m3. sudo bash -c \"{cd_part.replace('sudo ', '')} && {rest_part}\"\033[0m",
                f"\033[90m   (Run entire chain in sudo subshell)\033[0m"
            ])
        
        return lines
    
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
# Auto-cleanup: this script will self-destruct
trap 'rm -f "$0" 2>/dev/null || true' EXIT INT TERM

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

# Force cleanup before exec
rm -f "$0" 2>/dev/null || true

exec {shell}
"""
        else:
            return f"""#!/bin/bash
# QL Command Executor
# Auto-cleanup: this script will self-destruct
trap 'rm -f "$0" 2>/dev/null || true' EXIT INT TERM

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

# Force cleanup before exec
rm -f "$0" 2>/dev/null || true

exec {shell}
"""
    
    def run_command_and_exit(self, alias):
        """Run command by feeding it directly to the terminal - simplified version"""
        if alias not in self.command_manager.commands:
            return True
        
        # Clean up any old scripts first
        self.cleanup_old_scripts()
        
        # Update usage statistics
        self.command_manager.update_usage_stats(alias)
        
        # Move to front for recent usage
        self.move_command_to_front(alias)
        self.command_manager.save_commands()
        
        cmd_data = self.command_manager.commands[alias]
        command = cmd_data.get('command', '')
        cmd_type = cmd_data.get('type', 'link')
        
        # Safety checks
        if self.command_manager.is_dangerous_command(command):
            title = f"\033[93m⚠️  WARNING: This command appears potentially dangerous!\033[0m"
            lines = [f"\033[37mCommand: {command}\033[0m"]
            self.ui.show_message_and_pause(title, lines, "")
            
            response = input("\033[96mAre you sure you want to run this? (y/N): \033[0m").lower()
            if response != 'y':
                self.ui.show_message_and_pause(
                    None,
                    ["\033[37mCommand cancelled.\033[0m"],
                    "Press Enter to continue..."
                )
                return True
        
        # Check for sudo cd issues
        if self._check_sudo_cd_issues(command):
            return True
        
        # Create and execute script
        script_path = self._create_execution_script(alias, command, cmd_type)
        if not script_path:
            return True
        
        # Clear screen and launch
        self.ui.clear_screen()
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
        if alias not in self.command_manager.commands:
            return
        
        cmd_data = self.command_manager.commands[alias]
        command = cmd_data.get('command', '')
        cmd_type = cmd_data.get('type', 'link')
        description = cmd_data.get('description', '')
        tags = cmd_data.get('tags', [])
        emoji = "⛓️" if cmd_type == 'chain' else "🔗"
        
        self.ui.clear_screen()
        print()  # Top padding
        
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
        
        if self.command_manager.is_dangerous_command(command):
            print("\033[93m⚠️  WARNING: This command appears potentially dangerous!\033[0m")
        
        print()
        input("\033[90mPress Enter to continue...\033[0m")
    
    def copy_to_clipboard(self, alias):
        """Copy command to clipboard"""
        if not CLIPBOARD_AVAILABLE:
            self.ui.clear_screen()
            print()
            print("\033[91m❌ Clipboard support not available (install pyperclip)\033[0m")
            print()
            input("\033[90mPress Enter to continue...\033[0m")
            return
        
        if alias not in self.command_manager.commands:
            return
        
        cmd_data = self.command_manager.commands[alias]
        command = cmd_data.get('command', '')
        
        self.ui.clear_screen()
        print()  # Top padding
        
        try:
            pyperclip.copy(command)
            print(f"\033[92m📋 Copied '{alias}' to clipboard!\033[0m")
            print(f"\033[90mCommand: {command}\033[0m")
        except Exception as e:
            print(f"\033[91m❌ Error copying to clipboard: {e}\033[0m")
        
        print()
        input("\033[90mPress Enter to continue...\033[0m")
    
    def interactive_mode(self):
        """Main interactive loop with mode switching"""
        while True:
            if self.current_mode == 'command':
                if not self.command_interactive_mode():
                    break
            elif self.current_mode == 'template':
                if not self.template_interactive_mode_loop():
                    break
    
    def command_interactive_mode(self):
        """Interactive mode for commands"""
        while True:
            self.show_main_screen()
            
            try:
                key = self.ui.get_key()
                display_commands = self.get_filtered_commands()
                
                if key == '\r' or key == '\n':  # Enter key
                    if self.ui.filter_mode:
                        # Exit filter mode
                        self.ui.filter_mode = False
                        self.ui.selected_index = 0
                    elif self.ui.input_mode and self.ui.input_buffer.strip():
                        if not self.parse_input(self.ui.input_buffer):
                            return False
                        self.ui.input_buffer = ""
                        self.ui.input_mode = False
                    elif display_commands and not self.ui.input_mode:
                        # Run selected command
                        if 0 <= self.ui.selected_index < len(display_commands):
                            selected_alias = display_commands[self.ui.selected_index][0]
                            if not self.run_command_and_exit(selected_alias):
                                return False
                
                elif key == '\t' and self.ui.input_mode:  # Tab completion
                    suggestions = self.get_command_suggestions(self.ui.input_buffer)
                    if len(suggestions) == 1:
                        self.ui.input_buffer = suggestions[0] + ' '
                    elif len(suggestions) > 1:
                        # Show suggestions
                        print(f"\n\033[90mSuggestions: {', '.join(suggestions[:5])}\033[0m")
                        if len(suggestions) > 5:
                            print(f"\033[90m... and {len(suggestions) - 5} more\033[0m")
                        input("\033[90mPress Enter to continue...\033[0m")
                
                elif key.isdigit() and not self.ui.input_mode and not self.ui.filter_mode:
                    # Quick select with number keys (1-9)
                    num = int(key) - 1
                    if 0 <= num < len(display_commands) and num < 9:
                        selected_alias = display_commands[num][0]
                        if not self.run_command_and_exit(selected_alias):
                            return False
                
                elif key == 'p' and not self.ui.input_mode and not self.ui.filter_mode:
                    # Toggle preview
                    self.ui.show_preview = not self.ui.show_preview
                
                elif key == 'UP' and display_commands and not self.ui.input_mode and not self.ui.filter_mode:
                    self.ui.selected_index = max(0, self.ui.selected_index - 1)
                
                elif key == 'DOWN' and display_commands and not self.ui.input_mode and not self.ui.filter_mode:
                    self.ui.selected_index = min(len(display_commands) - 1, self.ui.selected_index + 1)
                
                elif key == '\x04' and display_commands and not self.ui.input_mode and not self.ui.filter_mode:
                    # Ctrl+D - Dry run selected command
                    if 0 <= self.ui.selected_index < len(display_commands):
                        selected_alias = display_commands[self.ui.selected_index][0]
                        self.dry_run_command(selected_alias)
                
                elif key == '\x19' and display_commands and not self.ui.input_mode and not self.ui.filter_mode:
                    # Ctrl+Y - Copy selected command
                    if 0 <= self.ui.selected_index < len(display_commands):
                        selected_alias = display_commands[self.ui.selected_index][0]
                        self.copy_to_clipboard(selected_alias)
                
                elif key == '/' and not self.ui.input_mode:
                    # Enter filter mode
                    self.ui.filter_mode = True
                    self.ui.filter_text = ""
                    self.ui.selected_index = 0
                
                elif key == '\x7f' or key == '\x08':  # Backspace
                    if self.ui.filter_mode:
                        if self.ui.filter_text:
                            self.ui.filter_text = self.ui.filter_text[:-1]
                            self.ui.selected_index = 0
                        else:
                            self.ui.filter_mode = False
                    elif self.ui.input_mode and self.ui.input_buffer:
                        self.ui.input_buffer = self.ui.input_buffer[:-1]
                        if not self.ui.input_buffer:
                            self.ui.input_mode = False
                
                elif key == '\x1b':  # Escape key
                    if self.ui.filter_mode:
                        self.ui.filter_mode = False
                        self.ui.filter_text = ""
                        self.ui.selected_index = 0
                    elif self.ui.input_mode:
                        self.ui.input_mode = False
                        self.ui.input_buffer = ""
                
                elif key == '\x03':  # Ctrl+C
                    return False
                
                elif key == '\x14':  # Ctrl+T - Switch to template mode
                    self.current_mode = 'template'
                    self.reset_ui_state()
                    return True
                
                elif key.isprintable():
                    if self.ui.filter_mode:
                        self.ui.filter_text += key
                        self.ui.selected_index = 0
                    else:
                        if not self.ui.input_mode:
                            self.ui.input_mode = True
                            self.ui.input_buffer = ""
                        self.ui.input_buffer += key
                    
            except KeyboardInterrupt:
                return False
            except Exception:
                continue
    
    def export_commands(self, filename):
        """Export commands to a file"""
        try:
            export_data = {
                'commands': dict(self.command_manager.commands),
                'exported_at': datetime.now().isoformat(),
                'version': '1.0.0'
            }
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            print(f"\033[92m✅ Exported {len(self.command_manager.commands)} commands to {filename}\033[0m")
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
                if alias in self.command_manager.commands:
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
                
                self.command_manager.commands[alias] = cmd_data
                imported_count += 1
            
            self.command_manager.save_commands()
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
        if args.command in launcher.command_manager.commands:
            launcher.run_command_and_exit(args.command)
        else:
            print(f"\033[91m❌ Command '{args.command}' not found!\033[0m")
            available = list(launcher.command_manager.commands.keys())
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