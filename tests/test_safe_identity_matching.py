"""Typed identities, domain-safe links and source-aware machine resolution."""
import csv
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlite_fixture import connect as fixture_connect, isolate_backend_database
from directory_lookup import exact_users, prepare_views, resolve_directory, search_directory
from directory_workbook import build, norm, schema
from identity_links import MATCHING_VERSION, build_index, candidates, rebuild_links
from merge_data import atlas_schema, merge_directory
from seating_excel import account_index, stamp
from test_directory_exports import device_sheets, workbook
import atlas_store
import vdi_data
import vdi_inventory


def user(con, uid, login='', name='', email='', employee=''):
    con.execute('insert into users(id,canonical_key,user_id,user_id_norm,full_name,full_name_norm,email,email_norm,employee_number) values(?,?,?,?,?,?,?,?,?)',
                (uid, 'person:'+str(uid), login, norm(login), name, norm(name), email, norm(email), employee))


def machine(con, mid, name, assigned='', logged='', category='', source_ci=''):
    con.execute('insert into machines(id,machine_name,machine_name_norm,assigned_to,last_logon_user,model_category,source_ci) values(?,?,?,?,?,?,?)',
                (mid, name, norm(name), assigned, logged, category, source_ci))


def alias(con, uid, kind, value):
    con.execute('insert into user_aliases(user_id_ref,alias_type,alias_value,alias_norm) values(?,?,?,?)', (uid, kind, value, norm(value)))


