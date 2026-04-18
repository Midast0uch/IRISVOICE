"""
PiN CLI — Primordial Information Nodes
File: IRISVOICE/bootstrap/pin.py

A PiN is any meaningful unit of knowledge anchored to this project's memory graph:
files, folders, documents, images, designs, decisions, URLs, code fragments.
"Primordial" connects to Mycelium — primordia are the first growth points of a
fungal network. PiNs are the attachment points IRIS memory crystallises around
as it moves across projects and instances.

Usage (run from IRISVOICE/):
    # Anchor knowledge nodes
    python bootstrap/pin.py --add "Design: TTS primary = F5-TTS" --type decision \
        --content "Chose F5-TTS over Piper for voice cloning capability." \
        --tags tts voice decision --permanent

    python bootstrap/pin.py --add "Arch: DER Loop diagram" --type image \
        --image-refs docs/der_loop.png --file-refs backend/agent/der_loop.py

    python bootstrap/pin.py --add "Spec: GOALS.md" --type doc \
        --file-refs bootstrap/GOALS.md --permanent

    python bootstrap/pin.py --add "Ref: xterm.js docs" --type url \
        --url-refs https://xtermjs.org/docs/

    # Query
    python bootstrap/pin.py --search "tts"
    python bootstrap/pin.py --list
    python bootstrap/pin.py --list --pin-type decision
    python bootstrap/pin.py --list --permanent

    # Graph edges between nodes
    python bootstrap/pin.py --link pin:PIN_ID landmark:lm_foo documents
    python bootstrap/pin.py --link pin:PIN_ID file:backend/agent/tts.py implements

    # Cross-project landmark bridging
    python bootstrap/pin.py --bridge lm_g1_backend_health \
        --remote-name "g1_api_healthy" --remote-project "other-project" \
        --confidence 0.95
    python bootstrap/pin.py --bridges            # list all bridges
    python bootstrap/pin.py --bridges lm_foo     # bridges for one landmark

    # Update a PiN
    python bootstrap/pin.py --update PIN_ID --content "new body" --permanent

    # Projects
    python bootstrap/pin.py --projects
    python bootstrap/pin.py --ensure-project "my-project" --path /some/path
"""

import sys
import os
import argparse
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from bootstrap.coordinates import CoordinateStore

PIN_TYPES = ["note", "file", "folder", "image", "doc", "url", "decision", "fragment"]


def cmd_add(store: CoordinateStore, args) -> None:
    pin_id = store.add_pin(
        title=args.add,
        pin_type=args.pin_type or "note",
        content=args.content or "",
        tags=args.tags or [],
        file_refs=args.file_refs or [],
        image_refs=args.image_refs or [],
        url_refs=args.url_refs or [],
        project_id=args.project or None,
        is_permanent=args.permanent,
    )
    ptype = args.pin_type or "note"
    print(f"PiN CREATED: {pin_id}  [{ptype}]")
    print(f"  Title: {args.add}")
    if args.tags:
        print(f"  Tags:  {', '.join(args.tags)}")
    if args.file_refs:
        print(f"  Files: {', '.join(args.file_refs)}")
    if args.image_refs:
        print(f"  Images:{', '.join(args.image_refs)}")
    if args.url_refs:
        print(f"  URLs:  {', '.join(args.url_refs)}")
    if args.permanent:
        print("  ★ PERMANENT — will never decay")


def cmd_update(store: CoordinateStore, args) -> None:
    perm = True if args.permanent else (False if args.no_permanent else None)
    store.update_pin(
        pin_id=args.update,
        content=args.content,
        tags=args.tags,
        file_refs=args.file_refs,
        image_refs=args.image_refs,
        url_refs=args.url_refs,
        is_permanent=perm,
    )
    print(f"PiN UPDATED: {args.update}")


