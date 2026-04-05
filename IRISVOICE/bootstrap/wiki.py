"""
Mycelium Wiki CLI
File: IRISVOICE/bootstrap/wiki.py

Add, query, and search wiki knowledge nodes in the coordinate graph.
Wiki entries are full citizens of the graph — they link to file nodes,
landmarks, and other entries via wiki_links edges.

Usage (run from IRISVOICE/):
    python bootstrap/wiki.py --add    "Title" --content "markdown body" --tags tag1 tag2
    python bootstrap/wiki.py --add    "Image: Arch Diagram" --image-refs docs/arch.png
    python bootstrap/wiki.py --add    "Design: TTS Pipeline" --file-refs backend/agent/tts.py
    python bootstrap/wiki.py --search "tts"
    python bootstrap/wiki.py --list
    python bootstrap/wiki.py --list   --project my-project
    python bootstrap/wiki.py --link   wiki:ENTRY_ID landmark:lm_foo documents
    python bootstrap/wiki.py --link   wiki:ENTRY_ID file:backend/agent/tts.py implements
    python bootstrap/wiki.py --update ENTRY_ID --content "new body" --permanent
    python bootstrap/wiki.py --projects
    python bootstrap/wiki.py --ensure-project "my-project" --path /some/path
"""

import sys
import os
import argparse
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from bootstrap.coordinates import CoordinateStore


def cmd_add(store: CoordinateStore, args) -> None:
    entry_id = store.add_wiki_entry(
        title=args.add,
        content=args.content or "",
        tags=args.tags or [],
        file_refs=args.file_refs or [],
        image_refs=args.image_refs or [],
        project_id=args.project or None,
        is_permanent=args.permanent,
    )
    print(f"WIKI ENTRY CREATED: {entry_id}")
    print(f"  Title: {args.add}")
    if args.tags:
        print(f"  Tags:  {', '.join(args.tags)}")
    if args.file_refs:
        print(f"  Files: {', '.join(args.file_refs)}")
    if args.image_refs:
        print(f"  Images:{', '.join(args.image_refs)}")
    if args.permanent:
        print("  ★ PERMANENT — will survive federation merges and decay passes")


def cmd_update(store: CoordinateStore, args) -> None:
    perm = True if args.permanent else (False if args.no_permanent else None)
    store.update_wiki_entry(
        entry_id=args.update,
        content=args.content,
        tags=args.tags,
        file_refs=args.file_refs,
        image_refs=args.image_refs,
        is_permanent=perm,
    )
    print(f"WIKI ENTRY UPDATED: {args.update}")


def cmd_list(store: CoordinateStore, args) -> None:
    entries = store.get_wiki_entries(
        project_id=args.project or None,
        permanent_only=args.permanent,
        limit=args.limit,
    )
    if not entries:
        print("No wiki entries found.")
        return
    print(f"WIKI ENTRIES ({len(entries)}):")
    print()
    for e in entries:
        perm_flag = " ★" if e["is_permanent"] else ""
        proj = f" [{e['project_id'][:8]}]" if e.get("project_id") else ""
        tags_str = f"  tags: {', '.join(e['tags'])}" if e.get("tags") else ""
        print(f"  {e['entry_id']}{perm_flag}{proj}  {e['title']}")
        if tags_str:
            print(tags_str)
        if e.get("file_refs"):
            print(f"  files: {', '.join(e['file_refs'])}")
        if e.get("image_refs"):
            print(f"  images: {', '.join(e['image_refs'])}")
        preview = (e.get("content") or "").strip()[:80].replace("\n", " ")
        if preview:
            print(f"  {preview}...")
        print()


def cmd_search(store: CoordinateStore, args) -> None:
    results = store.search_wiki(args.search, limit=args.limit)
    if not results:
        print(f"No wiki entries matching '{args.search}'.")
        return
    print(f"WIKI SEARCH: '{args.search}' — {len(results)} result(s)")
    print()
    for e in results:
        perm_flag = " ★" if e["is_permanent"] else ""
        print(f"  {e['entry_id']}{perm_flag}  {e['title']}")
        preview = (e.get("content") or "").strip()[:100].replace("\n", " ")
        if preview:
            print(f"  {preview}...")
        print()


