# ql.py — original v0.1

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