def cmd_list(store: CoordinateStore, args) -> None:
    pins = store.get_pins(
        project_id=args.project or None,
        pin_type=args.pin_type or None,
        permanent_only=args.permanent,
        limit=args.limit,
    )
    if not pins:
        print("No PiNs found.")
        return
    print(f"PiNs ({len(pins)}):")
    print()
    for p in pins:
        perm_flag = " ★" if p["is_permanent"] else ""
        proj = f" [{p['project_id'][:8]}]" if p.get("project_id") else ""
        tags_str = f"  tags: {', '.join(p['tags'])}" if p.get("tags") else ""
        print(f"  {p['pin_id']}{perm_flag}  [{p['pin_type']}]{proj}  {p['title']}")
        if tags_str:
            print(tags_str)
        if p.get("file_refs"):
            print(f"  files: {', '.join(p['file_refs'])}")
        if p.get("image_refs"):
            print(f"  images: {', '.join(p['image_refs'])}")
        if p.get("url_refs"):
            print(f"  urls: {', '.join(p['url_refs'])}")
        preview = (p.get("content") or "").strip()[:80].replace("\n", " ")
        if preview:
            print(f"  {preview}...")
        print()


def cmd_search(store: CoordinateStore, args) -> None:
    results = store.search_pins(args.search, limit=args.limit)
    if not results:
        print(f"No PiNs matching '{args.search}'.")
        return
    print(f"PiN SEARCH: '{args.search}' — {len(results)} result(s)")
    print()
    for p in results:
        perm_flag = " ★" if p["is_permanent"] else ""
        print(f"  {p['pin_id']}{perm_flag}  [{p['pin_type']}]  {p['title']}")
        preview = (p.get("content") or "").strip()[:100].replace("\n", " ")
        if preview:
            print(f"  {preview}...")
        print()


def cmd_link(store: CoordinateStore, args) -> None:
    """
    Link two nodes: "type:id type:id relationship"
    Examples:
      pin:pin_abc123 landmark:lm_foo documents
      pin:pin_abc123 file:backend/agent/tts.py implements
    """
    try:
        src_type, src_id = args.link[0].split(":", 1)
        tgt_type, tgt_id = args.link[1].split(":", 1)
        relationship = args.link[2] if len(args.link) > 2 else "references"
    except ValueError:
        print("ERROR: --link expects: source_type:id target_type:id [relationship]")
        sys.exit(1)

    link_id = store.add_pin_link(
        source_type=src_type, source_id=src_id,
        target_type=tgt_type, target_id=tgt_id,
        relationship=relationship,
    )
    print(f"PiN LINK CREATED: link_id={link_id}")
    print(f"  {src_type}:{src_id} --[{relationship}]--> {tgt_type}:{tgt_id}")


def cmd_bridge(store: CoordinateStore, args) -> None:
    """Register a cross-project landmark bridge."""
    bridge_id = store.add_landmark_bridge(
        local_landmark_id=args.bridge,
        remote_landmark_name=args.remote_name,
        remote_project_id=args.remote_project or None,
        remote_instance_id=args.remote_instance or None,
        remote_landmark_id=args.remote_id or None,
        confidence=args.confidence,
        bridge_type=args.bridge_type,
        notes=args.notes,
    )
    print(f"LANDMARK BRIDGE CREATED: {bridge_id}")
    print(f"  Local:  {args.bridge}")
    print(f"  Remote: {args.remote_name}  (project={args.remote_project}  instance={args.remote_instance})")
    print(f"  Type: {args.bridge_type}  Confidence: {args.confidence:.2f}")


