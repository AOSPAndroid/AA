"""Small, read-only SKILL.md library. Python 3.8+ standard library only."""
from dataclasses import dataclass
from pathlib import Path
import re


BUNDLED_SKILLS = Path(__file__).resolve().parent / "skills"
MAX_SKILLS = 24
MAX_FILE_BYTES = 12000
MAX_BODY = 2400  # A complete guide fits Axis's 3,000-character tool result budget.
MAX_DESCRIPTION = 160
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str

    def text(self):
        return "Skill: %s\n%s\n\n%s" % (self.name, self.description, self.body)


def skill_name(name):
    if not isinstance(name, str) or len(name) > 64 or NAME.fullmatch(name) is None:
        raise ValueError("Use a skill name from /skills (lowercase words separated by hyphens).")
    return name


def parse_skill(name, raw):
    """Deliberately support just two single-line front-matter fields, without YAML dependencies."""
    text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    parts = text.split("\n---\n", 1)
    if not text.startswith("---\n") or len(parts) != 2:
        raise ValueError("SKILL.md needs --- front matter with name and description.")
    metadata = {}
    for line in parts[0][4:].splitlines():
        key, separator, value = line.partition(":")
        if not separator or key not in ("name", "description") or key in metadata:
            raise ValueError("Use only name and description, once each, on single lines.")
        value = value.strip()
        if len(value) >= 2 and value[0] in ("'", '"') and value[-1] == value[0]:
            value = value[1:-1]
        metadata[key] = value
    description = metadata.get("description", "")
    body = parts[1].strip()
    if metadata.get("name") != name:
        raise ValueError("The name must match the skill's folder.")
    if (not description or len(description) > MAX_DESCRIPTION or
            any(ord(c) < 32 or ord(c) == 127 for c in description)):
        raise ValueError("Use a single-line description of 1 to %d characters." % MAX_DESCRIPTION)
    if not body or len(body) > MAX_BODY:
        raise ValueError("Use a skill body of 1 to %d characters; split longer procedures." % MAX_BODY)
    return Skill(name, description, body)


class SkillLibrary:
    def __init__(self, custom=None, bundled=BUNDLED_SKILLS):
        self.bundled = Path(bundled).resolve()
        self.custom = Path(custom).resolve() if custom else None

    def scan(self):
        skills, errors = {}, []
        roots = [self.bundled]
        if self.custom is not None and self.custom != self.bundled:
            roots.append(self.custom)
        for root in roots:
            try:
                folders = sorted(root.iterdir(), key=lambda path: path.name)
            except FileNotFoundError:
                continue
            except OSError:
                errors.append("A skills folder could not be read.")
                continue
            for folder in folders:
                if len(folder.name) > 64 or NAME.fullmatch(folder.name) is None:
                    continue
                path = folder / "SKILL.md"
                try:
                    # Reject directory links/junctions and linked files, including links within the root.
                    if folder.is_symlink() or folder.resolve().parent != root:
                        raise ValueError("Linked skill folders are not supported.")
                    if not folder.is_dir():
                        continue
                    if path.is_symlink() or path.resolve().parent != folder:
                        raise ValueError("Linked SKILL.md files are not supported.")
                    if not path.is_file():
                        continue
                    if folder.name in skills:
                        raise ValueError("A bundled skill already has this name; rename the custom skill.")
                    if len(skills) >= MAX_SKILLS:
                        raise ValueError("At most %d skills can be loaded." % MAX_SKILLS)
                    with path.open("rb") as source:
                        raw = source.read(MAX_FILE_BYTES + 1)
                    if len(raw) > MAX_FILE_BYTES:
                        raise ValueError("SKILL.md exceeds %d bytes." % MAX_FILE_BYTES)
                    skills[folder.name] = parse_skill(folder.name, raw)
                except (OSError, ValueError) as error:
                    reason = str(error) if isinstance(error, ValueError) else "SKILL.md could not be read."
                    errors.append("%s: %s" % (folder.name, reason))
        return skills, errors

    def summary(self):
        skills, errors = self.scan()
        lines = ["- %s: %s" % (skill.name, skill.description) for skill in skills.values()]
        if not lines:
            lines.append("No skills available.")
        if errors:
            lines.append("Some skills were skipped; /skills shows the reason.")
        return "\n".join(lines)

    def read(self, name):
        name = skill_name(name)
        skills, errors = self.scan()
        if name not in skills:
            reason = next((error for error in errors if error.startswith(name + ":")), None)
            raise ValueError(reason or "No skill %r. Use /skills to list available names." % name)
        return skills[name].text()

    def display(self, name=None):
        if name is not None:
            return self.read(name)
        skills, errors = self.scan()
        lines = ["Axis skills — ask Axis to use a skill for your task; /skills NAME reads its guide."]
        lines.extend("- %s: %s" % (skill.name, skill.description) for skill in skills.values())
        if not skills:
            lines.append("No skills available.")
        if errors:
            lines.append("\nSkipped skills:")
            lines.extend(errors[:MAX_SKILLS])
            if len(errors) > MAX_SKILLS:
                lines.append("... and %d more." % (len(errors) - MAX_SKILLS))
        return "\n".join(lines)
