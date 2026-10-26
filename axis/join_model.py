#!/usr/bin/env python3
"""Join a model's downloaded parts into its GGUF file. Nothing else: no server, no chat.

Double-click "Join Model.bat", or run:  python join_model.py [--model KEY] [--folder DIR]
Parts are found in Downloads, this folder, the folder above it, %USERPROFILE%\\local-ai and
any --folder. Every part is checked against its published SHA-256 before it is used, and
a part is deleted only once it has been joined. The joined file goes next to this script,
where Start AA.bat finds it. An interrupted join resumes where it stopped.
"""
import argparse
import os
import re
import sys

if __package__:
    from . import start
else:
    import start

COPY_SUFFIX = re.compile(r" \(\d+\)")  # what a browser adds to a file it has already downloaded once


def listing():
    """The files in each folder that is searched for parts."""
    entries = {}
    for folder in start.SEARCH_DIRS:
        try:
            entries[folder] = os.listdir(folder)
        except OSError:
            pass
    return entries


def problems(name, size, entries):
    """Why a part that is not usable as found is wrong: unfinished, renamed by the browser or the wrong size."""
    found = []
    for folder, names in entries.items():
        for entry in names:
            path = os.path.join(folder, entry)
            if entry == name:
                actual = os.path.getsize(path)
                if actual != size:
                    found.append("%s is %s bytes, not %s: delete it and download it again" % (path, format(actual, ","), format(size, ",")))
            elif entry.startswith(name + ".") and entry.lower().endswith((".crdownload", ".partial", ".download", ".tmp")):
                found.append("%s has not finished downloading" % path)
            elif COPY_SUFFIX.sub("", entry) == name:
                found.append("%s was renamed by the browser (it was downloaded twice): rename it to %s, "
                             "after deleting any other copy" % (path, name))
    return found


def missing_parts(model, entries):
    """[(part name, what is wrong with files that look like it, its release)] for each part not usable as found."""
    missing = []
    for f in model["files"]:
        if not f["parts"] or start.file_status(f)[0] == "ready":
            continue
        view = start.parts_view(f)
        found, joining = start.parts_status(view)
        if not joining:
            missing += [(name, problems(name, size, entries), view["release"])
                        for (name, size, _), path in zip(start.part_list(view), found) if not path]
    return missing


def downloaded(model, entries):
    """Whether any part of this model, usable or not, is in a searched folder."""
    total = sum(len(start.parts_view(f)["parts"]) for f in model["files"])
    missing = missing_parts(model, entries)
    return len(missing) < total or any(found for _, found, _ in missing)


def report(model, entries):
    """List the parts that stop a model from being joined, with what is wrong with each one found."""
    start.log("%s cannot be joined yet. Missing or unusable parts:" % model["name"])
    run = []  # consecutive missing parts with nothing to explain, shown as one range

    def flush():
        if run:
            start.log("  " + run[0] + (" to " + run[-1].rsplit(".", 1)[1] if len(run) > 1 else ""))
            del run[:]
    missing = missing_parts(model, entries)
    for name, found, _ in missing:
        if not found and run and run[-1].rsplit(".", 1)[0] == name.rsplit(".", 1)[0]:
            run.append(name)
            continue
        flush()
        if found:
            start.log("  " + name)
            for problem in found:
                start.log("    " + problem)
        else:
            run.append(name)
    flush()
    # A model that shares a file with another lists that file's parts under the other model's release.
    releases = []
    for _, _, release in missing:
        if release not in releases:
            releases.append(release)
    start.log("\nDownload them from %s" % " and ".join(releases or [model["release"]]))
    start.log("Looked in:")
    for folder in start.SEARCH_DIRS:
        start.log("  " + folder)


def join(key):
    """Join every file of one model and keep them in one folder; return the path llama-server is given."""
    model = start.MODELS[key]
    state, path = start.model_status(model)
    if state == "ready":
        start.log("%s is already joined: %s" % (model["name"], path))
        return path
    if state != "parts":
        report(model, listing())
        sys.exit(1)
    start.log("Joining %s..." % model["name"])
    path = start.same_folder([start.materialize(f) for f in model["files"]])
    if os.path.normcase(os.path.dirname(os.path.abspath(path))) != os.path.normcase(start.HERE):
        start.log("The parts are on another drive, so the model stayed there. Move %s into AA's axis folder."
                  % ("its files" if len(model["files"]) > 1 else "it"))
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Join a model's downloaded parts into its GGUF file.")
    parser.add_argument("--model", choices=sorted(start.MODELS), help="the model to join (default: ask when several can be)")
    parser.add_argument("--folder", action="append", default=[], help="another folder that holds parts (repeatable)")
    args = parser.parse_args(argv)
    start.SEARCH_DIRS[:0] = [os.path.abspath(folder) for folder in args.folder]
    try:
        if args.model:
            key = args.model
        else:
            status = {key: start.model_status(m) for key, m in start.MODELS.items()}
            joinable = [key for key, (state, _) in status.items() if state == "parts"]
            entries = listing()
            partial = [key for key, (state, _) in status.items()
                       if state not in ("ready", "parts") and downloaded(start.MODELS[key], entries)]
            for key, (state, path) in status.items():
                if state == "ready":
                    start.log("Already joined: %s (%s)" % (start.MODELS[key]["name"], path))
            if not joinable:
                for key in partial:
                    report(start.MODELS[key], entries)
                ready = any(state == "ready" for state, _ in status.values())
                if not partial and not ready:
                    start.log("No model parts found. Download all the parts of a model into Downloads, then run this again.")
                return 0 if ready and not partial else 1
            key = joinable[0] if len(joinable) == 1 else start.choose(joinable)
        path = join(key)
    except SystemExit as stop:  # start.py stops with a message on a missing or damaged part
        if isinstance(stop.code, str):
            start.log(stop.code)
        return stop.code if isinstance(stop.code, int) else 1
    start.log("Model ready: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