def cmd_bridges(store: CoordinateStore, args) -> None:
    landmark_id = args.bridges if args.bridges not in (True, None, "") else None
    bridges = store.get_landmark_bridges(local_landmark_id=landmark_id or None)
    if not bridges:
        print("No landmark bridges registered.")
        return
    print(f"LANDMARK BRIDGES ({len(bridges)}):")
    print()
    for b in bridges:
        print(f"  {b['bridge_id']}  [{b['bridge_type']}]  conf:{b['confidence']:.2f}")
        print(f"    local:  {b['local_landmark_id']}")
        print(f"    remote: {b['remote_landmark_name']}")
        if b.get("remote_project_id"):
            print(f"    project:{b['remote_project_id']}")
        if b.get("remote_instance_id"):
            print(f"    instance:{b['remote_instance_id']}")
        if b.get("notes"):
            print(f"    notes: {b['notes']}")
        print()


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
        description="PiN CLI — Primordial Information Nodes in the coordinate graph"
    )

    # PiN operations
    parser.add_argument("--add", metavar="TITLE",
                        help="Anchor a new PiN with this title")
    parser.add_argument("--update", metavar="PIN_ID",
                        help="Update an existing PiN")
    parser.add_argument("--list", action="store_true",
                        help="List PiNs")
    parser.add_argument("--search", metavar="QUERY",
                        help="Search PiNs by title/content/tags/file_refs")
    parser.add_argument("--link", nargs="+", metavar="TYPE:ID",
                        help="Link two nodes: src_type:id tgt_type:id [relationship]")

    # Landmark bridge operations
    parser.add_argument("--bridge", metavar="LOCAL_LANDMARK_ID",
                        help="Register a cross-project landmark bridge (provide local landmark ID)")
    parser.add_argument("--bridges", metavar="LANDMARK_ID", nargs="?", const=True,
                        help="List all landmark bridges, or filter to one landmark ID")
    parser.add_argument("--remote-name", metavar="NAME",
                        help="Remote landmark name/task_class for --bridge")
    parser.add_argument("--remote-project", metavar="PROJECT_ID",
                        help="Remote project ID for --bridge")
    parser.add_argument("--remote-instance", metavar="INSTANCE_ID",
                        help="Remote instance UUID for --bridge")
    parser.add_argument("--remote-id", metavar="LANDMARK_ID",
                        help="Remote landmark direct ID for --bridge (optional)")
    parser.add_argument("--confidence", type=float, default=1.0,
                        help="Bridge confidence 0.0-1.0 (default: 1.0)")
    parser.add_argument("--bridge-type", default="equivalent",
                        choices=["equivalent", "similar", "inverse"],
                        help="Bridge type (default: equivalent)")
    parser.add_argument("--notes", metavar="TEXT",
                        help="Notes for the bridge")

    # Project operations
    parser.add_argument("--projects", action="store_true",
                        help="List registered projects")
    parser.add_argument("--ensure-project", metavar="NAME",
                        help="Register a project by name (idempotent)")

    # PiN fields
    parser.add_argument("--type", dest="pin_type", choices=PIN_TYPES,
                        help="PiN type (default: note)")
    parser.add_argument("--content", metavar="MARKDOWN",
                        help="Markdown body / description")
    parser.add_argument("--tags", nargs="+", metavar="TAG")
    parser.add_argument("--file-refs", nargs="+", metavar="PATH",
                        help="File or folder paths")
    parser.add_argument("--image-refs", nargs="+", metavar="PATH",
                        help="Image paths/URLs")
    parser.add_argument("--url-refs", nargs="+", metavar="URL",
                        help="External URLs")
    parser.add_argument("--project", metavar="PROJECT_ID",
                        help="Project to associate with this PiN/list")
    parser.add_argument("--permanent", action="store_true",
                        help="Mark as permanent (never decays)")
    parser.add_argument("--no-permanent", action="store_true",
                        help="Remove permanent flag from a PiN")

    # Project fields
    parser.add_argument("--path", metavar="PATH",
                        help="Filesystem path for --ensure-project")
    parser.add_argument("--description", metavar="TEXT",
                        help="Description for --ensure-project")

    # Common
    parser.add_argument("--limit", type=int, default=50,
                        help="Max results (default: 50)")

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
    elif args.bridge:
        if not args.remote_name:
            print("ERROR: --bridge requires --remote-name")
            sys.exit(1)
        cmd_bridge(store, args)
    elif args.bridges is not None:
        cmd_bridges(store, args)
    elif args.projects:
        cmd_projects(store)
    elif args.ensure_project:
        cmd_ensure_project(store, args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
