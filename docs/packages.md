# Package states and ownership

Open **Packages** in the IT console sidebar, search **Packages** in the command palette (`Ctrl+K`), or use `Alt+6`. The compact list combines all package folders in your SharePoint-synced repository with imported ServiceNow metadata. Search short name, application, EPP ID, requester, packager, domain or build; filter by state and source coverage. Results are paginated so the full repository remains accessible. Select a row for details and its import date, or inspect its source scripts in Admin.

In **Database → Package data**, choose the ServiceNow `.csv`, click **Validate and preview**, review the counts, then **Back up and save package data**.

In Admin, `Ctrl+K` → **Update package data** opens this upload section directly. **Update users**, **Update devices**, and **Update floor plans** also open their upload sections. Users and devices share one complete workbook containing both tabs; these shortcuts do not import or save anything automatically.

| Export header | Atlas field |
| --- | --- |
| `name` | Short Package Name (required) |
| `u_package_sub_state` | Package State (required) |
| `u_display_name` | Display Name |
| `u_barclays_correlation_id` | Package ID |
| `u_requester` | Requester |
| `assigned_to` | Packager |
| `u_domain` | Domain |
| `u_build` | Build |
| `sys_created_on` | Created |

Display-label headers also work. Additional columns and original date text are retained. UTF-8/BOM, UTF-16 and Windows CSV exports are supported, using comma, semicolon or tab delimiters. Quote fields containing the delimiter. Limit: 10 MB and 20,000 rows.

Upload the raw ServiceNow export without removing repeated short names. Matching uses the **complete short package name**, ignoring case and surrounding spaces only. Atlas selects one whole record per name: the newest valid `sys_updated_on`, `updated_on`, `Updated` or `Updated on` timestamp when available; otherwise the last CSV row. Equal update times also use the last row. Creation date and package state do not set priority, and fields are never combined across conflicting records. The preview shows duplicate counts and up to 20 examples of the selected source rows. Every original header, cell and row number is retained in `source_rows_json`, with the selected row and selection rule; `raw_json` contains the selected record's original cells. Backups preserve this provenance too.

Blank, path-like, multiline and unusually long short names do not stop the import. Their original values are preserved as **Metadata only**, with counts and examples in the preview. Blank-name records use `sys_id`, then package ID, then an original-row hash for identity; unrelated blank records remain separate. Unusual names reconcile by their full literal value without taking a basename, shortening or correcting it. Internal raw-record keys cannot match a SharePoint folder. In Packages, unnamed entries show their display name, package ID or “Unnamed package”, with a “Short name not supplied” label. They stay searchable by their supplied metadata and cannot provide an executable source.

Source folders whose names collide after normalization remain ambiguous and receive no automatic metadata match. CSV-only entries are **Metadata only** and cannot supply an executable package. Source folders absent from the CSV remain available with **No package data**; Atlas never assumes their state is Live. Importing 2,000 rows does not replace an 8,000-folder repository.

Imports add or update only names present in that extract. Metadata absent from a later file stays in place with its original import date. Blank or absent optional fields in a supplied row clear those fields. State reflects the extract, rather than a live ServiceNow query. Manual catalogue names and versions retain precedence. SharePoint folder discovery, installer validation and execution stay unchanged. Each save creates a package-only `package-data-*.json.gz` archive in the active database's adjacent `backups/` directory (normally `data/backups/`) and an import-history record; directory data and floor plans are untouched.

Demo reads stored metadata without scanning the package share or allowing uploads and operations. The hosted Preview shows an empty package-data view until its snapshot includes this data; it does not connect to ServiceNow or SharePoint.
