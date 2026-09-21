import { ActionMetadata, ActionFamily } from "./types"

/**
 * Intelligent Action & Intent Parser
 * Replaces rigid uppercase tool names with modern, developer-first action verbs and target highlights.
 */

interface RawToolInput {
  toolName?: string
  description?: string
  detail?: string
  url?: string
}

const ACTION_FAMILY_MAP: Record<string, ActionFamily> = {
  // File & I/O
  read_file: "io",
  edit_file: "io",
  write_file: "io",
  multi_replace_file_content: "io",
  replace_file_content: "io",
  view_file: "io",
  list_dir: "io",
  
  // Execution & System
  run_command: "exec",
  exec: "exec",
  terminal: "exec",
  pytest: "exec",
  cargo_test: "exec",
  
  // Network & Web
  search: "network",
  web_search: "network",
  google_search: "network",
  crawler_query: "network",
  fetch_url: "network",
  read_url_content: "network",
  
  // Reasoning & Memory
  mcm_recall: "reasoning",
  mcm_compress: "reasoning",
  pin_search: "reasoning",
  navigate: "reasoning",
  reasoning: "reasoning",
  planning: "reasoning",
}

const VERB_MAP: Record<string, string> = {
  read_file: "read",
  view_file: "read",
  edit_file: "edit",
  write_file: "write",
  replace_file_content: "patch",
  multi_replace_file_content: "patch",
  list_dir: "list",
  run_command: "exec",
  search: "search",
  web_search: "search",
  google_search: "search",
  crawler_query: "crawl",
  read_url_content: "fetch",
  mcm_recall: "recall",
  mcm_compress: "compress",
  pin_search: "query-pin",
  navigate: "graph-nav",
  ask_user_question: "prompt-user",
  speak: "voice",
}

/**
 * Extracts a concise target from a description or raw command
 */
function extractTarget(toolName: string, desc: string, detail?: string, url?: string): string | undefined {
  if (url) {
    try {
      const u = new URL(url)
      return u.hostname + (u.pathname.length > 1 ? u.pathname.slice(0, 24) : "")
    } catch {
      return url.slice(0, 32)
    }
  }
  
  if (detail) return detail

  // Match file paths
  const fileMatch = desc.match(/(?:(?:[\w-]+\/)+[\w.-]+|\b[\w-]+\.(?:ts|tsx|js|jsx|py|rs|json|md|css|html|toml)\b)/i)
  if (fileMatch) return fileMatch[0]

  // Match quoted queries or commands
  const quoteMatch = desc.match(/["'`]([^"'`]+)["'`]/)
  if (quoteMatch) return quoteMatch[1]

  // Match commands
  if (toolName === "run_command" || desc.startsWith("Running ") || desc.startsWith("Run ")) {
    const cmdClean = desc.replace(/^(?:Running|Run)\s+(?:command\s+)?/i, "").trim()
    return cmdClean.length > 35 ? cmdClean.slice(0, 35) + "…" : cmdClean
  }

  return undefined
}

/**
 * Parses raw tool inputs into structured, clean ActionMetadata
 */
export function parseAction(input: RawToolInput): ActionMetadata {
  const rawTool = (input.toolName || "").trim().toLowerCase()
  const desc = (input.description || "").trim()
  
  const family = ACTION_FAMILY_MAP[rawTool] || inferFamilyFromDescription(desc)
  const verb = VERB_MAP[rawTool] || inferVerbFromDescription(desc, rawTool)
  const target = extractTarget(rawTool, desc, input.detail, input.url)

  return {
    verb,
    target,
    family,
    rawToolName: input.toolName,
  }
}

function inferFamilyFromDescription(desc: string): ActionFamily {
  const d = desc.toLowerCase()
  if (/(search|browse|crawl|url|http|web)/.test(d)) return "network"
  if (/(file|read|write|edit|dir|path|directory)/.test(d)) return "io"
  if (/(exec|command|run|terminal|test|build)/.test(d)) return "exec"
  if (/(analy|reason|think|eval|plan|synthe)/.test(d)) return "reasoning"
  return "system"
}

function inferVerbFromDescription(desc: string, rawTool: string): string {
  const d = desc.toLowerCase()
  if (/(search|find|query)/.test(d)) return "search"
  if (/(crawl|scrape|extract)/.test(d)) return "crawl"
  if (/(read|view|inspect)/.test(d)) return "read"
  if (/(edit|modify|patch|update)/.test(d)) return "edit"
  if (/(write|create|generate)/.test(d)) return "create"
  if (/(exec|run|test|build)/.test(d)) return "exec"
  if (/(plan|synthe|analy)/.test(d)) return "reason"
  
  if (rawTool) {
    return rawTool.replace(/_/g, " ").replace(/^(\w)/, (c) => c.toLowerCase())
  }
  return "action"
}

/**
 * Generates a clean single-line human summary for a step
 */
export function formatStepLine(action: ActionMetadata, fallbackIntent: string): string {
  if (action.verb && action.target) {
    return `${action.verb} ${action.target}`
  }
  return fallbackIntent || action.verb || "Processing step"
}
