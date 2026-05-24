"""GitHub integration stubs for IRIS backend."""


# In-memory token storage (not persisted — for demo/verification only)
_github_token: str | None = None
_github_user: dict | None = None


def connect_with_pat(token: str) -> dict:
    """Store a GitHub Personal Access Token."""
    global _github_token, _github_user
    _github_token = token
    # Try to fetch user info via GitHub API if requests is available
    try:
        import requests
        resp = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"token {token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            _github_user = {
                "login": data.get("login"),
                "avatar_url": data.get("avatar_url"),
            }
            return {"status": "ok", **_github_user}
    except Exception:
        pass
    _github_user = {"login": "user", "avatar_url": ""}
    return {"status": "ok", **_github_user}


def is_connected() -> bool:
    """Return whether a GitHub PAT is stored."""
    return _github_token is not None


def disconnect() -> dict:
    """Remove stored GitHub credentials."""
    global _github_token, _github_user
    _github_token = None
    _github_user = None
    return {"status": "ok"}


def get_user() -> dict:
    """Return cached GitHub user info."""
    return _github_user or {}


def get_repos() -> list[dict]:
    """Return list of repositories for the authenticated user."""
    if not _github_token:
        return []
    try:
        import requests
        resp = requests.get(
            "https://api.github.com/user/repos?sort=updated&per_page=30",
            headers={"Authorization": f"token {_github_token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "full_name": r["full_name"],
                    "description": r.get("description", ""),
                    "updated_at": r["updated_at"],
                }
                for r in resp.json()
            ]
    except Exception:
        pass
    return []


def generate_ssh_key(name: str, key_type: str = "ed25519") -> dict:
    """Generate a new SSH key pair using ssh-keygen."""
    import subprocess
    import tempfile
    import os

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = os.path.join(tmpdir, name)
            type_flag = "-t" + key_type
            result = subprocess.run(
                ["ssh-keygen", type_flag, "-f", key_path, "-N", "", "-C", f"{name}@iris"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0 and os.path.exists(key_path + ".pub"):
                pass  # ssh-keygen may warn but still create keys
            if not os.path.exists(key_path + ".pub"):
                return {"status": "error", "error": "ssh-keygen failed"}
            with open(key_path + ".pub", "r", encoding="utf-8") as f:
                public_key = f.read().strip()
            with open(key_path, "r", encoding="utf-8") as f:
                private_key = f.read().strip()
            return {
                "status": "ok",
                "public_key": public_key,
                "private_key": private_key,
            }
    except FileNotFoundError:
        return {"status": "error", "error": "ssh-keygen not found"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def list_ssh_keys() -> list[dict]:
    """Return SSH keys for the authenticated user (alias)."""
    return get_ssh_keys()


def delete_ssh_key(key_id: int) -> dict:
    """Delete an SSH key from the authenticated user's account."""
    if not _github_token:
        return {"status": "error", "error": "not connected"}
    try:
        import requests
        resp = requests.delete(
            f"https://api.github.com/user/keys/{key_id}",
            headers={"Authorization": f"token {_github_token}"},
            timeout=10,
        )
        if resp.status_code in (204, 200):
            return {"status": "ok"}
        return {"status": "error", "error": resp.text}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def get_ssh_keys() -> list[dict]:
    """Return SSH keys for the authenticated user."""
    if not _github_token:
        return []
    try:
        import requests
        resp = requests.get(
            "https://api.github.com/user/keys",
            headers={"Authorization": f"token {_github_token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return [{"id": k["id"], "title": k["title"]} for k in resp.json()]
    except Exception:
        pass
    return []


def add_ssh_key(title: str, key: str) -> dict:
    """Add an SSH key to the authenticated user's account."""
    if not _github_token:
        return {"status": "error", "error": "not connected"}
    try:
        import requests
        resp = requests.post(
            "https://api.github.com/user/keys",
            headers={"Authorization": f"token {_github_token}"},
            json={"title": title, "key": key},
            timeout=10,
        )
        if resp.status_code in (201, 200):
            return {"status": "ok", "id": resp.json().get("id")}
        return {"status": "error", "error": resp.text}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def get_gists() -> list[dict]:
    """Return gists for the authenticated user."""
    if not _github_token:
        return []
    try:
        import requests
        resp = requests.get(
            "https://api.github.com/gists?per_page=20",
            headers={"Authorization": f"token {_github_token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return [
                {
                    "id": g["id"],
                    "description": g.get("description", ""),
                    "html_url": g["html_url"],
                }
                for g in resp.json()
            ]
    except Exception:
        pass
    return []


def create_gist(description: str, files: dict, public: bool = False) -> dict:
    """Create a new gist."""
    if not _github_token:
        return {"status": "error", "error": "not connected"}
    try:
        import requests
        resp = requests.post(
            "https://api.github.com/gists",
            headers={"Authorization": f"token {_github_token}"},
            json={"description": description, "public": public, "files": files},
            timeout=10,
        )
        if resp.status_code == 201:
            data = resp.json()
            return {"status": "ok", "id": data["id"], "url": data["html_url"]}
        return {"status": "error", "error": resp.text}
    except Exception as e:
        return {"status": "error", "error": str(e)}
