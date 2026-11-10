from sqlite_fixture import isolate_backend_database
isolate_backend_database()
import unittest
from backend import main

class WorkspaceToday(unittest.TestCase):
    def test_today_uses_server_date_and_keeps_recorded_status(self):
        with main.hist_db() as c:
            c.execute('delete from deployments')
            for key, offset, state in [('old','-1 day','complete'),('new','+0 day','launched')]:
                c.execute('insert into deployments(id,started,state,target) values(?,datetime("now","localtime",?),?,?)',(key,offset,state,'PC'))
            c.commit()
        rows = main.history(limit=6,today=True)
        self.assertEqual([(r['id'],r['state']) for r in rows],[('new','launched')])
        self.assertEqual(len(main.history()),2)

if __name__ == '__main__': unittest.main()
