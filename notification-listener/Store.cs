using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;

namespace Atlas.Notifications
{
    // Windows supplies SQLite. The queue uses the same rollback journal and
    // busy timeout as the Python collector, so the elevated reader needs no writes.
    internal sealed class QueueStore : IDisposable
    {
        private IntPtr db;
        [DllImport("winsqlite3.dll", CallingConvention = CallingConvention.Cdecl, CharSet = CharSet.Unicode)]
        private static extern int sqlite3_open16(string path, out IntPtr db);
        [DllImport("winsqlite3.dll", CallingConvention = CallingConvention.Cdecl)]
        private static extern int sqlite3_close(IntPtr db);
        [DllImport("winsqlite3.dll", CallingConvention = CallingConvention.Cdecl)]
        private static extern int sqlite3_busy_timeout(IntPtr db, int ms);
        [DllImport("winsqlite3.dll", CallingConvention = CallingConvention.Cdecl)]
        private static extern IntPtr sqlite3_errmsg16(IntPtr db);
        [DllImport("winsqlite3.dll", CallingConvention = CallingConvention.Cdecl)]
        private static extern int sqlite3_prepare_v2(IntPtr db, byte[] sql, int size, out IntPtr stmt, IntPtr tail);
        [DllImport("winsqlite3.dll", CallingConvention = CallingConvention.Cdecl, CharSet = CharSet.Unicode)]
        private static extern int sqlite3_bind_text16(IntPtr stmt, int index, string value, int size, IntPtr destructor);
        [DllImport("winsqlite3.dll", CallingConvention = CallingConvention.Cdecl)]
        private static extern int sqlite3_step(IntPtr stmt);
        [DllImport("winsqlite3.dll", CallingConvention = CallingConvention.Cdecl)]
        private static extern int sqlite3_finalize(IntPtr stmt);
        [DllImport("winsqlite3.dll", CallingConvention = CallingConvention.Cdecl)]
        private static extern int sqlite3_column_count(IntPtr stmt);
        [DllImport("winsqlite3.dll", CallingConvention = CallingConvention.Cdecl)]
        private static extern IntPtr sqlite3_column_text16(IntPtr stmt, int column);
        [DllImport("winsqlite3.dll", CallingConvention = CallingConvention.Cdecl)]
        private static extern int sqlite3_changes(IntPtr db);

