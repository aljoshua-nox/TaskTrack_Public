from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AccountViewTests(TestCase):
    def setUp(self):
        self.password = 'pass12345'
        self.user = User.objects.create_user(username='student1', password=self.password)

    def test_register_creates_user_and_redirects_to_dashboard(self):
        response = self.client.post(
            reverse('accounts:register'),
            {
                'username': 'newstudent',
                'password1': 'newpass12345',
                'password2': 'newpass12345',
            },
        )
        self.assertRedirects(response, reverse('core:dashboard'))
        self.assertTrue(User.objects.filter(username='newstudent').exists())

    def test_register_page_uses_styled_layout_without_email_field(self):
        response = self.client.get(reverse('accounts:register'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'fa-user-plus')
        self.assertNotContains(response, 'type="email"')

    def test_login_with_valid_credentials_redirects_to_dashboard(self):
        response = self.client.post(
            reverse('accounts:login'),
            {'username': 'student1', 'password': self.password},
        )
        self.assertRedirects(response, reverse('core:dashboard'))

    def test_login_page_uses_updated_layout(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Welcome back')
        self.assertContains(response, 'What is TaskTrack about?')
        self.assertContains(response, "Don't have an account?")

    def test_login_with_invalid_credentials_stays_on_login_page(self):
        response = self.client.post(
            reverse('accounts:login'),
            {'username': 'student1', 'password': 'wrong-pass'},
        )
        self.assertEqual(response.status_code, 200)

    def test_logout_redirects_to_login(self):
        self.client.login(username='student1', password=self.password)
        response = self.client.get(reverse('accounts:logout'))
        self.assertRedirects(response, reverse('accounts:login'))

    def test_login_returns_user_to_requested_page(self):
        login_url = reverse('accounts:login') + '?next=/my-tasks/'
        page = self.client.get(login_url)
        self.assertContains(page, '<input type="hidden" name="next" value="/my-tasks/">', html=True)
        response = self.client.post(login_url, {'username': 'student1', 'password': self.password})
        self.assertRedirects(response, reverse('core:my_tasks'))

    def test_login_ignores_next_pointing_to_another_site(self):
        for next_url in ['https://evil.example/', '//evil.example/', 'javascript:alert(1)']:
            with self.subTest(next_url=next_url):
                self.client.logout()
                response = self.client.post(
                    reverse('accounts:login'),
                    {'username': 'student1', 'password': self.password, 'next': next_url},
                )
                self.assertRedirects(response, reverse('core:dashboard'))

    def test_logout_ends_the_session(self):
        self.client.login(username='student1', password=self.password)
        self.client.get(reverse('accounts:logout'))
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.status_code, 302)

    def test_register_rejects_invalid_submissions(self):
        cases = {
            'mismatched passwords': {'username': 'newbie', 'password1': 'newpass12345', 'password2': 'different12345'},
            'duplicate username': {'username': 'student1', 'password1': 'newpass12345', 'password2': 'newpass12345'},
            'duplicate username, other case': {'username': 'STUDENT1', 'password1': 'newpass12345', 'password2': 'newpass12345'},
            'common password': {'username': 'newbie', 'password1': 'password123', 'password2': 'password123'},
            'numeric password': {'username': 'newbie', 'password1': '84736291057', 'password2': '84736291057'},
            'blank username': {'username': '', 'password1': 'newpass12345', 'password2': 'newpass12345'},
        }
        for label, data in cases.items():
            with self.subTest(label):
                response = self.client.post(reverse('accounts:register'), data)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)
        self.assertEqual(User.objects.count(), 1)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_with_unknown_user_is_rejected(self):
        response = self.client.post(
            reverse('accounts:login'),
            {'username': 'ghost', 'password': self.password},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_inactive_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(
            reverse('accounts:login'),
            {'username': 'student1', 'password': self.password},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
