---
name: skill-creator
description: Guide for creating effective IRIS skills. This skill should be used when the user wants to create a new skill (or update an existing skill) that extends IRIS's capabilities with specialised knowledge, workflows, or tool integrations. IRIS uses this skill as its steering wheel for customising the user's experience.
---

# Skill Creator

This skill guides IRIS in creating effective skills that extend capabilities for the user's specific needs.

## About IRIS Skills

Skills are modular, self-contained packages that extend IRIS's capabilities by providing
specialised knowledge, workflows, and tools. Think of them as "onboarding guides" for specific
domains or tasks — they transform IRIS from a general-purpose assistant into a specialised agent
equipped with procedural knowledge tailored to the user.

**Skills directory:** `IRISVOICE/backend/agent/skills/` (relative to the project root)

Skills are loaded automatically at startup by `skills_loader.py`. After creating a new skill, the
`PersonalityManager` cache must be invalidated (call `update_profile()` or restart the backend)
for the new skill to appear in the system prompt.

### What Skills Provide

1. **Specialised workflows** — Multi-step procedures for specific domains
2. **Tool integrations** — Instructions for working with MCP tools or APIs
3. **Domain expertise** — User-specific knowledge, preferences, business logic
4. **Bundled resources** — Scripts, references, and assets for complex or repetitive tasks

### Anatomy of a Skill

Every skill consists of a required SKILL.md file and optional bundled resources:

```
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter (required): name, description
│   └── Markdown instructions (required)
└── Bundled Resources (optional)
    ├── scripts/       — Executable code (Python/Bash)
    ├── references/    — Documentation loaded into context as needed
    └── assets/        — Files used in output (templates, icons, etc.)
```

#### SKILL.md (required)

The `name` and `description` in YAML frontmatter determine when IRIS activates the skill.
Be specific — the description is shown in the system prompt, so it should clearly explain
what the skill does and when to use it. Use third-person phrasing, e.g.:
> "This skill should be used when the user asks to..."

#### Bundled Resources (optional)

- **`scripts/`** — Executable code for tasks that require deterministic reliability
- **`references/`** — Documentation IRIS loads into context when working
- **`assets/`** — Files used in output that IRIS produces

---

## Skill Creation Process

Follow these steps in order, skipping only when clearly not applicable.

### Step 1: Understand the Skill with Concrete Examples

Before writing anything, get concrete examples of how the skill will be used:

- "What should this skill help you do?"
- "Can you give examples of what you'd ask IRIS?"
- "What would you say to trigger this skill?"

Conclude when there is a clear picture of the functionality to support.

### Step 2: Plan the Skill Contents

For each example, identify what reusable resources would help:
- Would the same code be written repeatedly? → `scripts/`
- Is there domain knowledge IRIS should reference? → `references/`
- Are there template files needed in output? → `assets/`

### Step 3: Create the Skill Using the Built-in Tool

**ALWAYS use the `create_skill` tool** — never use `write_file` or describe the content without creating it.

Call `create_skill` with:
- `name`: kebab-case skill name (e.g. `the-motivator`)
- `content`: the full SKILL.md text including YAML frontmatter

The tool creates the directory and SKILL.md file atomically and notifies the UI immediately.

### Step 4: Write Good SKILL.md Content

Write using **imperative/infinitive form** (verb-first instructions):
- ✅ "To accomplish X, do Y"
- ❌ "You should do X"

Include in the `content` string passed to `create_skill`:
1. YAML frontmatter with `name` and `description`
2. What the skill does (2–3 sentences)
3. When to use it
4. How to use it step-by-step

Keep SKILL.md lean. Do not include code blocks with file system paths — the tool handles placement.

### Step 5: Confirm to the User

After calling `create_skill` successfully:
1. Tell the user: "Skill created! You can see it in the Skills panel of the Dashboard."
2. The skill is immediately active and will appear in the learned skills UI.
3. It will be loaded into the system prompt on the next backend restart.

### Step 6: Iterate

After testing, identify improvements:
- What did IRIS struggle with?
- What information was missing from the SKILL.md?
- What references or scripts would help?

Update SKILL.md and test again.

---

## Example: Creating a Skill for the User

**User says:** "Create a skill so you can help me manage my notes"

1. Ask: "Where do you store notes? What format? What operations — create, search, summarise?"
2. Plan the SKILL.md content based on the answers
3. Call `create_skill(name="notes-manager", content="---\nname: notes-manager\n...")` — the tool does everything
4. Tell user: "Done! The Notes Manager skill is live in your Skills panel."

**Never** describe the SKILL.md content as text and stop there. Always call the `create_skill` tool to actually create it.