def cmd_link(store: CoordinateStore, args) -> None:
    """
    Link two nodes: "type:id type:id relationship"
    Examples:
      wiki:wiki_abc123 landmark:lm_foo documents
      wiki:wiki_abc123 file:backend/agent/tts.py implements
    """
    try:
        src_type, src_id = args.link[0].split(":", 1)
        tgt_type, tgt_id = args.link[1].split(":", 1)
        relationship = args.link[2] if len(args.link) > 2 else "references"
    except ValueError:
        print("ERROR: --link expects: source_type:source_id target_type:target_id [relationship]")
        sys.exit(1)

    link_id = store.add_wiki_link(
        source_type=src_type, source_id=src_id,
        target_type=tgt_type, target_id=tgt_id,
        relationship=relationship,
    )
    print(f"WIKI LINK CREATED: link_id={link_id}")
    print(f"  {src_type}:{src_id} --[{relationship}]--> {tgt_type}:{tgt_id}")


def cmd_projects(store: CoordinateStore) -> None:
    projects = store.get_projects()
    if not projects:
        print("No projects registered.")
        return
    print(f"REGISTERED PROJECTS ({len(projects)}):")
    for p in projects:
        tags = json.loads(p.get("tags") or "[]")
        tags_str = f"  tags: {', '.join(tags)}" if tags else ""
        print(f"  {p['project_id'][:8]}  {p['name']}  {p.get('path','')}")
        if tags_str:
            print(tags_str)
        if p.get("description"):
            print(f"  {p['description']}")
        print()


def cmd_ensure_project(store: CoordinateStore, args) -> None:
    project_id = store.ensure_project(
        name=args.ensure_project,
        path=args.path or "",
        description=args.description or "",
        tags=args.tags or [],
    )
    print(f"PROJECT: {args.ensure_project}  id={project_id}")


def main():
    parser = argparse.ArgumentParser(
        description="Mycelium Wiki — knowledge nodes in the coordinate graph"
    )

    # Entry operations
    parser.add_argument("--add", metavar="TITLE",
                        help="Create a new wiki entry with this title")
    parser.add_argument("--update", metavar="ENTRY_ID",
                        help="Update an existing wiki entry")
    parser.add_argument("--list", action="store_true",
                        help="List wiki entries")
    parser.add_argument("--search", metavar="QUERY",
                        help="Search wiki entries by title/content/tags")
    parser.add_argument("--link", nargs="+", metavar="TYPE:ID",
                        help="Link two nodes: src_type:id tgt_type:id [relationship]")

    # Project operations
    parser.add_argument("--projects", action="store_true",
                        help="List registered projects")
    parser.add_argument("--ensure-project", metavar="NAME",
                        help="Register a project by name (idempotent)")

    # Entry fields
    parser.add_argument("--content", metavar="MARKDOWN",
                        help="Markdown body for the wiki entry")
    parser.add_argument("--tags", nargs="+", metavar="TAG",
                        help="Tags for the entry")
    parser.add_argument("--file-refs", nargs="+", metavar="PATH",
                        help="File paths referenced by this entry")
    parser.add_argument("--image-refs", nargs="+", metavar="PATH",
                        help="Image paths/URLs referenced by this entry")
    parser.add_argument("--project", metavar="PROJECT_ID",
                        help="Project ID to associate with this entry/list")
    parser.add_argument("--permanent", action="store_true",
                        help="Mark as permanent (survives merges and decay)")
    parser.add_argument("--no-permanent", action="store_true",
                        help="Remove permanent flag from an entry")

    # Project fields
    parser.add_argument("--path", metavar="PATH",
                        help="Filesystem path for --ensure-project")
    parser.add_argument("--description", metavar="TEXT",
                        help="Description for --ensure-project")

    # Common
    parser.add_argument("--limit", type=int, default=50,
                        help="Max results to return (default: 50)")

    args = parser.parse_args()
    store = CoordinateStore()

    if args.add:
        cmd_add(store, args)
    elif args.update:
        cmd_update(store, args)
    elif args.list:
        cmd_list(store, args)
    elif args.search:
        cmd_search(store, args)
    elif args.link:
        cmd_link(store, args)
    elif args.projects:
        cmd_projects(store)
    elif args.ensure_project:
        cmd_ensure_project(store, args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
