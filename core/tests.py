from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import ActivityLog, Group, Task


class CoreViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='pass12345')
        self.member = User.objects.create_user(username='member', password='pass12345')
        self.member_two = User.objects.create_user(username='member_two', password='pass12345')
        self.outsider = User.objects.create_user(username='outsider', password='pass12345')

        self.group = Group.objects.create(
            name='Alpha Team',
            description='Group for testing',
            created_by=self.owner,
        )
        self.group.members.add(self.owner, self.member, self.member_two)

        self.task = Task.objects.create(
            title='Initial Task',
            description='Baseline task',
            group=self.group,
            assigned_to=self.member,
            created_by=self.owner,
            deadline=timezone.now() + timedelta(days=2),
            status='PENDING',
        )

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_group_generates_unique_join_code(self):
        another_group = Group.objects.create(
            name='Alpha Team',
            description='Same name, different code',
            created_by=self.owner,
        )
        self.assertEqual(len(self.group.join_code), 8)
        self.assertEqual(len(another_group.join_code), 8)
        self.assertNotEqual(self.group.join_code, another_group.join_code)

    def test_dashboard_shows_user_group_and_task_stats(self):
        self.client.login(username='member', password='pass12345')
        Task.objects.create(
            title='Done Task',
            description='Completed work',
            group=self.group,
            assigned_to=self.member,
            created_by=self.owner,
            deadline=timezone.now() + timedelta(days=1),
            status='COMPLETED',
        )

        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['groups_count'], 1)
        self.assertEqual(response.context['total_assigned'], 2)
        self.assertEqual(response.context['total_completed'], 1)

    def test_group_detail_blocks_non_member(self):
        self.client.login(username='outsider', password='pass12345')
        response = self.client.get(reverse('core:group_detail', args=[self.group.id]))
        self.assertRedirects(response, reverse('core:group_list'))

    def test_group_detail_allows_member(self):
        self.client.login(username='member', password='pass12345')
        response = self.client.get(reverse('core:group_detail', args=[self.group.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['group'], self.group)

    def test_task_create_blocks_non_member(self):
        self.client.login(username='outsider', password='pass12345')
        response = self.client.post(
            reverse('core:task_create', args=[self.group.id]),
            {
                'title': 'Unauthorized Task',
                'description': 'Should not be created',
                'assigned_to': self.member.id,
                'deadline': (timezone.now() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'),
                'file_link': '',
            },
        )
        self.assertRedirects(response, reverse('core:group_list'))
        self.assertFalse(Task.objects.filter(title='Unauthorized Task').exists())

    def test_task_create_blocks_non_leader_member(self):
        self.client.login(username='member', password='pass12345')
        response = self.client.post(
            reverse('core:task_create', args=[self.group.id]),
            {
                'title': 'Member Task',
                'description': 'Should not be created',
                'assigned_to': self.member.id,
                'deadline': (timezone.now() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'),
                'file_link': '',
            },
        )
        self.assertRedirects(response, reverse('core:group_detail', args=[self.group.id]))
        self.assertFalse(Task.objects.filter(title='Member Task').exists())

    def test_task_create_by_leader_creates_task_and_activity(self):
        self.client.login(username='owner', password='pass12345')
        response = self.client.post(
            reverse('core:task_create', args=[self.group.id]),
            {
                'title': 'New Group Task',
                'description': 'Created by owner',
                'assigned_to': self.member.id,
                'deadline': (timezone.now() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'),
                'file_link': 'https://example.com/file',
            },
        )
        self.assertRedirects(response, reverse('core:group_detail', args=[self.group.id]))
        created_task = Task.objects.get(title='New Group Task')
        self.assertEqual(created_task.group, self.group)
        self.assertTrue(
            ActivityLog.objects.filter(
                task=created_task,
                action='TASK_CREATED',
            ).exists()
        )

    def test_task_edit_blocks_non_member(self):
        self.client.login(username='outsider', password='pass12345')
        response = self.client.get(reverse('core:task_edit', args=[self.task.id]))
        self.assertRedirects(response, reverse('core:dashboard'))

    def test_task_edit_blocks_non_leader_member(self):
        self.client.login(username='member', password='pass12345')
        response = self.client.get(reverse('core:task_edit', args=[self.task.id]))
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))

    def test_task_edit_by_leader_updates_fields_and_logs_activity(self):
        self.client.login(username='owner', password='pass12345')
        response = self.client.post(
            reverse('core:task_edit', args=[self.task.id]),
            {
                'title': 'Edited Task Title',
                'description': 'Updated description',
                'assigned_to': self.member_two.id,
                'deadline': (timezone.now() + timedelta(days=5)).strftime('%Y-%m-%dT%H:%M'),
                'file_link': 'https://example.com/edited-file',
            },
        )
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))

        self.task.refresh_from_db()
        self.assertEqual(self.task.title, 'Edited Task Title')
        self.assertEqual(self.task.description, 'Updated description')
        self.assertEqual(self.task.assigned_to, self.member_two)
        self.assertEqual(self.task.file_link, 'https://example.com/edited-file')
        self.assertTrue(
            ActivityLog.objects.filter(
                task=self.task,
                user=self.owner,
                action='TASK_UPDATED',
                description__icontains='edited task',
            ).exists()
        )

    def test_update_task_status_blocks_member_not_assigned_and_not_leader(self):
        self.client.login(username='member_two', password='pass12345')
        response = self.client.post(
            reverse('core:update_task_status', args=[self.task.id]),
            {'status': 'COMPLETED'},
        )
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'PENDING')

    def test_update_task_status_by_assigned_member_works(self):
        self.client.login(username='member', password='pass12345')
        response = self.client.post(
            reverse('core:update_task_status', args=[self.task.id]),
            {'status': 'COMPLETED', 'file_link': 'https://example.com/submission'},
        )
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'COMPLETED')
        self.assertEqual(self.task.file_link, 'https://example.com/submission')
        self.assertIsNotNone(self.task.completed_at)

    def test_update_task_status_by_leader_works(self):
        self.client.login(username='owner', password='pass12345')
        response = self.client.post(
            reverse('core:update_task_status', args=[self.task.id]),
            {'status': 'IN_PROGRESS'},
        )
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'IN_PROGRESS')

    def test_rollback_from_completed_requires_comment(self):
        self.task.status = 'COMPLETED'
        self.task.completed_at = timezone.now()
        self.task.save()
        self.client.login(username='member', password='pass12345')
        response = self.client.post(
            reverse('core:update_task_status', args=[self.task.id]),
            {'status': 'PENDING', 'rollback_comment': ''},
        )
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'COMPLETED')

    def test_rollback_from_completed_with_comment_is_logged(self):
        self.task.status = 'COMPLETED'
        self.task.completed_at = timezone.now()
        self.task.save()
        self.client.login(username='member', password='pass12345')
        response = self.client.post(
            reverse('core:update_task_status', args=[self.task.id]),
            {'status': 'PENDING', 'rollback_comment': 'Marked complete by mistake'},
        )
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'PENDING')
        self.assertIsNone(self.task.completed_at)
        self.assertTrue(
            ActivityLog.objects.filter(
                task=self.task,
                user=self.member,
                action='TASK_UPDATED',
                description__icontains='Reason: Marked complete by mistake',
            ).exists()
        )

    def test_leader_can_delete_task(self):
        self.client.login(username='owner', password='pass12345')
        response = self.client.post(reverse('core:task_delete', args=[self.task.id]))
        self.assertRedirects(response, reverse('core:group_detail', args=[self.group.id]))
        self.assertFalse(Task.objects.filter(id=self.task.id).exists())

    def test_non_leader_cannot_delete_task(self):
        self.client.login(username='member', password='pass12345')
        response = self.client.post(reverse('core:task_delete', args=[self.task.id]))
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))
        self.assertTrue(Task.objects.filter(id=self.task.id).exists())

    def test_leader_can_remove_member(self):
        self.client.login(username='owner', password='pass12345')
        response = self.client.post(
            reverse('core:remove_group_member', args=[self.group.id, self.member_two.id])
        )
        self.assertRedirects(response, reverse('core:group_detail', args=[self.group.id]))
        self.assertFalse(self.group.members.filter(id=self.member_two.id).exists())
        self.assertTrue(
            ActivityLog.objects.filter(
                user=self.owner,
                group=self.group,
                action='MEMBER_REMOVED',
            ).exists()
        )

    def test_non_leader_cannot_remove_member(self):
        self.client.login(username='member', password='pass12345')
        response = self.client.post(
            reverse('core:remove_group_member', args=[self.group.id, self.member_two.id])
        )
        self.assertRedirects(response, reverse('core:group_detail', args=[self.group.id]))
        self.assertTrue(self.group.members.filter(id=self.member_two.id).exists())

    def test_leader_can_delete_group(self):
        self.client.login(username='owner', password='pass12345')
        response = self.client.post(reverse('core:group_delete', args=[self.group.id]))
        self.assertRedirects(response, reverse('core:group_list'))
        self.assertFalse(Group.objects.filter(id=self.group.id).exists())

    def test_non_leader_cannot_delete_group(self):
        self.client.login(username='member', password='pass12345')
        response = self.client.post(reverse('core:group_delete', args=[self.group.id]))
        self.assertRedirects(response, reverse('core:group_detail', args=[self.group.id]))
        self.assertTrue(Group.objects.filter(id=self.group.id).exists())

    def test_my_tasks_separates_pending_and_completed(self):
        Task.objects.create(
            title='Completed Task',
            description='Already done',
            group=self.group,
            assigned_to=self.member,
            created_by=self.owner,
            deadline=timezone.now() + timedelta(days=2),
            status='COMPLETED',
        )
        self.client.login(username='member', password='pass12345')
        response = self.client.get(reverse('core:my_tasks'))
        self.assertEqual(response.status_code, 200)
        pending_titles = {task.title for task in response.context['pending_tasks']}
        completed_titles = {task.title for task in response.context['completed_tasks']}
        self.assertIn('Initial Task', pending_titles)
        self.assertIn('Completed Task', completed_titles)

    def test_join_group_by_code_adds_member_and_logs_activity(self):
        self.client.login(username='outsider', password='pass12345')
        response = self.client.post(
            reverse('core:join_group'),
            {'join_code': self.group.join_code.lower()},
        )
        self.assertRedirects(response, reverse('core:group_detail', args=[self.group.id]))
        self.assertTrue(self.group.members.filter(id=self.outsider.id).exists())
        self.assertTrue(
            ActivityLog.objects.filter(
                user=self.outsider,
                group=self.group,
                action='GROUP_JOINED',
            ).exists()
        )

    def test_join_group_with_invalid_code_does_not_add_member(self):
        self.client.login(username='outsider', password='pass12345')
        response = self.client.post(
            reverse('core:join_group'),
            {'join_code': 'INVALID1'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.group.members.filter(id=self.outsider.id).exists())
