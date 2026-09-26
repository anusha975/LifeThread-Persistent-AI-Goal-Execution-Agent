# LifeThread Agent Skills & Customization System

## 1. Overview

Agent Skills are modular, on-demand capability bundles and specialized procedural guidelines that extend the cognitive and tool-use capabilities of LifeThread agents. Skills allow the agent to follow established workflows, project-specific conventions, and domain recipes without bloating the base system prompt.

---

## 2. Customization Roots & Discovery

Skills and customizations are loaded hierarchically from two customization roots:

1. **Workspace Customizations Root:** `.agents/` (relative to the active project root).
2. **Global Customizations Root:** `<appDataDir>/config/` (or user configuration directory).

### Directory Structure
```text
.agents/
├── skills/
│   └── <skill_name>/
│       ├── SKILL.md            # Required: Instructions with YAML frontmatter
│       ├── scripts/            # Optional helper scripts and CLI utilities
│       ├── examples/           # Optional reference examples
│       └── resources/          # Optional templates and assets
├── rules/                      # Markdown guidelines (or GEMINI.md / AGENTS.md)
└── plugins/                    # Namespaced bundles of skills and MCP configs
```

---

## 3. The `SKILL.md` Format

Every skill directory must contain a `SKILL.md` file featuring a YAML frontmatter header followed by detailed markdown instructions:

```markdown
---
name: database-migration-runner
description: Step-by-step procedures for running zero-downtime database migrations with automated lag monitoring.
---

# Database Migration Runner

## Workflow Overview
1. Check baseline replication lag via `mcp__database_diagnostic`.
2. Validate foreign key constraints on target tables.
3. Initiate chunked data transfer with backpressure monitoring.
...
```

### Frontmatter Fields
- **`name`:** Unique identifier for the skill (alphanumeric and dashes).
- **`description`:** Concise summary explaining when and why the agent should activate this skill.

---

## 4. Builtin Agent Skills

LifeThread includes standard builtin skills available out of the box:

### 4.1 `agy-customizations`
- **Location:** `builtin/skills/agy-customizations/SKILL.md`
- **Purpose:** Comprehensive guide for the customization system, explaining loading priorities, discovery rules, and formatting standards for skills, rules, and plugins.

### 4.2 `antigravity-guide`
- **Location:** `builtin/skills/antigravity_guide/SKILL.md`
- **Purpose:** Full reference manual for the Antigravity CLI, IDE tooling, slash commands (`/goal`, `/plan`, `/schedule`), and runtime environment.

---

## 5. Skill Execution Lifecycle

1. **Discovery:** At initialization, the agent indexes all available skills from the customization roots.
2. **Evaluation:** When a task or user request matches a skill's description, the agent reads the skill's `SKILL.md` instructions using `view_file`.
3. **Execution:** The agent strictly executes the recommended procedures, utilizing any bundled scripts or reference examples.
4. **Safety & Fallback:** If a script or step fails, the agent applies the error handling procedures defined within the skill before escalating.
