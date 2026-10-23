"""Start Atlas and open Admin, Demo and/or the hosted Preview in the browser.

There is one Atlas layout. The old "desktop" and "both" arguments are still accepted so older
shortcuts keep working; they open the same Atlas.
"""
import argparse
import webbrowser
import launcher

PREVIEW = "https://office-atlas-mobile-preview.daaalil.chatgpt.site"

def edition_url(mode):
    if mode == "preview":
        return PREVIEW + "/"
    specs = launcher.servers()
    spec = next(s for s in specs if s["mode"] == ("admin" if mode == "admin" else "viewer"))
    return f"http://127.0.0.1:{spec['port']}/"

def launch(edition, mode, open_browser=True):
    if edition not in {"classic", "desktop", "both"} or mode not in {"admin", "demo", "preview", "all"}:
        raise ValueError("Unknown Atlas edition or mode")
    if mode != "preview":
        result = launcher.run(open_browser=False)
        if result:
            return result
    # "both" (Start-All-Atlas) also opens the hosted Preview.
    modes = (("admin", "demo", "preview") if edition == "both" else ("admin", "demo")) if mode == "all" else (mode,)
    for target in modes:
        url = edition_url(target)
        print(f"Atlas {target}: {url}")
        if open_browser:
            webbrowser.open_new_tab(url)
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edition", choices=["classic", "desktop", "both"])
    parser.add_argument("mode", choices=["admin", "demo", "preview", "all"])
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    raise SystemExit(launch(args.edition, args.mode, not args.no_browser))