def citrix(con, name, account):
    stream=io.StringIO(newline='');writer=csv.writer(stream)
    writer.writerow(['Name','User','Machine Catalog']);writer.writerow([name,account,'Fictional catalog'])
    rows=vdi_data.parse_csv(stream.getvalue().encode())[0]
    vdi_data.write_rows(con, rows, 'fictional.csv', '2026-10-07')
    return rows


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.con=fixture_connect(':memory:');self.addCleanup(self.con.close)
        self.con.row_factory=sqlite3.Row;schema(self.con)

    def people(self, query):
        return {row['id'] for row in exact_users(self.con,query)}

    def prepare(self):
        rebuild_links(self.con);prepare_views(self.con)

    def test_qualified_wrong_domain_never_links_even_with_bare_alias(self):
        user(self.con,1,'INTRANET\\G55','First Person');alias(self.con,1,'user_id','x55')
        machine(self.con,1,'PC-1','CLIENT\\x55','CLIENT\\x55')
        result=rebuild_links(self.con)
        self.assertEqual(result,{'linked':0,'ambiguous':0,'unmatched':2})
        prepare_views(self.con)
        self.assertEqual(self.people('CLIENT\\x55'),set())
        self.assertEqual(self.people('INTRANET\\x55'),{1})
        index,_=account_index(self.con)
        self.assertEqual(candidates(index,'CLIENT\\x55',allow_names=False),set())
        self.assertEqual(candidates(index,'INTRANET\\x55',allow_names=False),{'person:1'})

    def test_domain_exact_wins_and_bare_alias_preserves_two_domain_collision(self):
        user(self.con,1,'INTRANET\\G0055','First Person');user(self.con,2,'CLIENT\\G0055','Second Person')
        machine(self.con,1,'PC-1','INTRANET\\x0055','CLIENT\\x0055')
        self.prepare()
        self.assertEqual(self.people('x0055'),{1,2})
        self.assertEqual(self.people('INTRANET\\X0055'),{1})
        self.assertEqual(self.people('CLIENT\\x0055'),{2})
        self.assertEqual(self.people('x55'),set(),'Leading zeroes are identity evidence')
        links={tuple(row) for row in self.con.execute('select user_id_ref,relationship_type from assignments')}
        self.assertEqual(links,{(1,'assigned_to'),(2,'last_logon_user')})

    def test_identity_precedes_names_and_historical_logon_name_remains_inventory_evidence(self):
        user(self.con,1,'G123','First Person');user(self.con,2,'other','x123')
        machine(self.con,1,'PC-1','x123','x123');machine(self.con,2,'PC-2','First Person','First Person');machine(self.con,3,'PC-3','','Missing Person')
        self.prepare()
        self.assertEqual(self.people('X123'),{1})
        self.assertEqual(self.people('name:x123'),set())
        self.assertEqual({tuple(row) for row in self.con.execute('select machine_id,user_id_ref,relationship_type from assignments')},
                         {(1,1,'assigned_to'),(1,1,'last_logon_user'),(2,1,'assigned_to'),(2,1,'last_logon_user')})
        diagnostics=json.loads(self.con.execute("select value from metadata where key='matching_diagnostics'").fetchone()[0])
        self.assertEqual(diagnostics['fields']['last_logon_user']['unmatched'],1)
        self.assertEqual(diagnostics['fields']['last_logon_user']['name_matches'],1)
        self.assertEqual(diagnostics['fields']['last_logon_user']['identifier_matches'],1)
        self.assertEqual(diagnostics['examples'][0]['field'],'last_logon_user')

    def test_separate_g_and_x_people_remain_ambiguous(self):
        user(self.con,1,'G123','First Person');user(self.con,2,'X123','Other Person')
        machine(self.con,1,'PC-1','x123','x123');self.prepare()
        self.assertEqual(self.people('x123'),{1,2})
        self.assertEqual(self.people('DOMAIN\\x123'),{1,2})
        self.assertEqual(self.con.execute('select count(*) from assignments').fetchone()[0],0)

    def test_duplicate_names_and_placeholders_never_become_confirmed_links(self):
        user(self.con,1,'one','Same Name');user(self.con,2,'two','Same Name');user(self.con,3,'three','(empty)')
        machine(self.con,1,'PC-1','Same Name','Same Name');machine(self.con,2,'PC-2','(empty)','(empty)')
        self.prepare()
        self.assertEqual(self.people('  SAME   NAME  '),{1,2})
        self.assertEqual(self.people('(empty)'),set())
        self.assertEqual(self.con.execute('select count(*) from assignments').fetchone()[0],0)

    def test_full_email_upn_and_exported_aliases_without_localpart_inference(self):
        user(self.con,1,'Person.UPN@EXAMPLE.INVALID','First Person','different.mail@example.invalid')
        alias(self.con,1,'user_id','alias.upn@example.invalid');alias(self.con,1,'email','Second.Mail@example.invalid')
        user(self.con,2,'person.upn','Other Person')
        machine(self.con,1,'PC-1',' person.upn@EXAMPLE.INVALID ','alias.upn@example.invalid')
        self.prepare()
        for query in ('PERSON.UPN@EXAMPLE.INVALID',' alias.upn@EXAMPLE.INVALID ',' SECOND.MAIL@EXAMPLE.INVALID ','different.mail@example.invalid'):
            self.assertEqual(self.people(query),{1})
        self.assertEqual(self.people('person.upn'),{2})
        self.assertEqual({row[0] for row in self.con.execute('select user_id_ref from assignments')},{1})
        index,_=account_index(self.con)
        self.assertEqual(candidates(index,'ALIAS.UPN@example.invalid',allow_names=False),{'person:1'})
        self.assertEqual(candidates(index,'person.upn',allow_names=False),{'person:2'})

    def test_explicit_prefixes_restrict_exact_and_partial_fields(self):
        user(self.con,1,'G123','First Person','person@example.invalid','E123');self.prepare()
        for term in ('email:G123','email:First Person','name:G123','brid:G123','email:First','name:E123'):
            self.assertEqual(search_directory(self.con,term)['users'],[],term)
        for term in ('email:person@','name:FIRST','brid:E12','user:x123'):
            self.assertEqual({r['id'] for r in search_directory(self.con,term)['users']},{1},term)

    def test_qualified_alias_does_not_claim_realm_of_unqualified_primary(self):
        user(self.con,1,'G55','First Person');alias(self.con,1,'user_id','CLIENT\\x55')
        machine(self.con,1,'PC-1','INTRANET\\x55','CLIENT\\x55');self.prepare()
        self.assertEqual(self.people('INTRANET\\x55'),{1})
        self.assertEqual(self.con.execute('select count(*) from assignments').fetchone()[0],2)
        vdi_data.initialize(self.con);rows=citrix(self.con,'VDI-1','INTRANET\\x55')
        self.assertEqual(vdi_data.match_refs(self.con,rows)[0]['matched_users'],1)

    def test_citrix_explicit_upn_matches_only_account_not_mail_or_name(self):
        user(self.con,1,'worker.upn@example.invalid','First Person','different.mail@example.invalid')
        alias(self.con,1,'user_id','alias.upn@example.invalid');alias(self.con,1,'email','mail.alias@example.invalid')
        user(self.con,2,'other','worker.upn@example.invalid')
        vdi_data.initialize(self.con)
        for account in ('worker.upn@example.invalid','alias.upn@example.invalid'):
            rows=citrix(self.con,'VDI-1',account)
            self.assertEqual(vdi_data.match_refs(self.con,rows)[1],{(next(iter(rows)),'person:1')})
        for account in ('different.mail@example.invalid','mail.alias@example.invalid','worker.upn'):
            rows=citrix(self.con,'VDI-1',account)
            self.assertEqual(vdi_data.match_refs(self.con,rows)[1],set())

    def test_identifier_lookup_keeps_old_readonly_exports_without_derived_aliases(self):
        user(self.con,1,'INTRANET\\G55','First Person');user(self.con,2,'CLIENT\\G55','Second Person')
        prepare_views(self.con);self.con.execute('pragma query_only=on')
        self.assertEqual(self.people('x55'),{1,2})
        self.assertEqual(self.people('INTRANET\\x55'),{1})
        self.assertEqual(self.people('OTHER\\x55'),set())
        self.assertEqual(self.con.execute('select count(*) from user_aliases').fetchone()[0],0)

    def test_unicode_canonical_key_round_trips_old_readonly_exports(self):
        user(self.con,1,'','First Person','groß@example.invalid')
        self.con.execute("update users set canonical_key='email:groß@example.invalid'")
        prepare_views(self.con);self.con.execute('pragma query_only=on')
        self.assertEqual(self.people('email:groß@example.invalid'),{1})


