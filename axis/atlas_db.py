"""Small, read-only lookups in an Atlas directory database; Python 3.8+ stdlib."""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import sqlite3
import time


WARNING = "Stored inventory, not live PC status or a current logged-on session."
MAX_QUERY_SECONDS = 3.0
_KINDS = ("people", "computers")
_TABLES = {"people": "users", "computers": "machines"}
_FIELDS = {
    "people": {"id": "canonical_key", "name": "full_name", "account": "user_id", "email": "email",
               "department": "department", "location": "location", "manager": "manager",
               "employee_number": "employee_number", "job_role": "job_role", "business_unit": "business_unit",
               "organisation": "organisational_unit", "last_login": "last_login_time"},
    "computers": {"id": "machine_name", "name": "machine_name", "model": "model_id", "status": "operational_status",
                  "assigned_to": "assigned_to", "last_logon_user": "last_logon_user", "serial": "serial_number",
                  "manufacturer": "manufacturer", "asset_tag": "asset_tag", "description": "short_description",
                  "last_discovered": "last_discovered", "updated_on": "updated_on", "location": "device_location",
                  "source_ci": "source_ci", "class": "sys_class_name", "category": "model_category"}}
_COMPACT = {"people": ("id", "name", "account", "email", "department", "location"),
            "computers": ("id", "name", "model", "status", "assigned_to", "last_logon_user", "category", "class")}
_REQUIRED = {"users": {"id", "canonical_key", "user_id", "user_id_norm", "full_name", "full_name_norm", "email", "email_norm"},
             "machines": {"id", "machine_name", "machine_name_norm"},
             "assignments": {"user_id_ref", "machine_id", "relationship_type"}}


def _tool(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required,
                           "additionalProperties": False}}}


_PAGE = {"offset": {"type": "integer", "minimum": 0, "maximum": 10000},
         "limit": {"type": "integer", "minimum": 1, "maximum": 25}}
TOOLS = [
    _tool("search_atlas", "Search the local Atlas inventory by person name, email, account or PC name. Exact matches come first. Results are stored records, not live status. Use returned kind/id with read_atlas_record for linked people and PCs. No Atlas server is needed.",
          dict({"query": {"type": "string"}, "kind": {"type": "string", "enum": ["all", "people", "computers"]}}, **_PAGE), ["query"]),
    _tool("read_atlas_record", "Read an exact Atlas record and its stored person-PC links using a kind/id returned by search_atlas. Assigned and last-logged-on inventory links have different meanings. Never choose between ambiguous people or PCs without the user.",
          dict({"kind": {"type": "string", "enum": list(_KINDS)}, "id": {"type": "string"}}, **_PAGE), ["kind", "id"]),
]
TOOL_NAMES = {tool["function"]["name"] for tool in TOOLS}


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(ord(c) < 32 for c in value):
        raise ValueError("Use a non-empty %s of at most 256 characters" % label)
    return " ".join(value.strip().split())


def _page(args, default):
    offset, limit = args.get("offset", 0), args.get("limit", default)
    if type(offset) is not int or not 0 <= offset <= 10000 or type(limit) is not int or not 1 <= limit <= 25:
        raise ValueError("Use offset from 0 to 10000 and limit from 1 to 25; narrow broad searches")
    return offset, limit


def _like(value):
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _device_info(record):
    """Atlas's inventory classification; eligibility is not a live Windows check."""
    name = record.get("name", "").strip()
    hostname = name.upper().split(".")[0]
    text = " ".join(record.get(key, "") for key in ("category", "model", "class")).lower()
    if "iphone" in text or hostname == "IPHONE" or hostname.startswith("IPHONE-"):
        kind = "iphone"
    elif re.search(r"\b(ipad|tablet)\b", text) or hostname in ("IPAD", "TABLET") or hostname.startswith(("IPAD-", "TABLET-")):
        kind = "tablet"
    elif re.search(r"mobile device|handheld|android|\b(phone|smartphone)\b", text) or hostname == "PHONE" or hostname.startswith("PHONE-"):
        kind = "phone"
    elif re.search(r"\b(macbook|imac|mac mini|mac pro)\b", text):
        kind = "mac"
    elif re.search(r"\b(vdi|virtual desktop|virtual machine)\b", text) or "VDI" in hostname:
        kind = "vdi"
    elif re.search(r"\b(laptop|notebook|latitude|thinkpad|elitebook|zbook|probook)\b", text):
        kind = "laptop"
    elif re.match(r"^[A-Z]{3}PWMK", hostname):
        kind = "kiosk"
    elif re.match(r"^[A-Z]{3}PWMF", hostname) or re.search(r"\b(computer|desktop|workstation)\b", text):
        kind = "desktop"
    else:
        kind = "inventory" if hostname.startswith("INVENTORY-") else "other"
    eligible = bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name)) and not name.upper().startswith("INVENTORY-") and kind not in ("iphone", "phone", "tablet", "mac", "inventory")
    return {"device_kind": kind, "windows_remote_supported": eligible}