        public QueueStore(string directory)
        {
            try
            {
                Check(sqlite3_open16(Path.Combine(directory, "inbox.sqlite3"), out db));
                Check(sqlite3_busy_timeout(db, 10000));
                using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("inbox_schema.sql"))
                using (var reader = new StreamReader(stream))
                    foreach (var statement in reader.ReadToEnd().Split(';'))
                        if (!String.IsNullOrWhiteSpace(statement)) Run(statement);
                Run("BEGIN IMMEDIATE");
                try
                {
                    var columns = new HashSet<string>(Run("PRAGMA table_info(messages)").Select(row => row[1]));
                    foreach (var field in new[] { new[] { "channel", "outlook" }, new[] { "content_kind", "mail" }, new[] { "app_name", "" } })
                        if (!columns.Contains(field[0])) Run("ALTER TABLE messages ADD COLUMN " + field[0] + " TEXT NOT NULL DEFAULT '" + field[1] + "'");
                    Run("COMMIT");
                }
                catch { Run("ROLLBACK"); throw; }
            }
            catch { Dispose(); throw; }
        }
        private void Check(int result)
        {
            if (result != 0) throw new IOException("Local inbox: " + Marshal.PtrToStringUni(sqlite3_errmsg16(db)));
        }
        internal List<string[]> Run(string sql, params string[] values)
        {
            IntPtr stmt;
            Check(sqlite3_prepare_v2(db, Encoding.UTF8.GetBytes(sql + "\0"), -1, out stmt, IntPtr.Zero));
            try
            {
                for (int i = 0; i < values.Length; i++) Check(sqlite3_bind_text16(stmt, i + 1, values[i] ?? "", -1, new IntPtr(-1)));
                var rows = new List<string[]>();
                int code;
                while ((code = sqlite3_step(stmt)) == 100)
                {
                    var row = new string[sqlite3_column_count(stmt)];
                    for (int i = 0; i < row.Length; i++) row[i] = Marshal.PtrToStringUni(sqlite3_column_text16(stmt, i)) ?? "";
                    rows.Add(row);
                }
                if (code != 101) Check(code);
                return rows;
            }
            finally { sqlite3_finalize(stmt); }
        }
        public DateTimeOffset Since()
        {
            Run("INSERT OR IGNORE INTO notification_state(key,value) VALUES('since',?)", DateTimeOffset.UtcNow.ToString("o"));
            return DateTimeOffset.Parse(Run("SELECT value FROM notification_state WHERE key='since'")[0][0]);
        }
        public bool Add(string channel, string appId, string appName, uint id, DateTimeOffset created, string[] text)
        {
            if (channel != "teams" && channel != "outlook") throw new ArgumentException("Unsupported source");
            var parts = (text ?? new string[0]).Select(value => Clip(value, 16000)).ToArray();
            var title = parts.FirstOrDefault() ?? "";
            var body = Clip(String.Join("\n", parts.Skip(1)), 32000);
            // Content hash preserves a changed notification as another preview,
            // while identical snapshots and restarts are idempotent.
            var payload = new JavaScriptSerializer().Serialize(new[] { created.ToUniversalTime().ToString("o"), id.ToString(), title, body });
            string key;
            using (var sha = SHA256.Create()) key = BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(payload))).Replace("-", "");
            Run("INSERT OR IGNORE INTO messages(source,entry_id,received_at,imported_at,conversation_id,sender_name,sender_address,subject,body,body_truncated,channel,content_kind,app_name) VALUES(?,?,?,?,?,?,?,?,?,0,?,'notification',?)",
                "notification:" + appId, key, created.ToUniversalTime().ToString("o"), DateTimeOffset.UtcNow.ToString("o"), "", Clip(title, 512), "",
                title.Length == 0 ? (channel == "teams" ? "Teams notification" : "Outlook notification") : Clip(title, 512), body, channel, Clip(appName, 256));
            return sqlite3_changes(db) != 0;
        }
        internal static string Clip(string value, int max)
        {
            value = value ?? "";
            if (value.Length <= max) return value;
            if (Char.IsHighSurrogate(value[max - 1])) max--;
            return value.Substring(0, max);
        }
        public void Dispose() { if (db != IntPtr.Zero) { sqlite3_close(db); db = IntPtr.Zero; } }
    }

    internal sealed class ListenerCommand
    {
        public string id { get; set; }
        public string operation { get; set; }
        public bool outlook_previews { get; set; }
        public string expires_at { get; set; }
        public static ListenerCommand Read(string path)
        {
            try
            {
                if (!File.Exists(path) || new FileInfo(path).Length > 8192) return null;
                var command = new JavaScriptSerializer().Deserialize<ListenerCommand>(File.ReadAllText(path));
                DateTimeOffset expires;
                if (command == null || String.IsNullOrEmpty(command.id) || command.id.Length > 64 ||
                    !new[] { "start", "pause", "exit", "start_show", "pause_show" }.Contains(command.operation) ||
                    !DateTimeOffset.TryParse(command.expires_at, out expires) ||
                    expires < DateTimeOffset.UtcNow || expires > DateTimeOffset.UtcNow.AddSeconds(45)) return null;
                return command;
            }
            catch (IOException) { return null; }
            catch (UnauthorizedAccessException) { return null; }
            catch (ArgumentException) { return null; }
            catch (InvalidOperationException) { return null; }
        }
    }

    internal sealed class Settings
    {
        public string Directory { get; set; }
        public bool OutlookEnabled { get; set; }
        public string ExtraTeamsId { get; set; }
        public string ExtraOutlookId { get; set; }
        private static readonly string[] TeamsIds = { "MSTeams_8wekyb3d8bbwe!MSTeams", "MicrosoftTeams_8wekyb3d8bbwe!MicrosoftTeams", "com.squirrel.Teams.Teams" };
        private static readonly string[] OutlookIds = { "Microsoft.Office.OUTLOOK.EXE.15", "Microsoft.OutlookForWindows_8wekyb3d8bbwe!Microsoft.OutlookforWindows" };
        public string Source(string id)
        {
            if (String.IsNullOrEmpty(id)) return null;
            if (TeamsIds.Contains(id, StringComparer.OrdinalIgnoreCase) || String.Equals(id, ExtraTeamsId, StringComparison.OrdinalIgnoreCase)) return "teams";
            if (OutlookEnabled && (OutlookIds.Contains(id, StringComparer.OrdinalIgnoreCase) || String.Equals(id, ExtraOutlookId, StringComparison.OrdinalIgnoreCase))) return "outlook";
            return null;
        }
    }
    internal static class JsonFile
    {
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool MoveFileEx(string existing, string destination, int flags);
        public static void Write(string path, object data)
        {
            string temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                File.WriteAllText(temp, new JavaScriptSerializer().Serialize(data), new UTF8Encoding(false));
                if (!MoveFileEx(temp, path, 1 | 8)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            }
            finally { if (File.Exists(temp)) File.Delete(temp); }
        }
    }
}
