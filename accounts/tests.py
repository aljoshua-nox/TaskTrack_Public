from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


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

    def test_login_with_valid_credentials_redirects_to_dashboard(self):
        response = self.client.post(
            reverse('accounts:login'),
            {'username': 'student1', 'password': self.password},
        )
        self.assertRedirects(response, reverse('core:dashboard'))

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
