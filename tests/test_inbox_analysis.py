import unittest

from backend.inbox.inbox_analysis import analyse, hostname_candidates, latest_text, match_packages, plain

PACKAGES = [
    {'folder': 'Microsoft_PowerBI_Desktop_2.130', 'display_name': 'Microsoft Power BI Desktop'},
    {'folder': 'Adobe_Acrobat_Reader_DC', 'display_name': 'Adobe Acrobat Reader DC'},
    {'folder': 'Notepad++_8.6', 'display_name': 'Notepad++'},
    {'folder': 'Bloomberg_Terminal', 'display_name': 'Bloomberg Terminal'},
    {'folder': 'Microsoft_Teams', 'display_name': 'Microsoft Teams'},
    {'folder': 'Example App', 'display_name': 'Example App'},
    {'folder': '7-Zip', 'display_name': '7-Zip'},
]
INVENTORY = {'gbrpwmk20881521': {'name': 'GBRPWMK20881521', 'device_kind': 'laptop'},
             'example-desktop-02': {'name': 'EXAMPLE-DESKTOP-02', 'device_kind': 'desktop'}}


def run(subject, body, **options):
    options.setdefault('packages', PACKAGES)
    options.setdefault('find_machines', lambda names: [INVENTORY[n] for n in names if n in INVENTORY])
    return analyse(subject, body, **options)


class SoftwareRequests(unittest.TestCase):
    def test_install_request_in_english_matches_partial_product_name(self):
        result = run('Install request', 'Hi, could you please install Power BI on my laptop? Thanks')
        self.assertEqual((result['kind'], result['action']), ('software', 'Install'))
        self.assertEqual(result['packages'][0]['folder'], 'Microsoft_PowerBI_Desktop_2.130')

    def test_french_request_and_accents(self):
        result = run('Demande', 'Bonjour, pourriez-vous installer Notepad++ sur mon poste ? Merci')
        self.assertEqual((result['kind'], result['action']), ('software', 'Install'))
        self.assertEqual(result['packages'][0]['display_name'], 'Notepad++')
        self.assertEqual(run('Désinstallation', 'Merci de désinstaller 7-Zip')['action'], 'Uninstall')

    def test_vendor_word_alone_is_not_enough_but_with_product_it_is(self):
        self.assertEqual(run('Request', 'Can I get Adobe Reader please')['packages'][0]['folder'], 'Adobe_Acrobat_Reader_DC')
        self.assertEqual(run('Request', 'Please install something from Microsoft')['packages'], [])

    def test_issue_naming_a_package_suggests_repair(self):
        result = run('Teams', 'Microsoft Teams keeps crashing since this morning')
        self.assertEqual((result['kind'], result['action']), ('software', 'Repair'))
        self.assertEqual(result['packages'][0]['folder'], 'Microsoft_Teams')
        self.assertIn('crash', [c['id'] for c in result['categories']])

    def test_unknown_software_gives_a_catalogue_search_hint(self):
        result = run('Install', 'Hi, please install the Foo Bar Studio on my laptop')
        self.assertEqual((result['kind'], result['packages'], result['search']), ('software', [], 'foo bar studio'))

    def test_past_tense_install_in_an_issue_is_not_a_request(self):
        result = run('Screen', 'I installed the update and now my screen flickers')
        self.assertEqual((result['kind'], result['action']), ('issue', None))


class Issues(unittest.TestCase):
    def test_categories_tools_and_named_machine(self):
        result = run('Help', 'My PC GBRPWMK20881521 is very slow and Outlook freezes', linked=['GBRPWMK20881521'])
        self.assertEqual(result['kind'], 'issue')
        self.assertEqual([c['id'] for c in result['categories']], ['slow', 'outlook'])
        self.assertEqual(result['tools'][:3], ['performance', 'health', 'reboot'])
        self.assertEqual(result['machines'], [{'name': 'GBRPWMK20881521', 'device_kind': 'laptop', 'linked': True}])

    def test_machine_name_words_do_not_match_packages(self):
        result = run('PC very slow', 'EXAMPLE-DESKTOP-02 is very slow')
        self.assertEqual(result['packages'], [])
        self.assertEqual(result['machines'][0]['name'], 'EXAMPLE-DESKTOP-02')
        self.assertFalse(result['machines'][0]['linked'])

    def test_email_addresses_do_not_match_packages(self):
        result = run('Help', 'Outlook keeps freezing. Contact me at alex@example.test')
        self.assertEqual((result['kind'], result['packages']), ('issue', []))

    def test_french_issue(self):
        result = run('Compte', 'Mon compte est verrouillé, mot de passe expiré')
        self.assertEqual([c['id'] for c in result['categories']], ['account'])
        self.assertEqual(result['tools'], ['user-groups'])

    def test_quoted_history_is_ignored(self):
        body = 'Thanks, all good now.\n\nFrom: IT Support\nSent: Monday\nPlease install Power BI. My PC is slow.'
        self.assertEqual(run('RE: request', body)['kind'], 'other')
        self.assertNotIn('Power BI', latest_text('RE', body))

    def test_plain_message_has_no_suggestions(self):
        result = run('Thanks', 'Thank you for your help yesterday')
        self.assertEqual((result['kind'], result['action'], result['packages'], result['tools']), ('other', None, [], []))


class Helpers(unittest.TestCase):
    def test_plain_text(self):
        self.assertEqual(plain("Réseau: l'imprimante  ne-marche PAS!"), 'reseau limprimante ne marche pas')

    def test_hostname_candidates_need_letters_and_digits(self):
        self.assertEqual(hostname_candidates('PC GBRPWMK20881521, INC0012345 and hello world 2026'),
                         ['gbrpwmk20881521', 'inc0012345'])

    def test_knowledge_documents_rank_by_title_then_notes(self):
        documents = [{'id': 'a', 'title': 'Printer setup', 'notes': ''}, {'id': 'b', 'title': 'Misc', 'notes': 'printer queue'},
                     {'id': 'c', 'title': 'VPN', 'notes': 'nothing relevant'}]
        result = run('Printer', 'I cannot print', documents=documents)
        self.assertEqual([d['id'] for d in result['knowledge']], ['a', 'b'])

    def test_package_ranking_is_limited(self):
        many = [{'folder': f'Tool {n}', 'display_name': f'Widget Tool {n}'} for n in range(10)]
        self.assertEqual(len(match_packages(plain('install widget'), many)), 5)


if __name__ == '__main__':
    unittest.main()
