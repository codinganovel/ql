# ql.py — original v0.1

## v0.3 – 2025-07-17
### ➕ Added
**Modular Architecture Refactor**
- Complete rewrite with class-based modular architecture
- New classes: `UIManager`, `CommandManager`, `TemplateManager`, `QLLauncher`
- Better separation of concerns and maintainability

**Dual-Mode Interface**
- New dual-mode navigation system (command mode + template mode)
- `Ctrl+T` hotkey to seamlessly switch between modes
- Mode-specific interfaces with tailored navigation
- Mode state persistence during navigation sessions

**Usage Statistics and Optimization**
- Usage tracking system (`~/.local/bin/.qlstats`)
- Command usage counters and last-used timestamps
- Statistics display showing command counts, types, and usage
- Command optimization based on usage patterns

**Enhanced UI and Navigation**
- Safe string truncation (`safe_truncate()`) to prevent crashes from long commands
- Improved screen clearing with better terminal compatibility
- Enhanced keyboard handling with cross-platform arrow key support
- Real-time preview system with toggle capability (`p` key)
- Inline preview mode showing command/template details below selections

**Advanced Search and Filtering**
- Combined fuzzy matching (substring + character-in-order matching)
- Multi-field search across commands, descriptions, tags, and templates
- Real-time filter feedback with match count display
- Enhanced filter mode with better visual indicators

**Extended Keyboard Shortcuts for templates as well**
- `d` - Dry run preview
- `c` - Copy to clipboard
- `p` - Toggle preview on/off
- `e` - Edit selected item
- `r` - Remove selected item
- `Ctrl+T` - Switch between modes
- Number keys (1-9) for quick selection

### 🔄 Changed
**Complete Architectural Overhaul**
- Transformed from monolithic structure to modular class-based design
- Enhanced template navigation with dedicated template mode
- Improved command management with in-place updates
- Better command validation and alias checking
- Enhanced template preview system with dry-run capabilities

**User Experience Improvements**
- Significantly improved cross-platform compatibility
- Better terminal handling across different platforms
- Enhanced keyboard input with proper escape sequence handling
- Improved error recovery for platform-specific issues

### 🐛 Fixed
- Fixed crashes from extremely long commands with safe string handling
- Improved error handling for edge cases
- Enhanced dangerous command detection patterns
- Better command validation and typo detection
- More robust terminal compatibility across platforms

## v0.2 – 2025-06-28 00:57
### ➕ Added
L55 Introduced self.templates_file, pointing to a per-user .qltemplates file for saved command templates. 

L62 Loaded those templates at start-up (self.templates = self.load_templates()). 

L95-120 New load_templates() helper: creates the template file on first run and seeds it with four default templates (git-setup, backup, deploy, docker-build) that include descriptions and placeholder metadata. 

L121-167 Robust read/validate/recreate logic for the template file, with warnings on I/O or JSON errors and automatic fallback to defaults when needed. 

L169-176 save_templates(): persists the in-memory template dictionary back to disk, with error reporting. 

L177-181 extract_placeholders(): parses {placeholder} patterns from a template command. 

L182-210 show_template_list(): pretty, colourised listing of all saved templates plus quick-reference help. 

L211-250 run_template(): prompts the user for placeholder values, substitutes them into the command, and executes it. 

L251-285 save_template(): interactively creates or overwrites a template (validates the name, gathers optional description, stores placeholders, calls save_templates()). 

L286-331 edit_template(): lets users modify command, description, or placeholders of an existing template. 

L332-350 remove_template(): deletes a template after confirmation. 

L352-371 run_direct_command(): executes an ad-hoc command without saving it, using the existing script-execution helper. 

L682-915 CLI dispatch & help text updated: adds template sub-commands (list, run, edit, remove, save) and integrates template management into the main command loop. 

### ➖ Removed
L45-67 Deleted the hard-coded COMMAND_TEMPLATES dictionary—template data is now stored in the user-editable file. 

L421-430, L484, L538-582, L584, L600-639, L1267-1303 Removed all functions, help text, and menu entries that depended on the static COMMAND_TEMPLATES, including the old create_from_template() workflow. These responsibilities are fully replaced by the new file-backed template-management system.