class MachineMatchingTests(unittest.TestCase):
    setUp=MatchingTests.setUp
    prepare=MatchingTests.prepare

    def test_physical_only_unique_short_fqdn_resolves_exact_target(self):
        machine(self.con,1,'PC-1.ONE.INVALID');self.prepare()
        for value in ('pc-1','PC-1.ONE.INVALID.','pc-1.one.invalid'):
            records=vdi_inventory.find_machines(self.con,value)
            self.assertEqual([row['name'] for row in records],['PC-1.ONE.INVALID'])
            self.assertEqual(search_directory(self.con,'machine:'+value)['machines'][0]['name'],'PC-1.ONE.INVALID')
        result=resolve_directory(self.con,'PC-1')
        self.assertFalse(result['matched']);self.assertEqual(result['users'],[])
        self.assertEqual(result['machine']['name'],'PC-1.ONE.INVALID')

    def test_physical_only_bare_and_multiple_fqdn_are_all_ambiguous(self):
        for mid,name in enumerate(('PC-1','PC-1.ONE.INVALID','PC-1.TWO.INVALID'),1):machine(self.con,mid,name)
        self.prepare()
        result=resolve_directory(self.con,'PC-1')
        self.assertTrue(result['ambiguous']);self.assertIsNone(result['machine']);self.assertEqual(len(result['machines']),3)
        self.assertEqual(len(search_directory(self.con,'machine:PC-1')['machines']),3)
        self.assertEqual(vdi_inventory.find_machines(self.con,'PC-1.ONE.INVALID')[0]['name'],'PC-1.ONE.INVALID')

    def test_qualified_netbios_sources_merge_only_same_identity_and_remain_nonremote(self):
        user(self.con,1,'G55','First Person');machine(self.con,1,'DOMAIN\\PC-1','G55',category='Computer',source_ci='PC-1')
        self.prepare();vdi_data.initialize(self.con);citrix(self.con,'DOMAIN\\PC-1','G55')
        records=vdi_inventory.find_machines(self.con,'DOMAIN\\PC-1')
        self.assertEqual(len(records),1);self.assertEqual(records[0]['vdi_catalog'],'Fictional catalog')
        self.assertFalse(records[0]['windows_remote_supported'])
        self.assertEqual([r['id'] for r in vdi_inventory.assigned_users(self.con,records[0])],[1])
        machine(self.con,2,'OTHER\\PC-1',category='Computer',source_ci='PC-1')
        self.assertTrue(resolve_directory(self.con,'PC-1')['ambiguous'])

    def test_owner_and_last_logon_evidence_stay_separate_when_machine_shared(self):
        user(self.con,1,'owner','First Person');user(self.con,2,'visitor','Second Person')
        machine(self.con,1,'PC-1','owner','visitor');self.prepare()
        result=resolve_directory(self.con,'PC-1')
        self.assertFalse(result['matched']);self.assertTrue(result['ambiguous'])
        self.assertEqual({(r['id'],r['assigned_relationship'],r['logon_relationship']) for r in result['users']},{(1,1,0),(2,0,1)})
        self.assertEqual(result['machine']['name'],'PC-1')


class PersistentMatchingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'runtime.db'
        with fixture_connect(self.db) as con:
            schema(con);con.execute("insert into metadata values('atlas.seeded','1')")
            user(con,1,'INTRANET\\G55','First Person');user(con,2,'other','Second Person')
            machine(con,1,'PC-1','CLIENT\\x55','INTRANET\\x55')
            machine(con,2,'PC-2','G55','')
            con.execute("insert into assignments(user_id_ref,machine_id,relationship_type,source_value) values(1,1,'assigned_to','CLIENT\\x55')")
            con.execute("insert into assignments(user_id_ref,machine_id,relationship_type,source_value) values(2,2,'assigned_to','explicit manual override')")

    def test_admin_migration_repairs_derived_links_once_preserves_raw_and_manual(self):
        with fixture_connect(self.db) as con:
            before={table:list(con.execute('select * from '+table)) for table in ('users','machines')}
        with patch.object(atlas_store,'DB',self.db):
            atlas_store.initialize()
            with fixture_connect(self.db) as con:
                self.assertEqual(before,{table:list(con.execute('select * from '+table)) for table in before})
                self.assertEqual({tuple(r) for r in con.execute('select user_id_ref,machine_id,relationship_type from assignments')},{(1,1,'last_logon_user'),(2,2,'assigned_to')})
                generation=con.execute("select value from metadata where key='directory.generation'").fetchone()[0]
                self.assertEqual(con.execute("select value from metadata where key='directory.matching_version'").fetchone()[0],MATCHING_VERSION)
                self.assertTrue(con.execute("select 1 from user_aliases where alias_type='matching_account'").fetchone())
            with patch('identity_links.rebuild_links',side_effect=AssertionError('No repeat rebuild')):
                atlas_store.initialize()
            with fixture_connect(self.db) as con:
                self.assertEqual(con.execute("select value from metadata where key='directory.generation'").fetchone()[0],generation)

    def test_old_backup_restore_rebuilds_aliases_and_replaces_stale_version_diagnostics(self):
        old=self.root/'old.db'
        with fixture_connect(old) as con:
            schema(con);user(con,9,'DOMAIN\\G99','Replacement Person');machine(con,9,'PC-9','DOMAIN\\x99','')
        with fixture_connect(self.db) as con:
            con.execute("insert into metadata values('matching_accounts_version','2')")
            con.execute("insert into metadata values('matching_diagnostics','old diagnostic')")
        merge_directory(self.db,old)
        with fixture_connect(self.db) as con:
            con.row_factory=sqlite3.Row;prepare_views(con)
            self.assertEqual([r['id'] for r in exact_users(con,'x99')],[9])
            self.assertEqual(con.execute('select user_id_ref from assignments').fetchone()[0],9)
            self.assertNotEqual(con.execute("select value from metadata where key='matching_diagnostics'").fetchone()[0],'old diagnostic')
            self.assertEqual(con.execute("select value from metadata where key='matching_accounts_version'").fetchone()[0],MATCHING_VERSION)

    def test_backup_restore_retains_manual_links_but_repairs_recognized_unsafe_links(self):
        backup=self.root/'backup.db'
        with fixture_connect(self.db) as source,fixture_connect(backup) as destination:
            source.backup(destination)
        merge_directory(self.db,backup)
        with fixture_connect(self.db) as con:
            self.assertEqual({tuple(row) for row in con.execute('select user_id_ref,machine_id,relationship_type from assignments')},
                             {(2,2,'assigned_to'),(1,1,'last_logon_user')})

    def test_seating_fingerprint_detects_alias_ownership_changes(self):
        with fixture_connect(self.db) as con:
            con.execute('create table records(id text primary key,body text)')
            con.execute('create table official_records(id text primary key,body text)');atlas_schema(con)
            alias(con,1,'user_id','sharedalias');before=stamp(con,'official')
            con.execute("update user_aliases set user_id_ref=2 where alias_value='sharedalias'")
            self.assertNotEqual(stamp(con,'official'),before)

    def test_unknown_person_refresh_cannot_inherit_confirmed_desk_link(self):
        path=self.root/'unknown.xlsx';target=self.root/'atlas.db';source=self.root/'new.db'
        sheets=device_sheets();sheets['users']=[sheets['users'][0],['','Original Person','','','','','','','','','']]
        workbook(path,sheets);build(path,target)
        with fixture_connect(target) as con:
            atlas_schema(con);old_key=con.execute('select canonical_key from users').fetchone()[0]
            con.execute('insert into desk_user_links values(?,?,?,?)',('desk-example',old_key,'confirmed','2026-10-07'))
        sheets['users'][1][1]='Different Person';workbook(path,sheets);build(path,source)
        merge_directory(target,source)
        with fixture_connect(target) as con:
            self.assertEqual(con.execute('select user_key from desk_user_links').fetchone()[0],old_key)
            self.assertIsNone(con.execute('select id from users where canonical_key=?',(old_key,)).fetchone())
            self.assertNotEqual(con.execute('select canonical_key from users').fetchone()[0],old_key)


class RoutesMatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        isolate_backend_database()
        from backend import main,viewer
        cls.main=main;cls.viewer=viewer

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'fictional.db'
        with fixture_connect(self.db) as con:
            schema(con);user(con,1,'owner','First Person');user(con,2,'visitor','Second Person')
            machine(con,1,'PC-1.ONE.INVALID','owner','visitor');rebuild_links(con)
        for module,attribute in ((self.main,'MASTER_DB'),(self.viewer,'DB')):
            effect=patch.object(module,attribute,self.db);effect.start();self.addCleanup(effect.stop)
        for name in ('run','ps','wmi_create'):
            effect=patch.object(self.main,name,side_effect=AssertionError('No live transport'));effect.start();self.addCleanup(effect.stop)

    def test_admin_and_viewer_resolve_have_same_shared_machine_context(self):
        self.assertEqual(self.main.master_resolve('PC-1'),self.viewer.resolve('PC-1'))
        data=self.viewer.resolve('PC-1')
        self.assertFalse(data['matched']);self.assertEqual(len(data['users']),2)
        self.assertEqual(data['machine']['name'],'PC-1.ONE.INVALID')

    def test_transport_validation_canonicalizes_unique_fqdn_and_rejects_all_short_collisions(self):
        self.assertEqual(self.main.validate_pc('PC-1'),'PC-1.ONE.INVALID')
        self.assertEqual(self.main.validate_pc('pc-1.one.invalid.'),'PC-1.ONE.INVALID')
        self.assertEqual(self.main.validate_pc('GBRPWMF20847983'),'GBRPWMF20847983')
        with fixture_connect(self.db) as con:machine(con,2,'PC-1.TWO.INVALID')
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as error:self.main.validate_pc('PC-1')
        self.assertEqual(error.exception.status_code,400)
        self.assertIn('Ambiguous',error.exception.detail)
        self.assertEqual(self.main.validate_pc('PC-1.ONE.INVALID'),'PC-1.ONE.INVALID')

    def test_source_ci_collision_and_inventory_only_devices_are_blocked_before_transport(self):
        with fixture_connect(self.db) as con:
            machine(con,2,'INVENTORY-SERIAL:RAW-A',category='iPhone',source_ci='CORPMOBILE')
            machine(con,3,'INVENTORY-SERIAL:RAW-B',category='iPhone',source_ci='CORPMOBILE')
            machine(con,4,'DOMAIN\\PC-2',category='Computer',source_ci='PC-2')
        from fastapi import HTTPException
        for name in ('CORPMOBILE','PC-2'):
            with self.assertRaises(HTTPException):self.main.validate_pc(name)
        self.assertEqual(len(self.viewer.resolve('CORPMOBILE')['machines']),2)

    def test_valid_windows_hostname_cannot_be_mistaken_for_generated_inventory_key(self):
        with fixture_connect(self.db) as con:
            machine(con,2,'INVENTORY-SERIAL-RAW-ABC',category='Computer')
        self.assertEqual(self.main.validate_pc('inventory-serial-raw-abc'),'INVENTORY-SERIAL-RAW-ABC')


if __name__=='__main__':unittest.main()
