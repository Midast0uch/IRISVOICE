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

**Skills directory:** `backend/agent/skills/`

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

### Step 3: Create the Skill Directory

Create the skill directory inside `backend/agent/skills/`:

```
backend/agent/skills/<skill-name>/
└── SKILL.md
```

### Step 4: Write SKILL.md

Write using **imperative/infinitive form** (verb-first instructions):
- ✅ "To accomplish X, do Y"
- ❌ "You should do X"

Include:
1. What the skill does (2–3 sentences)
2. When to use it
3. How to use it step-by-step, referencing bundled resources

Keep SKILL.md lean. Move detailed reference material to `references/` files.

### Step 5: Activate the Skill

After creating the skill:
1. Tell the user: "Skill created at `backend/agent/skills/<skill-name>/SKILL.md`"
2. The skill will be loaded next time the backend starts or the personality cache refreshes
3. Optionally update `backend/agent/skills/config.yaml` to document the new skill

### Step 6: Iterate

After testing, identify improvements:
- What did IRIS struggle with?
- What information was missing from the SKILL.md?
- What references or scripts would help?

Update SKILL.md and test again.

---

## Example: Creating a Skill for the User

**User says:** "Create a skill so you can help me manage my notes"

1. Ask: "Where do you store notes? What format? What operations do you want — create, search, summarise?"
2. Plan: references/ for note format spec, scripts/ for search script if needed
3. Create `backend/agent/skills/notes-manager/SKILL.md`
4. Write SKILL.md with the note-taking workflow
5. Tell user the skill is created and what triggers it
