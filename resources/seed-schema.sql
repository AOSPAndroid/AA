CREATE VIEW user_machine_links as select u.canonical_key,u.user_id as login_id,u.employee_number as brid,u.email,u.full_name,m.machine_name,a.relationship_type from assignments a join users u on u.id=a.user_id_ref join machines m on m.id=a.machine_id;
CREATE TABLE assignments(id integer primary key,user_id_ref integer,machine_id integer,relationship_type text,source_value text,unique(user_id_ref,machine_id,relationship_type));
CREATE TABLE atlas_imports(digest text primary key,at text not null);
CREATE TABLE deployments(id text primary key,started text,finished text,operator text,target text,package text,action text,script text,mode text,state text,robocopy_code text,pid text,exit_code text,details text);
CREATE TABLE desk_deployments(job_id text primary key,desk_id text not null,user_key text,target text not null,desk_revision integer,created_at text not null);
CREATE TABLE desk_link_history(seq integer primary key,desk_id text,at text,action text,before_key text,after_key text);
CREATE TABLE desk_user_links(desk_id text primary key,user_key text not null,method text not null,updated_at text not null);
CREATE TABLE directory_export_rows(sheet text not null,row_number integer not null,entity_key text not null,cells text not null,primary key(sheet,row_number));
CREATE TABLE directory_export_sheets(sheet text primary key,kind text not null,source_file text not null,headers text not null,populated text not null,row_count integer not null,linked_count integer not null);
CREATE TABLE directory_import_history(id text primary key,at text,source text,backup text,report text);
CREATE TABLE history(seq INTEGER PRIMARY KEY, desk_id TEXT NOT NULL, at TEXT NOT NULL, action TEXT NOT NULL, before_json TEXT, after_json TEXT NOT NULL);
CREATE TABLE machines(id integer primary key,machine_name text,machine_name_norm text unique,infrastructure_itsi text,sys_class_name text,operational_status text,correlation_id text,serial_number text,manufacturer text,model_id text,short_description text,updated_on text,last_discovered text,discovery_source text,assigned_to text,last_logon_user text);
CREATE TABLE metadata(key text primary key,value text);
CREATE TABLE official_records(id text primary key,body text not null);
CREATE TABLE official_seating_mappings(legacy_id text primary key,official_id text unique,at text);
CREATE TABLE package_catalog(
 repository text not null,folder text not null,display_name text not null default '',
 version text not null default '',revision integer not null default 1,updated_at text not null,
 primary key(repository,folder));
CREATE TABLE records(id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE user_aliases(id integer primary key,user_id_ref integer,alias_type text,alias_value text,alias_norm text,unique(alias_type,alias_norm,user_id_ref));
CREATE TABLE users(id integer primary key,canonical_key text unique,user_id text,user_id_norm text,full_name text,full_name_norm text,email text,email_norm text,organisational_unit text,business_unit text,start_date text,manager text,location text,last_login text,job_role text,job_type text,employee_number text,department text,last_login_time text);
CREATE INDEX desk_deployments_desk on desk_deployments(desk_id);
CREATE INDEX history_desk ON history(desk_id, seq);
CREATE INDEX ix_alias on user_aliases(alias_norm);
CREATE INDEX ix_assign_machine on assignments(machine_id);
CREATE INDEX ix_assign_user on assignments(user_id_ref);
CREATE INDEX ix_export_entity on directory_export_rows(entity_key,sheet);
CREATE INDEX ix_machine on machines(machine_name_norm);
CREATE INDEX ix_users_email on users(email_norm);
CREATE INDEX ix_users_email_lower ON users(lower(email));
CREATE INDEX ix_users_employee_lower ON users(lower(employee_number));
CREATE INDEX ix_users_login on users(user_id_norm);
CREATE INDEX ix_users_name on users(full_name_norm);
