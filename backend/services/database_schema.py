"""Runtime-only schema migrations; importing the application never opens a seed writer."""
import json
from pathlib import Path


def initialize(path):
    import atlas_store as store
    from merge_data import atlas_schema
    from database_manager import HISTORY_SCHEMA
    import package_data
    import vdi_data
    from official_atlas import apply_visual_matches
    store.DB = Path(path)
    store.initialize()
    with store.connect() as con:
        atlas_schema(con)
        con.execute(HISTORY_SCHEMA)
        package_data.initialize(con)
        vdi_data.initialize(con)
        con.execute('create table if not exists official_records(id text primary key,body text not null)')
        con.execute('create table if not exists official_seating_mappings(legacy_id text primary key,official_id text unique,at text)')
        for row in json.loads((store.ROOT/'official-data.json').read_text())['records']:
            con.execute('insert or ignore into official_records values(?,?)',(row['id'],json.dumps(row)))
        apply_visual_matches(con)
        con.execute("insert or replace into metadata values('runtime.schema_version','1')")
