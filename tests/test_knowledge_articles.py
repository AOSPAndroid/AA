import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_articles import all_articles, excerpt, plain_text, register
from knowledge_base import register as register_diagrams

TOKEN = {'X-Atlas-Token': 'test-token'}


class KnowledgeArticles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'knowledge.sqlite3'
        self.token = patch('atlas_api.TOKEN', 'test-token')
        self.token.start()
        # Same order as backend/main.py: article routes before the diagrams' /api/knowledge/{doc_id}.
        self.app = FastAPI()
        register(self.app, self.path)
        register_diagrams(self.app, self.path)
        self.client = TestClient(self.app)
        self.article = {'title': 'Outlook keeps freezing', 'markdown': '## Fix\n1. Start `outlook.exe /safe`',
                        'tags': ['outlook', ' Outlook ', 'email'], 'categories': ['outlook'], 'revision': 0}

    def tearDown(self):
        self.token.stop()
        self.tmp.cleanup()

    def put(self, article_id, body, headers=TOKEN):
        return self.client.put(f'/api/knowledge/articles/{article_id}', json=body, headers=headers)

    def test_create_read_update_delete_with_revisions(self):
        self.assertEqual(self.client.get('/api/knowledge/articles').json(), {'articles': []})
        self.assertEqual(self.put('outlook', self.article).json()['revision'], 1)
        saved = self.client.get('/api/knowledge/articles/outlook').json()
        self.assertEqual(saved['tags'], ['outlook', 'email'], 'Duplicate tags are dropped, ignoring case')
        self.assertEqual(saved['markdown'], self.article['markdown'])
        self.assertEqual(self.put('outlook', self.article).status_code, 409, 'A stale window cannot overwrite')
        self.article.update(revision=1, title='Outlook freezes')
        self.assertEqual(self.put('outlook', self.article).json()['revision'], 2)
        listed = self.client.get('/api/knowledge/articles').json()['articles']
        self.assertEqual([(a['id'], a['title'], a['excerpt']) for a in listed], [('outlook', 'Outlook freezes', 'Fix Start outlook.exe /safe')])
        self.assertNotIn('markdown', listed[0], 'The list stays small')
        self.assertEqual(saved['created'], self.client.get('/api/knowledge/articles/outlook').json()['created'])
        self.assertEqual(self.client.delete('/api/knowledge/articles/outlook?revision=1', headers=TOKEN).status_code, 409)
        self.assertEqual(self.client.delete('/api/knowledge/articles/outlook?revision=2', headers=TOKEN).status_code, 200)
        self.assertEqual(self.client.get('/api/knowledge/articles/outlook').status_code, 404)

    def test_changes_need_the_session_token(self):
        self.assertEqual(self.put('outlook', self.article, headers={}).status_code, 403)
        self.assertEqual(self.put('outlook', self.article, headers={'X-Atlas-Token': 'wrong'}).status_code, 403)
        self.put('outlook', self.article)
        self.assertEqual(self.client.delete('/api/knowledge/articles/outlook?revision=1').status_code, 403)
        self.assertEqual(all_articles(self.path)[0]['id'], 'outlook')

    def test_validation(self):
        self.assertEqual(self.put('bad id!', self.article).status_code, 400)
        self.assertEqual(self.put('x', {**self.article, 'categories': ['unknown']}).status_code, 422)
        self.assertEqual(self.put('x', {**self.article, 'title': ''}).status_code, 422)
        self.assertEqual(self.put('x', {**self.article, 'markdown': 'x' * 200001}).status_code, 422)
        self.assertEqual(self.client.get('/api/knowledge/articles').json()['articles'], [])
        categories = self.client.get('/api/knowledge/article-categories').json()['categories']
        self.assertIn({'id': 'outlook', 'label': 'Outlook or email'}, categories)

    def test_articles_and_diagrams_share_the_file_without_route_clashes(self):
        self.put('outlook', self.article)
        diagram = {'title': 'Network', 'notes': '', 'revision': 0,
                   'xml': '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>'}
        self.assertEqual(self.client.put('/api/knowledge/network', json=diagram).status_code, 200)
        self.assertEqual([d['id'] for d in self.client.get('/api/knowledge').json()['documents']], ['network'])
        self.assertEqual(len(self.client.get('/api/knowledge/articles').json()['articles']), 1)
        self.assertEqual(all_articles(Path(self.tmp.name) / 'missing.sqlite3'), [])

    def test_plain_text_for_search_and_excerpts(self):
        markdown = ('## Checks\n- [ ] Machine replies to ping\n- [x] VPN group in **AD groups**\n\n| A | B |\n| --- | --- |\n'
                    '| x | y |\n\nSee [the wiki](http://wiki)\n\n```powershell\ngpupdate /force\n```\n')
        self.assertEqual(plain_text(markdown), 'Checks Machine replies to ping VPN group in AD groups A B x y See the wiki gpupdate /force')
        self.assertEqual(excerpt(markdown), 'Checks Machine replies to ping VPN group in AD groups A B x y See the wiki')
        self.assertEqual(excerpt('word ' * 100)[-1], '…')


if __name__ == '__main__':
    unittest.main()