class AtlasDatabase:
    def __init__(self, path=None, directory=None):
        self.path = None
        self._problem = "not configured; use --atlas-db PATH or place office_atlas.db beside agent.py"
        chosen = path or os.environ.get("AGENT_ATLAS_DB") or os.environ.get("ATLAS_DB_PATH")
        if chosen:
            self.path = Path(chosen).expanduser().resolve()
        else:
            root = Path(directory) if directory is not None else Path(__file__).resolve().parent
            candidates = [root / "office_atlas.db", root / "data" / "office_atlas.db"]
            if os.name == "nt":
                candidates.append(Path(r"F:\Atlas\DB\office_atlas.db"))
            found = sorted({p.resolve() for p in candidates if p.is_file()}, key=str)
            if len(found) == 1:
                self.path = found[0]
            elif len(found) > 1:
                self._problem = "multiple databases found; choose --atlas-db PATH: " + ", ".join(map(str, found))

    @property
    def available(self):
        return self.path is not None and self.path.is_file()

    @property
    def status(self):
        if self.path is None:
            return self._problem
        return ("read-only: " if self.available else "file not found: ") + str(self.path)

    def fingerprint(self):
        values = []
        if self.path is not None:
            for filename in (str(self.path), str(self.path) + "-wal"):
                try:
                    stat = os.stat(filename)
                    values.append((stat.st_mtime_ns, stat.st_size, stat.st_ino))
                except OSError:
                    values.append(None)
        return (str(self.path) if self.path is not None else None, tuple(values))

    @contextmanager
    def _connect(self):
        if not self.available:
            raise ValueError("Atlas database " + self.status)
        # mode=ro keeps SQLite from creating or changing the database. Do not use
        # immutable: Atlas may have committed newer inventory in its WAL.
        con = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=1.0)
        try:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA query_only=ON")
            con.execute("PRAGMA trusted_schema=OFF")
            deadline = time.monotonic() + MAX_QUERY_SECONDS
            con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            con.execute("BEGIN")
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            columns = {}
            for table, required in _REQUIRED.items():
                columns[table] = {row[1] for row in con.execute("PRAGMA table_info(" + table + ")")}
                if table not in tables or not required <= columns[table]:
                    raise ValueError("Not a compatible Atlas directory database: missing %s fields. Select office_atlas.db containing users, machines and assignments." % table)
            if "user_aliases" in tables:
                known = {row[1] for row in con.execute("PRAGMA table_info(user_aliases)")}
                if {"user_id_ref", "alias_type", "alias_norm"} <= known:
                    columns["user_aliases"] = known
            yield con, tables, columns
        finally:
            con.close()

    def _source(self, con, tables):
        source = {"path": str(self.path)}
        if "metadata" in tables:
            values = dict(con.execute("SELECT key,value FROM metadata WHERE key IN "
                                      "('directory.created_at','created_at','directory.generation','generation')"))
            # A runtime DB with directory metadata must not borrow an old seed date.
            runtime = any(key.startswith("directory.") for key in values)
            imported = values.get("directory.created_at") if runtime else values.get("created_at")
            generation = values.get("directory.generation") if runtime else values.get("generation")
            if imported:
                source["directory_imported_at"] = str(imported)[:128]
            if generation:
                source["generation"] = str(generation)[:128]
        return source

    @staticmethod
    def _select(kind, columns, compact=False, alias="r"):
        fields = _COMPACT[kind] if compact else _FIELDS[kind]
        return ",".join(alias + '."' + source + '" AS "' + target + '"'
                        for target in fields for source in [_FIELDS[kind][target]] if source in columns[_TABLES[kind]])

    @staticmethod
    def _record(row, kind):
        # Bound imported text so a corrupt/oversized field cannot fill model context.
        if len(str(row["id"] or "")) > 256 or not row["id"]:
            raise ValueError("Atlas returned a missing or oversized record identifier; narrow the query or repair the source inventory")
        record = dict({"kind": kind}, **{key: str(value or "")[:512] for key, value in dict(row).items()})
        if kind == "computers":
            record.update(_device_info(record))
        return record

    def _where(self, kind, query, columns, exact):
        known = columns[_TABLES[kind]]
        if not exact:
            names = ("full_name_norm", "user_id_norm", "email_norm", "employee_number") if kind == "people" else ("machine_name_norm", "serial_number", "asset_tag", "model_id", "source_ci")
            names = [name for name in names if name in known]
            return " OR ".join('lower(r."' + name + '") LIKE ? ESCAPE \'\\\'' for name in names), [_like(query)] * len(names)
        if kind == "computers":
            names = [name for name in ("machine_name_norm", "serial_number", "correlation_id", "asset_tag", "source_ci") if name in known]
            condition = " OR ".join('lower(r."' + name + '")=?' for name in names)
            params = [query.rstrip(".")] * len(names)
            if "." not in query and "\\" not in query:
                short = "CASE WHEN instr(r.machine_name_norm,'\\')>0 THEN substr(r.machine_name_norm,instr(r.machine_name_norm,'\\')+1) ELSE r.machine_name_norm END"
                condition += " OR (CASE WHEN instr(" + short + ",'.')>0 THEN substr(" + short + ",1,instr(" + short + ",'.')-1) ELSE " + short + " END)=?"
                params.append(query)
            return condition, params
        domain, separator, account = query.rpartition("\\")
        variants = [account]
        if re.fullmatch(r"x[0-9]+", account):
            variants.append("g" + account[1:])
        values = variants + ([domain + "\\" + name for name in variants] if separator else [])
        placeholders = ",".join("?" for _ in values)
        account_sql = "CASE WHEN instr(r.user_id_norm,'\\')>0 THEN substr(r.user_id_norm,instr(r.user_id_norm,'\\')+1) ELSE r.user_id_norm END"
        if separator:
            full = [domain + "\\" + name for name in variants]
            marks = ",".join("?" for _ in full)
            condition = "(r.user_id_norm IN (" + marks + ")"
            params = list(full)
            if "user_aliases" in columns:
                condition += " OR r.id IN (SELECT user_id_ref FROM user_aliases WHERE alias_norm IN (" + marks + ") AND alias_type IN ('user_id','login','windows_login','account','matching_account'))"
                params += full
            # Bare exported G/X accounts are usable when their domain is unknown;
            # a known foreign domain must never be discarded during fallback.
            condition += " OR (" + account_sql + " IN (" + ",".join("?" for _ in variants) + ")"
            params += variants
            if "user_aliases" in columns:
                condition += " AND (instr(r.user_id_norm,'\\')>0 OR NOT EXISTS (SELECT 1 FROM user_aliases a WHERE a.user_id_ref=r.id AND a.alias_type IN ('user_id','login','windows_login','account','matching_account') AND instr(a.alias_norm,'\\')>0 AND substr(a.alias_norm,1,instr(a.alias_norm,'\\')-1)<>?))"
                params.append(domain)
            condition += ")) AND (instr(r.user_id_norm,'\\')=0 OR substr(r.user_id_norm,1,instr(r.user_id_norm,'\\')-1)=?)"
            params.append(domain)
            return condition, params
        condition = "(" + account_sql + " IN (" + ",".join("?" for _ in variants) + ")"
        params = list(variants)
        if "user_aliases" in columns:
            condition += " OR r.id IN (SELECT user_id_ref FROM user_aliases WHERE alias_norm IN (" + placeholders + ") AND alias_type IN ('user_id','login','windows_login','account','matching_account'))"
            params += values
        condition += ")"
        for name in ("email_norm", "canonical_key", "employee_number", "full_name_norm"):
            if name in known:
                condition += ' OR lower(r."' + name + '")=?'
                params.append(query)
        if "user_aliases" in columns:
            condition += " OR r.id IN (SELECT user_id_ref FROM user_aliases WHERE alias_norm=? AND alias_type IN ('email','upn','user_principal_name','employee_number','employee_id','brid','canonical_key','matching_email','matching_employee','name'))"
            params.append(query)
        return condition, params

    def _search(self, con, columns, query, kind, offset, limit, exact):
        parts, params = [], []
        for item_kind in (_KINDS if kind == "all" else (kind,)):
            condition, values = self._where(item_kind, query, columns, exact)
            # A compact common projection allows one global page across both kinds.
            fields = ("id", "name", "account", "email", "department", "location", "model", "status", "assigned_to", "last_logon_user", "category", "class")
            selected = []
            for field in fields:
                source = _FIELDS[item_kind].get(field)
                selected.append(('r."' + source + '"' if source in columns[_TABLES[item_kind]] else "''") + ' AS "' + field + '"')
            parts.append("SELECT '" + item_kind + "' AS kind," + ",".join(selected) + " FROM " + _TABLES[item_kind] + " r WHERE (" + condition + ")")
            params += values
        sql = " UNION ALL ".join(parts) + " ORDER BY kind,name,id LIMIT ? OFFSET ?"
        rows = con.execute(sql, params + [limit + 1, offset]).fetchall()
        return [self._record({key: row[key] for key in _COMPACT[row["kind"]] if key in row.keys()}, row["kind"]) for row in rows]

    def _read(self, con, columns, kind, record_id, offset, limit):
        column = "canonical_key" if kind == "people" else "machine_name"
        rows = con.execute("SELECT r.id AS _row_id," + self._select(kind, columns) + " FROM " + _TABLES[kind] + ' r WHERE r."' + column + '"=? LIMIT 2', (record_id,)).fetchall()
        if not rows:
            raise ValueError("Atlas record no longer exists; search again for the current record")
        if len(rows) != 1:
            raise ValueError("Atlas record identifier is ambiguous; correct the duplicate source records before selecting a target")
        row = rows[0]
        record = self._record({key: row[key] for key in row.keys() if key != "_row_id"}, kind)
        other = "computers" if kind == "people" else "people"
        target = "machine_id" if kind == "people" else "user_id_ref"
        own = "user_id_ref" if kind == "people" else "machine_id"
        links = con.execute("SELECT " + self._select(other, columns, compact=True) + ",a.relationship_type FROM assignments a JOIN " + _TABLES[other] + " r ON r.id=a." + target + " WHERE a." + own + "=? ORDER BY a.relationship_type,r.id LIMIT ? OFFSET ?", (row["_row_id"], limit + 1, offset)).fetchall()
        items = []
        for link in links[:limit]:
            item = self._record({key: link[key] for key in link.keys() if key != "relationship_type"}, other)
            item["relationship"] = {"assigned_to": "Assigned", "last_logon_user": "Last logged on (inventory)"}.get(link["relationship_type"], "Other stored relationship")
            items.append(item)
        return {"kind": kind, "id": record_id, "record": record, "links": items, "offset": offset,
                "next_offset": offset + limit if len(links) > limit else None}

    def call(self, name, args):
        result = {"source": {"path": str(self.path) if self.path is not None else None}, "warning": WARNING}
        try:
            if not isinstance(args, dict) or name not in TOOL_NAMES:
                raise ValueError("Unknown Atlas tool or invalid arguments")
            allowed = {"query", "kind", "offset", "limit"} if name == "search_atlas" else {"kind", "id", "offset", "limit"}
            if set(args) - allowed:
                raise ValueError("Unsupported Atlas arguments; use the named lookup fields")
            offset, limit = _page(args, 10 if name == "search_atlas" else 25)
            kind = args.get("kind", "all")
            if kind not in (_KINDS + ("all",) if name == "search_atlas" else _KINDS):
                raise ValueError("Invalid Atlas record kind")
            with self._connect() as (con, tables, columns):
                result["source"] = self._source(con, tables)
                if any(table.startswith("vdi_") for table in tables):
                    result["warning"] += " Separate Atlas VDI inventory is not included in this lookup."
                if name == "search_atlas":
                    query = _text(args.get("query"), "query")
                    rows = self._search(con, columns, query.lower(), kind, offset, limit, True)
                    exact = bool(rows)
                    # Later pages must not switch from exact results to substring matches.
                    if not exact and offset:
                        exact = bool(self._search(con, columns, query.lower(), kind, 0, 1, True))
                    if not exact:
                        rows = self._search(con, columns, query.lower(), kind, offset, limit, False)
                    result.update(query=query, kind=kind, match="exact" if exact else "contains", items=rows[:limit], offset=offset,
                                  next_offset=offset + limit if len(rows) > limit else None)
                else:
                    result.update(self._read(con, columns, kind, _text(args.get("id"), "record id"), offset, limit))
        except sqlite3.OperationalError as error:
            message = str(error).lower()
            if "locked" in message or "busy" in message:
                result["error"] = "Atlas database is busy. Retry after the current import finishes."
            elif "interrupt" in message:
                result["error"] = "Atlas lookup exceeded its time limit; narrow the name/account/PC query."
            else:
                result["error"] = "Cannot read the Atlas directory database; check its path, permissions and schema. " + str(error)
        except (sqlite3.DatabaseError, ValueError, OSError) as error:
            result["error"] = str(error)
        return result
